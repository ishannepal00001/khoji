"""Scrape the front page of books.toscrape.com, a sandbox built for scraping practice.

uv run python examples/quickstart.py
"""

import asyncio
from typing import Annotated

from pydantic import BaseModel

from khoji import Khoji, Selector


class Book(BaseModel):
    title: Annotated[str, Selector("h3 a", attr="title")]
    price: Annotated[float, Selector(".price_color", pattern=r"\d[\d.]*")]
    link: Annotated[str, Selector("h3 a", attr="href")]
    in_stock: Annotated[str, Selector(".availability")]


async def main() -> None:
    async with Khoji() as k:
        page = await k.open("https://books.toscrape.com/")
        books = await page.extract_all(Book, root="article.product_pod")

    for book in books[:5]:
        print(f"{book.price:>6.2f}  {book.title}")
    print(f"... {len(books)} books")


if __name__ == "__main__":
    asyncio.run(main())
