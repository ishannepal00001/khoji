import time
from typing import Literal, Self

from patchright.async_api import Error as PatchrightError
from patchright.async_api import Page, Response
from pydantic import BaseModel

from .config import KhojiConfig
from .errors import BlockedError, NavigationError
from .extract import extract_model

WaitUntil = Literal["commit", "domcontentloaded", "load", "networkidle"]

_BLOCK_STATUSES = frozenset({403, 429})
_CHALLENGE_TITLES = (
    "just a moment",  # Cloudflare
    "attention required",  # Cloudflare
    "access denied",  # Akamai
    "pardon our interruption",  # Imperva
)
_CHALLENGE_SELECTORS = (
    "#challenge-form",  # Cloudflare
    "#challenge-running",
    "#cf-challenge-running",
    "#challenge-error-text",
    "iframe[src*='captcha-delivery.com']",  # DataDome
    "#px-captcha",  # PerimeterX
)
_CHALLENGE_SELECTOR = ", ".join(_CHALLENGE_SELECTORS)
_POLL_MS = 250


class KhojiPage:
    """A browser tab. `raw` exposes the underlying Patchright page for anything not covered here."""

    def __init__(self, page: Page, config: KhojiConfig) -> None:
        self._page = page
        self._config = config

    @property
    def raw(self) -> Page:
        return self._page

    @property
    def url(self) -> str:
        return self._page.url

    async def goto(self, url: str, *, wait_until: WaitUntil = "domcontentloaded") -> Self:
        try:
            response = await self._page.goto(url, wait_until=wait_until)
        except PatchrightError as exc:
            raise NavigationError(f"Could not open {url}: {exc}") from exc
        if self._config.block_detection:
            await self._raise_if_blocked(url, response)
        return self

    async def html(self) -> str:
        return await self._page.content()

    async def extract[M: BaseModel](self, model: type[M], *, root: str | None = None) -> M:
        """Build one `model` from the page, or from the first element matching `root`."""
        scope = self._page if root is None else self._page.locator(root).first
        return await extract_model(scope, model, url=self.url)

    async def extract_all[M: BaseModel](self, model: type[M], *, root: str) -> list[M]:
        """Build one `model` per element matching `root`."""
        elements = await self._page.locator(root).all()
        return [await extract_model(element, model, url=self.url) for element in elements]

    async def close(self) -> None:
        await self._page.close()

    async def _challenge(self) -> str | None:
        title = (await self._page.title()).lower()
        for marker in _CHALLENGE_TITLES:
            if marker in title:
                return f"page title {marker!r}"
        if await self._page.locator(_CHALLENGE_SELECTOR).count():
            return "challenge element on page"
        return None

    async def _raise_if_blocked(self, url: str, response: Response | None) -> None:
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
