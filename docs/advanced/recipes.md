# Recipes

> **Level:** intermediate → advanced

Short, complete solutions to common jobs. Each one combines pieces from the guides.

- [Follow "next" links](#follow-next-links)
- [Numbered pages](#numbered-pages)
- [Load more buttons](#load-more-buttons)
- [Infinite feed into models](#infinite-feed-into-models)
- [Crawl a site](#crawl-a-site)
- [List page, then detail pages](#list-page-then-detail-pages)
- [Log in once, scrape many times](#log-in-once-scrape-many-times)
- [Save results to JSON Lines](#save-results-to-json-lines)
- [Several tabs at once](#several-tabs-at-once)

## Follow "next" links

```python
from typing import Annotated
from urllib.parse import urljoin

from pydantic import BaseModel

from khoji import Khoji, Selector


class ListingPage(BaseModel):
    books: Annotated[list[Book], Selector("article.product_pod")]
    next: Annotated[str | None, Selector("li.next a", attr="href")] = None


async def all_books(start: str) -> list[Book]:
    books, url = [], start
    async with Khoji() as k:
        page = await k.open(url)
        while True:
            listing = await page.extract(ListingPage)
            books.extend(listing.books)
            if listing.next is None:
                return books
            await page.goto(urljoin(page.url, listing.next))  # same tab
```

Reusing one tab with `goto` is lighter than opening a new one per page.

## Numbered pages

When the URL has a page number, generate it and stop at the first empty page:

```python
for number in range(1, 100):
    page = await k.open(f"https://shop.example/c/lamps?page={number}")
    items = await page.extract_all(Item, root=".product")
    await page.close()
    if not items:
        break
    collected.extend(items)
```

## Load more buttons

Click until the button disappears, then extract once:

```python
button = page.raw.get_by_role("button", name="Load more")
for _ in range(50):
    if not await button.is_visible():
        break
    await button.click()
    await page.raw.wait_for_timeout(1200)
items = await page.extract_all(Item, root=".item")
```

## Infinite feed into models

```python
page = await k.open("https://example.com/feed", scroll=True)
posts = await page.extract_all(Post, root="article")
```

For very long feeds that virtualise their list (old items are removed from the DOM), collect while
scrolling and de-duplicate:

```python
seen: dict[str, Post] = {}
while True:
    for post in await page.extract_all(Post, root="article"):
        seen.setdefault(post.url, post)
    result = await page.scroll_to_end(max_rounds=3)
    if result.reached_end:
        for post in await page.extract_all(Post, root="article"):
            seen.setdefault(post.url, post)
        break
posts = list(seen.values())
```

## Crawl a site

Breadth-first, one host, polite, with a page limit and `robots.txt`:

```python
import asyncio
import random
from collections import deque
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from khoji import Khoji, KhojiError


async def crawl(start: str, limit: int = 50) -> dict[str, str]:
    robots = RobotFileParser(urljoin(start, "/robots.txt"))
    robots.read()

    seen, queue, titles = {start}, deque([start]), {}
    async with Khoji() as k:
        page = await k.new_page()
        while queue and len(titles) < limit:
            url = queue.popleft()
            if not robots.can_fetch("*", url):
                continue
            try:
                await page.goto(url)
            except KhojiError as exc:
                print(f"skip {url}: {exc}")
                continue
            titles[url] = await page.raw.title()
            for link in await page.links(internal=True):
                if link.url not in seen and "nofollow" not in link.rel:
                    seen.add(link.url)
                    queue.append(link.url)
            await asyncio.sleep(random.uniform(1.5, 4))
    return titles
```

`k.new_page()` gives a blank tab, and `page.goto()` reuses it for every URL.

## List page, then detail pages

```python
class Summary(BaseModel):
    href: Annotated[str, Selector("h3 a", attr="href")]


class Detail(BaseModel):
    title: Annotated[str, Selector("h1")]
    description: Annotated[str | None, Selector("#product_description + p")] = None
    upc: Annotated[str, Selector("tr:has(th:text-is('UPC')) td")]


async with Khoji() as k:
    listing = await k.open("https://books.toscrape.com/")
    summaries = await listing.extract_all(Summary, root="article.product_pod")
    detail_page = await k.new_page()
    details = []
    for summary in summaries[:5]:
        await detail_page.goto(urljoin(listing.url, summary.href))
        details.append(await detail_page.extract(Detail))
```

> **Note:** `:has()` and `:text-is()` are Playwright selector extensions on top of CSS; they work
> in `Selector` because khoji resolves selectors with Playwright locators.

## Log in once, scrape many times

Because the profile persists, log in by hand once and reuse it:

```python
config = KhojiConfig(user_data_dir="~/profiles/members")

# First run: log in in the window, then press Enter here.
async with Khoji(config) as k:
    await k.open("https://members.example/login")
    input("Log in in the browser window, then press Enter...")

# Every later run is already logged in.
async with Khoji(config) as k:
    page = await k.open("https://members.example/dashboard")
```

## Save results to JSON Lines

```python
from pathlib import Path

with Path("books.jsonl").open("a") as out:
    for book in books:
        out.write(book.model_dump_json() + "\n")
```

Read back with `Book.model_validate_json(line)`.

## Several tabs at once

One `Khoji` can drive several tabs concurrently, and `k.open()` is safe to call from concurrent
tasks: every call gets a tab of its own. Keep the number small; parallel bursts are easy to spot.

```python
import asyncio

from khoji import Khoji


async def fetch(k: Khoji, url: str, limit: asyncio.Semaphore) -> Detail:
    async with limit:
        page = await k.open(url)
        try:
            return await page.extract(Detail)
        finally:
            await page.close()


async with Khoji() as k:
    limit = asyncio.Semaphore(3)  # at most 3 tabs loading at once
    details = await asyncio.gather(*(fetch(k, url, limit) for url in urls))
```

---

**Related:** [Scrolling](../guides/scrolling.md) · [Collecting links](../guides/links.md) ·
[Going below khoji](raw-patchright.md)
