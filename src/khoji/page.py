"""`KhojiPage`: one browser tab, with block detection on navigation and typed extraction."""

import time
from typing import Literal, Self

from patchright.async_api import Error as PatchrightError
from patchright.async_api import Page, Response
from pydantic import BaseModel

from .config import KhojiConfig
from .errors import BlockedError, NavigationError
from .extract import Extractor

WaitUntil = Literal["commit", "domcontentloaded", "load", "networkidle"]
"""Load state a navigation waits for before it returns."""

# HTTP statuses that mean the site refused the request.
_BLOCK_STATUSES = frozenset({403, 429})
# Lower-cased fragments of page titles used by anti-bot challenge pages.
_CHALLENGE_TITLES = (
    "just a moment",  # Cloudflare
    "attention required",  # Cloudflare
    "access denied",  # Akamai
    "pardon our interruption",  # Imperva
)
# Elements that only exist on anti-bot challenge pages.
_CHALLENGE_SELECTORS = (
    "#challenge-form",  # Cloudflare
    "#challenge-running",
    "#cf-challenge-running",
    "#challenge-error-text",
    "iframe[src*='captcha-delivery.com']",  # DataDome
    "#px-captcha",  # PerimeterX
)
_CHALLENGE_SELECTOR = ", ".join(_CHALLENGE_SELECTORS)
# Gap between checks while waiting for a challenge to clear.
_POLL_MS = 250


class KhojiPage:
    """A browser tab. `raw` exposes the underlying Patchright page for anything not covered here."""

    def __init__(self, page: Page, config: KhojiConfig, extractor: Extractor | None = None) -> None:
        """Wrap a Patchright page.

        Args:
            page: The Patchright page to wrap.
            config: Browser settings; controls block detection and the challenge wait.
            extractor: Builds models for `extract` and `extract_all`. Defaults to `Extractor()`.
        """
        self._page = page
        self._config = config
        self._extractor = extractor or Extractor()

    @property
    def raw(self) -> Page:
        """The underlying Patchright page, for clicks, waits and anything not covered here."""
        return self._page

    @property
    def url(self) -> str:
        """The tab's current URL."""
        return self._page.url

    async def goto(self, url: str, *, wait_until: WaitUntil = "domcontentloaded") -> Self:
        """Navigate to `url`, then check the result for blocks unless detection is disabled.

        Args:
            url: Absolute URL to open.
            wait_until: Load state to wait for before returning.

        Returns:
            This page, so the call can be chained.

        Raises:
            NavigationError: If the page could not be loaded.
            BlockedError: If the site answered with a block or a challenge that did not clear.
        """
        try:
            response = await self._page.goto(url, wait_until=wait_until)
        except PatchrightError as exc:
            raise NavigationError(f"Could not open {url}: {exc}") from exc
        if self._config.block_detection:
            await self._raise_if_blocked(url, response)
        return self

    async def html(self) -> str:
        """Return the page's current HTML, as rendered after scripts have run."""
        return await self._page.content()

    async def extract[M: BaseModel](self, model: type[M], *, root: str | None = None) -> M:
        """Build one `model` from the page, or from the first element matching `root`.

        Args:
            model: Pydantic model whose fields carry `Selector` metadata.
            root: CSS selector that scopes the extraction to one element. None means the
                whole page.

        Returns:
            A validated instance of `model`.

        Raises:
            ExtractionError: If the page does not satisfy the model.
        """
        scope = self._page if root is None else self._page.locator(root).first
        return await self._extractor.extract(scope, model, url=self.url)

    async def extract_all[M: BaseModel](self, model: type[M], *, root: str) -> list[M]:
        """Build one `model` per element matching `root`.

        Args:
            model: Pydantic model whose fields carry `Selector` metadata.
            root: CSS selector matching the repeated elements, e.g. one per product card.

        Returns:
            One validated instance per match, in document order. Empty if nothing matches.

        Raises:
            ExtractionError: If any matched element does not satisfy the model.
        """
        elements = await self._page.locator(root).all()
        return [await self._extractor.extract(element, model, url=self.url) for element in elements]

    async def close(self) -> None:
        """Close the tab."""
        await self._page.close()

    async def _challenge(self) -> str | None:
        """Check whether the page currently shows an anti-bot challenge.

        Returns:
            A short description of what gave the challenge away, or None if the page looks
            normal.
        """
        title = (await self._page.title()).lower()
        for marker in _CHALLENGE_TITLES:
            if marker in title:
                return f"page title {marker!r}"
        if await self._page.locator(_CHALLENGE_SELECTOR).count():
            return "challenge element on page"
        return None

    async def _raise_if_blocked(self, url: str, response: Response | None) -> None:
        """Wait for any challenge to clear, then raise if the page is still blocked.

        Polls until the page shows no challenge or `challenge_wait_ms` runs out. A challenge
        that clears by itself is not a block, even though it was served with a 403.

        Args:
            url: The URL that was requested, used in error messages.
            response: The navigation's response, or None if there was none.

        Raises:
            BlockedError: If a challenge did not clear in time, or the response status was
                403 or 429 with no challenge involved.
        """
        status = response.status if response is not None else None
        deadline = time.monotonic() + self._config.challenge_wait_ms / 1000
        challenged = False
        while True:
            try:
                reason = await self._challenge()
            except PatchrightError:
                # The page is navigating underneath us, typically a challenge redirecting on.
                reason = "page still navigating"
            else:
                if reason is None:
                    break
                challenged = True
            if time.monotonic() >= deadline:
                raise BlockedError(
                    f"Anti-bot challenge did not clear on {url} ({reason})", url=url, status=status
                )
            await self._page.wait_for_timeout(_POLL_MS)
        # A challenge that cleared was served with a 403 too, so only trust the status
        # when no challenge was involved.
        if not challenged and status in _BLOCK_STATUSES:
            raise BlockedError(f"{url} answered HTTP {status}", url=url, status=status)
