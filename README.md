# khoji

Stealth Playwright scraping with Pydantic-typed extraction.

- **One entry point**: `Khoji` owns the browser and hands out pages.
- **Typed extraction**: declare selectors on a Pydantic model and get validated objects back.
- **Bot-detection bypass**: built on [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python), a patched Playwright that removes the automation leaks detectors look for.

## Install

```sh
uv sync
uv run patchright install chromium
```

Requires Python 3.13+.

## Quickstart

```python
import asyncio
from typing import Annotated

from pydantic import BaseModel

from khoji import Khoji, Selector


class Book(BaseModel):
    title: Annotated[str, Selector("h3 a", attr="title")]
    price: Annotated[float, Selector(".price_color", pattern=r"\d[\d.]*")]
    in_stock: Annotated[str, Selector(".availability")]


async def main() -> None:
    async with Khoji() as k:
        page = await k.open("https://books.toscrape.com/")
        books = await page.extract_all(Book, root="article.product_pod")
    print(books[0])


asyncio.run(main())
```

## Extraction

`Selector(css, *, attr=None, pattern=None, all=None)` goes in the field's `Annotated` metadata.

| Field | Result |
|---|---|
| `Annotated[str, Selector("h1")]` | Text of the first match |
| `Annotated[str, Selector("a", attr="href")]` | An attribute instead of text |
| `Annotated[float, Selector(".price", pattern=r"\d[\d.]*")]` | Regex applied first; group 1 if the pattern has one, else the whole match |
| `Annotated[list[str], Selector(".tag")]` | Every match |
| `Annotated[Seller, Selector(".seller")]` | Nested model, selectors scoped to the match |
| `Annotated[list[Card], Selector(".card")]` | One nested model per match |

- `page.extract(Model)` builds one model from the page; `root="..."` scopes it to an element.
- `page.extract_all(Model, root="...")` builds one model per element matching `root`.
- When nothing matches, the field's default applies. A required field with no match raises `ExtractionError`.
- Pydantic does the type coercion, so `"51.77"` becomes a `float` and bad data fails loudly.
- Fields without a `Selector` are left alone and need a default.
- `page.raw` is the underlying Patchright `Page` for clicks, waits and anything else.

## Site modules

Wrap a site's URLs and models in a `Site` subclass:

```python
from khoji import Khoji, Site


class Books(Site):
    base_url = "https://books.toscrape.com"

    async def front_page(self) -> list[Book]:
        page = await self.open("/")
        return await page.extract_all(Book, root="article.product_pod")


async with Khoji() as k:
    books = await k.site(Books).front_page()
```

See `examples/` for runnable versions.

## Configuration

```python
from khoji import Khoji, KhojiConfig, ProxyConfig

config = KhojiConfig(
    headless=False,  # default; headless is easy to detect
    channel="chrome",  # default: Chrome if installed, else bundled Chromium
    user_data_dir="~/profiles/shop",  # persistent profile, keeps cookies between runs
    proxy=ProxyConfig(server="http://host:8080", username="u", password="p"),
    locale="en-US",
    timezone_id="Asia/Kathmandu",
    navigation_timeout_ms=30_000,
    block_detection=True,
    challenge_wait_ms=10_000,
)
```

Things worth knowing:

- **Use real Chrome when you can.** Khoji picks Google Chrome automatically if it is installed and falls back to Patchright's bundled Chromium otherwise. Chrome has the more common fingerprint and does better against strict detectors. On Arch, install `google-chrome` from the AUR; `patchright install chrome` only supports Debian and Ubuntu.
- **User agent, headers and viewport are not configurable on purpose.** Overriding them makes the fingerprint inconsistent, which is what gets a browser flagged.
- **One profile, one process.** Two `Khoji` instances cannot share a `user_data_dir` at the same time; give concurrent runs their own.
- **Match the proxy.** If you use a proxy, set `locale` and `timezone_id` to its region.

## Errors

All inherit from `KhojiError`.

| Error | When |
|---|---|
| `NavigationError` | The page could not be loaded: DNS failure, timeout, refused connection |
| `BlockedError` | HTTP 403/429, or an anti-bot challenge (Cloudflare, DataDome, PerimeterX) that did not clear within `challenge_wait_ms` |
| `ExtractionError` | The page did not satisfy the model |

Patchright passes non-interactive challenges by itself; khoji waits for them to clear. It does not solve interactive CAPTCHAs.

## Development

```sh
uv run pytest
uv run ruff check && uv run ruff format --check
```

Tests launch a headless browser against a local HTTP server; no network needed.

## Responsible use

Scrape only what you are allowed to. Check the site's terms and `robots.txt`, keep request rates low, and do not collect personal data without a lawful basis.
