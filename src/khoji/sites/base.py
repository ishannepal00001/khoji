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
    """

    base_url: ClassVar[str]

    def __init__(self, khoji: "Khoji") -> None:
        self.khoji = khoji

    def url(self, path: str = "/") -> str:
        return urljoin(self.base_url, path)

    async def open(self, path: str = "/", *, wait_until: WaitUntil = "domcontentloaded") -> KhojiPage:
        return await self.khoji.open(self.url(path), wait_until=wait_until)
