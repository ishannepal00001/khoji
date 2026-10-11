from typing import TYPE_CHECKING, Self

from patchright.async_api import BrowserContext, Playwright, async_playwright

from .browser import launch
from .config import KhojiConfig
from .errors import KhojiError
from .page import KhojiPage, WaitUntil

if TYPE_CHECKING:
    from .sites.base import Site


class Khoji:
    """Entry point: owns one stealth browser and hands out pages.

    async with Khoji() as k:
        page = await k.open("https://example.com")
        item = await page.extract(Item)
    """

    def __init__(self, config: KhojiConfig | None = None) -> None:
        self.config = config or KhojiConfig()
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None

    @property
    def context(self) -> BrowserContext:
        """The underlying Patchright browser context."""
        if self._context is None:
            raise KhojiError("Khoji is not started; use `async with Khoji() as k:` or call start().")
        return self._context

    async def start(self) -> Self:
        if self._context is not None:
            return self
        self._playwright = await async_playwright().start()
        try:
            self._context = await launch(self._playwright, self.config)
        except BaseException:
            await self.close()
            raise
        return self

    async def close(self) -> None:
        context, self._context = self._context, None
        playwright, self._playwright = self._playwright, None
        try:
            if context is not None:
                await context.close()
        finally:
            if playwright is not None:
                await playwright.stop()

    async def __aenter__(self) -> Self:
        return await self.start()

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def new_page(self) -> KhojiPage:
        context = self.context
        # A persistent context opens with one blank tab; use it before opening more.
        blank = [page for page in context.pages if page.url == "about:blank"]
        page = blank[0] if blank else await context.new_page()
        return KhojiPage(page, self.config)

    async def open(self, url: str, *, wait_until: WaitUntil = "domcontentloaded") -> KhojiPage:
        """Open `url` in a tab and return it once loaded and checked for blocks."""
        page = await self.new_page()
        try:
            return await page.goto(url, wait_until=wait_until)
        except BaseException:
            await page.close()
            raise

    def site[S: "Site"](self, site_cls: type[S]) -> S:
        """Bind a site module to this browser: `books = k.site(Books)`."""
        return site_cls(self)
