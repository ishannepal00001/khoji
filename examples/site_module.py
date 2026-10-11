"""A site module: one class that knows a site's URLs and returns typed data.

uv run python examples/site_module.py
"""

import asyncio
from typing import Annotated

from pydantic import BaseModel

from khoji import Khoji, Selector, Site


class Book(BaseModel):
    title: Annotated[str, Selector("h3 a", attr="title")]
    price: Annotated[float, Selector(".price_color", pattern=r"\d[\d.]*")]


class BookDetail(BaseModel):
    title: Annotated[str, Selector("h1")]
    price: Annotated[float, Selector(".price_color", pattern=r"\d[\d.]*")]
    upc: Annotated[str, Selector("table tr:first-child td")]
    description: Annotated[str | None, Selector("#product_description + p")] = None


class Books(Site):
    base_url = "https://books.toscrape.com"

    async def category(self, slug: str) -> list[Book]:
        page = await self.open(f"/catalogue/category/books/{slug}/index.html")
        try:
            return await page.extract_all(Book, root="article.product_pod")
        finally:
            await page.close()

    async def detail(self, slug: str) -> BookDetail:
        page = await self.open(f"/catalogue/{slug}/index.html")
        try:
            return await page.extract(BookDetail)
        finally:
            await page.close()


async def main() -> None:
    async with Khoji() as k:
        books = k.site(Books)
        travel = await books.category("travel_2")
        detail = await books.detail("a-light-in-the-attic_1000")

    print(f"{len(travel)} travel books, first: {travel[0].title}")
    print(f"{detail.title} ({detail.upc}): {detail.price}")


if __name__ == "__main__":
    asyncio.run(main())
