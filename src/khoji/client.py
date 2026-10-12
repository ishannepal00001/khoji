"""The `Khoji` client: the library's entry point."""

from typing import TYPE_CHECKING, Self

from patchright.async_api import BrowserContext, Playwright, async_playwright

from .browser import BrowserLauncher
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

    Attributes:
        config: The browser settings this instance was created with.
    """

    def __init__(self, config: KhojiConfig | None = None) -> None:
        """Create a client. The browser is not launched until `start()`.

        Args:
            config: Browser settings. Defaults to `KhojiConfig()`.
        """
        self.config = config or KhojiConfig()
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None

    @property
    def context(self) -> BrowserContext:
        """The underlying Patchright browser context.

        Raises:
            KhojiError: If the browser has not been started.
        """
        if self._context is None:
            raise KhojiError("Khoji is not started; use `async with Khoji() as k:` or call start().")
        return self._context

    async def start(self) -> Self:
        """Launch the browser. Does nothing if it is already running.

        If the launch fails, anything partly started is shut down before the error propagates.

        Returns:
            This instance, so the call can be chained.
        """
        if self._context is not None:
            return self
        self._playwright = await async_playwright().start()
        try:
            self._context = await BrowserLauncher(self.config).launch(self._playwright)
        except BaseException:
            await self.close()
            raise
        return self

    async def close(self) -> None:
        """Close the browser and stop Patchright.

        Safe to call more than once, and on an instance that was never started. Patchright is
        stopped even if closing the browser context fails.
        """
        context, self._context = self._context, None
        playwright, self._playwright = self._playwright, None
        try:
            if context is not None:
                await context.close()
        finally:
            if playwright is not None:
                await playwright.stop()

    async def __aenter__(self) -> Self:
        """Start the browser on entering `async with`.

        Returns:
            This instance.
        """
        return await self.start()

    async def __aexit__(self, *exc_info: object) -> None:
        """Close the browser on leaving `async with`. Exceptions are not suppressed.

        Args:
            *exc_info: Exception type, value and traceback, or three Nones.
        """
        await self.close()

    async def new_page(self) -> KhojiPage:
        """Return a blank tab, reusing the one the browser opened with if it is still unused.

        Returns:
            A page that has not navigated anywhere yet.

        Raises:
            KhojiError: If the browser has not been started.
        """
        context = self.context
        # A persistent context opens with one blank tab; use it before opening more.
        blank = [page for page in context.pages if page.url == "about:blank"]
        page = blank[0] if blank else await context.new_page()
        return KhojiPage(page, self.config)

    async def open(self, url: str, *, wait_until: WaitUntil = "domcontentloaded") -> KhojiPage:
        """Open `url` in a tab and return it once loaded and checked for blocks.

        The tab is closed again if the navigation fails, so failed opens do not leak tabs.

        Args:
            url: Absolute URL to open.
            wait_until: Load state to wait for before returning.

        Returns:
            The loaded page.

        Raises:
            NavigationError: If the page could not be loaded.
            BlockedError: If the site answered with a block or a challenge that did not clear.
            KhojiError: If the browser has not been started.
        """
        page = await self.new_page()
        try:
            return await page.goto(url, wait_until=wait_until)
        except BaseException:
            await page.close()
            raise

    def site[S: "Site"](self, site_cls: type[S]) -> S:
        """Bind a site module to this browser: `books = k.site(Books)`.

        Args:
            site_cls: The `Site` subclass to instantiate.

        Returns:
            An instance of `site_cls` that opens its pages through this client.
        """
        return site_cls(self)
