"""`KhojiPage`: one browser tab, with block detection on navigation and typed extraction."""

import logging
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Self
from urllib.parse import urldefrag, urlparse

from patchright.async_api import Error as PatchrightError
from patchright.async_api import Page, Response
from pydantic import BaseModel

from .config import KhojiConfig
from .errors import BlockedError, KhojiError, NavigationError
from .extract import Extractor
from .models import Link, ScrollResult

log = logging.getLogger(__name__)

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
# Share of the visible height moved by one scroll step, so consecutive views overlap.
_SCROLL_STEP = 0.8
# Pixels short of the bottom that still count as being at the bottom (sub-pixel rounding).
_SCROLL_SLACK = 2

# Runs in the page. Finds what to scroll, optionally scrolls it by `by` pixels, and reports
# its position plus a point inside it for the mouse. With no selector it takes the document
# when that can scroll, else the largest scrollable element (feeds that live in an inner div).
_SCROLL_STATE_JS = """
({selector, by}) => {
  const canScroll = el => el.scrollHeight - el.clientHeight > 2;
  const hidden = el => !!el && getComputedStyle(el).overflowY === 'hidden';
  const doc = document.scrollingElement || document.documentElement;
  let target = null;
  if (selector) target = document.querySelector(selector);
  else if (canScroll(doc) && !hidden(document.documentElement) && !hidden(document.body)) target = doc;
  else {
    let best = 0;
    for (const el of document.body ? document.body.querySelectorAll('*') : []) {
      if (!canScroll(el) || !['auto', 'scroll', 'overlay'].includes(getComputedStyle(el).overflowY)) continue;
      const box = el.getBoundingClientRect();
      if (box.width * box.height > best) { best = box.width * box.height; target = el; }
    }
  }
  if (!target) return null;
  if (by) target.scrollBy(0, by);
  const box = target === doc
    ? {left: 0, top: 0, right: innerWidth, bottom: innerHeight}
    : target.getBoundingClientRect();
  const left = Math.max(box.left, 0), right = Math.min(box.right, innerWidth);
  const top = Math.max(box.top, 0), bottom = Math.min(box.bottom, innerHeight);
  return {
    top: target.scrollTop, client: target.clientHeight, height: target.scrollHeight,
    x: (left + right) / 2, y: (top + bottom) / 2,
  };
}
"""

