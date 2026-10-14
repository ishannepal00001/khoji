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
- `Selector` is optional. A field without one is not scraped: it keeps its default, or is `None` if it has none.
- `page.raw` is the underlying Patchright `Page` for clicks, waits and anything else.

## Scrolling and links

```python
page = await k.open("https://example.com/feed", scroll=True)  # scroll to the end first

result = await page.scroll_to_end(max_rounds=100)  # or scroll an already open page
print(result.rounds, result.reached_end)

for link in await page.links(internal=True):
    print(link.url, link.text)
```

- `scroll_to_end()` scrolls with the mouse wheel while the page can still go down, waiting at the bottom for infinite feeds to load more. A page that cannot scroll returns at once.
- It scrolls the document, or the largest scrollable element when the feed lives in an inner panel; pass `container="..."` to choose. `max_rounds` and `timeout_ms` bound it, and `ScrollResult.reached_end` says whether it got to the end.
- `links()` returns one `Link(url, text, title, rel, internal)` per distinct absolute URL, in document order, read from the live page so scrolled-in content is included. Fragments are removed, and only http(s) links are kept unless `schemes=` says otherwise. `root=` scopes it to an element; `internal=True/False` keeps only same-host or only external links.

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

## Chat sites

A chat web app is a `Site` that can also log in, list chats, open one, send and wait for replies.
`khoji.chat` holds that behaviour once; a platform in `khoji.sites` only says where things are on the page.

```
Site (sites/base.py)            base_url, open a page
  └─ ChatSite (chat/site.py)    login wait, chat list, thread, send, wait for reply
       └─ WhatsApp (sites/whatsapp.py)   selectors and in-page JS
```

```python
from khoji import Khoji
from khoji.chat import Chat, Conversation, Message, Responder
from khoji.sites import WhatsApp


class Echo(Responder):
    async def reply(self, chat: Chat, messages: list[Message]) -> list[str]:
        last = [m for m in messages if m.direction == "in"][-1]
        return [f"You said: {last.text}"]


async with Khoji() as k, k.site(WhatsApp) as wa:  # first run: scan the QR code in the window
    chat = await wa.find_chat("Alice")
    await wa.open_thread(chat)
    result = await Conversation(wa, chat, responder=Echo(), max_replies=3).run("Hello")
```

- `chats()`, `find_chat(name)`, `open_thread(chat)`, `messages()`, `send(text)` and `wait_for_reply(...)` can be used directly; `Conversation` is the send, wait, reply loop built on them.
- Without a responder, `run()` returns as soon as the other side answers. `run(resume=True)` picks a conversation back up and treats whatever they sent after your last message as unanswered.
- Login is never automated. The persistent profile keeps the session after the first login.
- `send()` types like a person and confirms the message appeared. If it cannot confirm, it raises `SendUnconfirmedError` and never retries by itself.
- Timings (typing speed, polling gaps, how long to wait) are in `ChatSettings`: `k.site(WhatsApp, settings=ChatSettings(wait_hours=1))`.
- `site.save_debug("label")` saves a screenshot and the page HTML under `debug/<site>/`. Those files contain your chats; `debug/` is git-ignored.

### Adding a platform

Subclass `ChatSite` in `khoji/sites/`, set `name` and `base_url`, and implement the hooks:

| Hook | Returns |
|---|---|
| `_session_state()` | `SessionState`: chat list showing, login prompt showing, or still loading |
| `_chat_rows()` | The chat list rows, top to bottom, from one read |
| `_read_chat(row, position)` | A `Chat` built from one row |
| `_composer()` | Locator of the message input |
| `_thread_is_open()` | Whether a conversation is open |
| `_read_messages()` | The open thread's `Message`s, oldest first |
| `_thread_text()` (optional) | Visible text of the message area, a fallback for confirming a send |
| `inspect()` (optional) | A structure-only dump of the thread markup, for fixing selectors |

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
| `ChatError` | A chat site could not do what was asked: no such chat, a list that would not settle, a closed thread |
| `LoggedOutError` | The chat site is not logged in, or logged the session out (a `ChatError`) |
| `SendUnconfirmedError` | A message was submitted but never showed up in the thread (a `ChatError`) |

Patchright passes non-interactive challenges by itself; khoji waits for them to clear. It does not solve interactive CAPTCHAs.

## Development

```sh
uv run pytest
uv run ruff check && uv run ruff format --check
```

Tests launch a headless browser against a local HTTP server; no network needed.

## Responsible use

Scrape only what you are allowed to. Check the site's terms and `robots.txt`, keep request rates low, and do not collect personal data without a lawful basis.
