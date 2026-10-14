# Site modules

> **Level:** intermediate · **Prerequisites:** [Extracting data](extraction.md)

A *site module* is a class that holds everything about scraping one website: its base URL, its
models, and methods that return typed results. Callers ask for `shop.product("abc")`; they never
see URLs or selectors.

- [Why use one](#why-use-one)
- [Writing a site module](#writing-a-site-module)
- [Using it](#using-it)
- [Patterns](#patterns)
- [Testing a site module](#testing-a-site-module)

## Why use one

| Without | With |
|---|---|
| URLs and selectors spread through your code | One class per site, everything in one place |
| A markup change means hunting for selectors | A markup change means editing one model |
| Callers deal with pages and tabs | Callers call `books.front_page()` and get `list[Book]` |

## Writing a site module

Subclass `Site`, set `base_url`, and add methods:

```python
from typing import Annotated

from pydantic import BaseModel

from khoji import Selector, Site


class Book(BaseModel):
    title: Annotated[str, Selector("h3 a", attr="title")]
    price: Annotated[float, Selector(".price_color", pattern=r"\d[\d.]*")]
    url: Annotated[str, Selector("h3 a", attr="href")]


class Books(Site):
    base_url = "https://books.toscrape.com"

    async def page_of_books(self, number: int = 1) -> list[Book]:
        page = await self.open(f"/catalogue/page-{number}.html")
        try:
            return await page.extract_all(Book, root="article.product_pod")
        finally:
            await page.close()
```

What `Site` gives you:

| Member | Does |
|---|---|
| `base_url` | Class attribute you set. Every subclass must have one |
| `self.url(path)` | Resolves `path` against `base_url`. Absolute URLs pass through unchanged |
| `self.open(path, *, wait_until=..., scroll=False)` | Opens `url(path)` in a new tab, with block detection; returns a `KhojiPage` |
| `self.khoji` | The `Khoji` client, for anything else (e.g. `self.khoji.new_page()`) |

> **Note:** `self.url()` uses `urllib.parse.urljoin`. A path starting with `/` replaces the
> whole path of `base_url`; a path without one is relative to it.

## Using it

```python
from khoji import Khoji

async with Khoji() as k:
    books = k.site(Books)
    first = await books.page_of_books(1)
    second = await books.page_of_books(2)
```

`k.site(Cls, **kwargs)` creates the site bound to this browser. Extra keyword arguments go to the
site's constructor, so a site can take its own settings:

```python
class Shop(Site):
    base_url = "https://shop.example"

    def __init__(self, khoji, *, currency: str = "USD") -> None:
        super().__init__(khoji)
        self.currency = currency


shop = k.site(Shop, currency="NPR")
```

## Patterns

**Close what you open.** Each `self.open()` is a new tab. Close it in `finally` once you have the
data, as above, unless the caller needs the page.

**Keep models next to the site.** Put `Book` and `Books` in the same module, e.g.
`mysites/books.py`. The model is the site's contract.

**Return models, not pages.** Methods that return `list[Book]` are easy to test and reuse; methods
that return `KhojiPage` leak browser details to the caller.

**Paginate inside the site:**

```python
class Books(Site):
    ...

    async def all_books(self, max_pages: int = 50) -> list[Book]:
        books: list[Book] = []
        for number in range(1, max_pages + 1):
            batch = await self.page_of_books(number)
            if not batch:
                break
            books.extend(batch)
        return books
```

**Infinite feeds:** pass `scroll=True`:

```python
async def feed(self) -> list[Post]:
    page = await self.open("/feed", scroll=True)
    ...
```

**Absolute links:** combine a model with `page.links()`, or resolve with `self.url(book.url)`
(careful: relative links resolve against the page they came from, not always `base_url`).

## Testing a site module

khoji's own tests serve fixture HTML from a local HTTP server and point a `Site` at it. Do the same
for your sites so tests run offline and stay fast:

```python
# conftest.py: serve saved pages from a local server
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from functools import partial

import pytest

from khoji import Khoji, KhojiConfig


@pytest.fixture(scope="session")
def server():
    handler = partial(SimpleHTTPRequestHandler, directory="tests/pages")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


@pytest.fixture
async def khoji(tmp_path):
    async with Khoji(KhojiConfig(headless=True, user_data_dir=tmp_path / "profile")) as k:
        yield k
```

```python
# test_books.py
async def test_page_of_books(khoji, server):
    class LocalBooks(Books):
        base_url = server

    books = await khoji.site(LocalBooks).page_of_books(1)
    assert books[0].title == "A Light in the Attic"
```

Save real pages into `tests/pages/` with `page.save_debug()` or your browser's *Save page as*.

---

**Related:** [Chat sites](chat-sites.md) (a `Site` subclass for messaging apps) ·
[API reference](../reference/api.md#site)