# Runs in the page, on an element or the whole document. One call gives a consistent snapshot.
_LINKS_JS = """
scope => [...(scope || document).querySelectorAll('a[href]')]
  .filter(a => typeof a.href === 'string')  // SVG links hold an object, not a URL
  .map(a => ({
    url: a.href,
    text: (a.innerText || '').replace(/\\s+/g, ' ').trim()
      || a.getAttribute('aria-label') || a.getAttribute('title') || '',
    title: a.getAttribute('title'),
    rel: [...a.relList],
  }))
"""


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

    async def scroll_to_end(
        self,
        *,
        container: str | None = None,
        max_rounds: int = 50,
        timeout_ms: int = 30_000,
        pause_ms: tuple[int, int] = (500, 1200),
        settle_checks: int = 2,
    ) -> ScrollResult:
        """Scroll down for as long as the page can go further, loading lazy and infinite content.

        Scrolls with the mouse wheel, so scroll listeners and lazy loaders fire as they would
        for a person. At the bottom it keeps checking for `settle_checks` pauses in case more
        content is still loading. A page that cannot scroll returns at once.

        Args:
            container: CSS selector of the element to scroll. None picks the document, or the
                largest scrollable element when the document itself cannot scroll.
            max_rounds: Most scroll steps to take before giving up.
            timeout_ms: Most time to spend scrolling before giving up.
            pause_ms: Range of the random pause after each step, in milliseconds.
            settle_checks: Pauses at the bottom with no new content before it counts as the end.

        Returns:
            How many steps were taken, the final scroll height, and whether the end was reached.

        Raises:
            KhojiError: If `container` matches no element.
        """
        deadline = time.monotonic() + timeout_ms / 1000
        state = await self._scroll_state(container)
        if state is None:
            if container is not None:
                raise KhojiError(f"No element matches {container!r} on {self.url}")
            return ScrollResult(rounds=0, height=0, reached_end=True)
        if not self._can_scroll_down(state):
            return ScrollResult(rounds=0, height=state["height"], reached_end=True)

        rounds = idle = 0
        use_wheel = True
        while True:
            if self._can_scroll_down(state):
                if rounds >= max_rounds or time.monotonic() >= deadline:
                    log.info("Stopped scrolling %s after %d steps, before the end", self.url, rounds)
                    return ScrollResult(rounds=rounds, height=state["height"], reached_end=False)
                step = round(state["client"] * _SCROLL_STEP * random.uniform(0.85, 1.15))
                if use_wheel:
                    await self._page.mouse.move(state["x"], state["y"])
                    await self._page.mouse.wheel(0, step)
                else:
                    await self._scroll_state(container, by=step)
                rounds += 1
                idle = 0
            elif idle >= settle_checks:
                return ScrollResult(rounds=rounds, height=state["height"], reached_end=True)
            else:
                idle += 1
            await self._page.wait_for_timeout(random.randint(*pause_ms))
            previous, state = state, await self._scroll_state(container)
            if state is None:  # the scrolled element went away, e.g. the page re-rendered
                return ScrollResult(rounds=rounds, height=previous["height"], reached_end=True)
            if use_wheel and idle == 0 and state["top"] <= previous["top"] and self._can_scroll_down(state):
                # The wheel landed on something else (an overlay, a fixed header); scroll directly.
                use_wheel = False

    async def links(
        self,
        *,
        root: str | None = None,
        internal: bool | None = None,
        schemes: tuple[str, ...] = ("http", "https"),
    ) -> list[Link]:
        """Return the links currently on the page, once each, in document order.

        Read from the live page, so links loaded by `scroll_to_end` are included. URLs are
        absolute and have their `#fragment` removed, so anchors into the same page collapse
        into one link.

        Args:
            root: CSS selector that scopes the search to the first matching element. None
                means the whole page.
            internal: True keeps only links to the page's own host, False only links
                elsewhere. None keeps both.
            schemes: URL schemes to keep; mailto:, tel: and javascript: links are dropped by
                default.

        Returns:
            One `Link` per distinct URL, first occurrence first.
        """
        if root is None:
            raw = await self._page.evaluate(_LINKS_JS)
        else:
            raw = await self._page.locator(root).first.evaluate(_LINKS_JS)
        host = urlparse(self.url).hostname
        links: dict[str, Link] = {}
        for item in raw:
            url = urldefrag(item["url"]).url
            parsed = urlparse(url)
            if parsed.scheme not in schemes or url in links:
                continue
            link = Link(**{**item, "url": url}, internal=parsed.hostname == host)
            if internal is None or link.internal == internal:
                links[url] = link
        return list(links.values())

    async def close(self) -> None:
        """Close the tab."""
        await self._page.close()

    async def save_debug(self, directory: Path, label: str) -> Path | None:
        """Save a screenshot and the page HTML, for working out what went wrong.

        Failures to save are logged and never raised, so they cannot hide the original error.

        Args:
            directory: Folder to save into. Created if it does not exist.
            label: Short tag added to the timestamped file names.

        Returns:
            The path of the saved files without their `.png` / `.html` extension, or None if
            saving failed.
        """
        try:
            directory.mkdir(parents=True, exist_ok=True)
            stem = directory / f"{datetime.now():%Y%m%d-%H%M%S}-{label}"
            await self._page.screenshot(path=f"{stem}.png")
            Path(f"{stem}.html").write_text(await self._page.content())
        except (PatchrightError, OSError) as exc:
            log.error("Could not save debug files: %s", exc)
            return None
        log.info("Saved debug files to %s.{png,html}", stem)
        return stem

    async def _scroll_state(self, container: str | None, *, by: int = 0) -> dict[str, Any] | None:
        """Find the element to scroll, optionally scroll it, and report where it stands.

        Args:
            container: CSS selector of the element to scroll, or None to pick one.
            by: Pixels to scroll down directly before reporting. 0 only reads.

        Returns:
            `top`, `client` and `height` (scroll position, visible height, scroll height) and
            `x`, `y` (a viewport point inside the element), or None if there is nothing to scroll.
        """
        return await self._page.evaluate(_SCROLL_STATE_JS, {"selector": container, "by": by})

    @staticmethod
    def _can_scroll_down(state: dict[str, Any]) -> bool:
        """Report whether the element described by `state` has more content below the view."""
        return state["top"] + state["client"] < state["height"] - _SCROLL_SLACK

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
