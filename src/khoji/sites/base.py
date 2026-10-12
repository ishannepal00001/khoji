"""`Site`: the base class for a scraper dedicated to one website."""

from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urljoin

from ..page import KhojiPage, WaitUntil

if TYPE_CHECKING:
    from ..client import Khoji


class Site:
    """Base class for a scraper dedicated to one site.

    Subclass it, set `base_url`, and add methods that return your own models:

        class Books(Site):
            base_url = "https://books.toscrape.com"

            async def front_page(self) -> list[Book]:
                page = await self.open("/")
                return await page.extract_all(Book, root="article.product_pod")

    Attributes:
        base_url: The site's root URL. Every subclass must set it.
        khoji: The client this site opens its pages through.
    """

    base_url: ClassVar[str]

    def __init__(self, khoji: "Khoji") -> None:
        """Bind the site to a browser.

        Args:
            khoji: A `Khoji` client. It must be started before any page is opened.
        """
        self.khoji = khoji

    def url(self, path: str = "/") -> str:
        """Resolve a path against `base_url`.

        Args:
            path: A path such as "/catalogue/page-2.html". An absolute URL is returned as is.

        Returns:
            The absolute URL.
        """
        return urljoin(self.base_url, path)

    async def open(self, path: str = "/", *, wait_until: WaitUntil = "domcontentloaded") -> KhojiPage:
        """Open a page of this site in a new tab.

        Args:
            path: Path relative to `base_url`.
            wait_until: Load state to wait for before returning.

        Returns:
            The loaded page. The caller is responsible for closing it.

        Raises:
            NavigationError: If the page could not be loaded.
            BlockedError: If the site answered with a block or a challenge that did not clear.
        """
        return await self.khoji.open(self.url(path), wait_until=wait_until)
