# 3. Core concepts

> **Level:** beginner · **Time:** 10 minutes · **Previous:** [Your first scrape](02-first-scrape.md) ·
> **Next:** pick a [guide](../README.md#2-guides--how-to-do-one-thing-well)

khoji has a small number of objects. Once you know what each one owns, the rest of the library
follows.

```text
Khoji ─────────────── owns the browser (one per program)
 │
 ├─ open(url) ──────► KhojiPage ── one tab: navigate, scroll, links, extract
 │                        │
 │                        └─ raw ──► Patchright Page (everything else)
 │
 └─ site(Cls) ──────► Site ──────── one website's URLs and scraping methods
                         └─ ChatSite ── a chat web app (login, chats, send, reply)

Pydantic model + Selector ─── what to extract, used by KhojiPage.extract*
```

## `Khoji`: the browser

`Khoji` is the entry point. It launches **one** browser and hands out tabs.

```python
from khoji import Khoji, KhojiConfig

async with Khoji(KhojiConfig(locale="en-US")) as k:
    ...
```

- `async with` starts the browser on entry and closes it on exit, also when an exception is
  raised. You can call `await k.start()` and `await k.close()` yourself instead.
- The browser uses a **persistent profile** (a folder on disk). Cookies and logins survive between
  runs, which is how you log in to a site once and stay logged in.
- Create one `Khoji` per program and open as many pages from it as you need.

## `KhojiPage`: one tab

`k.open(url)` returns a `KhojiPage`: a loaded tab that has been checked for blocks.

| Method | Does |
|---|---|
| `goto(url)` | Navigate this tab somewhere else |
| `scroll_to_end()` | Scroll down while the page can, loading lazy and infinite content |
| `links()` | Every link on the page, as typed `Link` objects |
| `extract(Model)` | Build one model from the page |
| `extract_all(Model, root=...)` | Build one model per matching element |
| `html()` | The rendered HTML |
| `save_debug(dir, label)` | Screenshot + HTML, for figuring out what went wrong |
| `close()` | Close the tab |
| `raw` | The underlying Patchright `Page` for anything else |

khoji covers the common path. For clicking, typing, waiting for elements or intercepting
requests, use `page.raw` — see [Going below khoji](../advanced/raw-patchright.md).

## Models and `Selector`: what to extract

You describe data as an ordinary Pydantic model. A field with `Selector` metadata is read from the
page; a field without one is left at its default.

```python
class Product(BaseModel):
    name: Annotated[str, Selector("h1")]
    price: Annotated[float, Selector(".price", pattern=r"\d[\d.]*")]
    tags: Annotated[list[str], Selector(".tag")]
    source: str = "shop"  # no Selector: not scraped
```

Pydantic then converts and validates. If the page does not fit the model, you get an
`ExtractionError` instead of bad data. Full details: [Extracting data](../guides/extraction.md).

## `Site`: one website as a class

When you scrape the same site repeatedly, put its URLs and models in a `Site` subclass. Your code
then calls methods like `shop.product("abc")` instead of building URLs and selectors inline.

```python
class Books(Site):
    base_url = "https://books.toscrape.com"

    async def front_page(self) -> list[Book]:
        page = await self.open("/")
        return await page.extract_all(Book, root="article.product_pod")


books = await k.site(Books).front_page()
```

See [Site modules](../guides/site-modules.md). `ChatSite` builds on `Site` for messaging apps; see
[Chat sites](../guides/chat-sites.md).

## Errors

Everything khoji raises is a `KhojiError`, so one `except KhojiError` catches all of it. The
specific subclasses tell you what happened:

```text
KhojiError
├── NavigationError     page could not load
├── BlockedError        403/429 or an anti-bot challenge that did not clear
├── ExtractionError     the page did not fit the model
└── ChatError           a chat site could not do what was asked
    ├── LoggedOutError
    └── SendUnconfirmedError
```

See [Errors and debugging](../guides/errors-and-debugging.md).

## The life of `k.open(url, scroll=True)`

Putting it together, this is what one call does:

1. Reuse the browser's blank starting tab, or open a new one.
2. Navigate to `url` and wait for `domcontentloaded` (configurable with `wait_until=`).
3. If block detection is on: look for anti-bot challenge pages, wait up to `challenge_wait_ms` for
   them to clear, then raise `BlockedError` if they did not, or if the status was 403/429.
4. If `scroll=True`: scroll to the end of the page.
5. Return the `KhojiPage`. If anything failed, the tab is closed before the error propagates, so
   failed opens never leak tabs.

---

**Next:** you know enough to use any [guide](../README.md#2-guides--how-to-do-one-thing-well).
[Extracting data](../guides/extraction.md) is a good one to read first.
