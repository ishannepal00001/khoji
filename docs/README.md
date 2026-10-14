# khoji documentation

khoji is a Python library for scraping websites with a real, stealthy browser and turning what
it finds into typed Pydantic objects. You declare *what* you want on a model; khoji drives the
browser, gets past common bot checks, and hands back validated data.

```python
async with Khoji() as k:
    page = await k.open("https://books.toscrape.com/", scroll=True)
    books = await page.extract_all(Book, root="article.product_pod")
    links = await page.links(internal=True)
```

## How these docs are organised

The docs go from first steps to internals. If you are new, read **Getting started** in order.
After that, jump to whatever you need.

### 1. Getting started — *learn the basics, in order*

| | Page | You will learn |
|---|---|---|
| 1 | [Installation](getting-started/01-installation.md) | Installing khoji and a browser, checking it works |
| 2 | [Your first scrape](getting-started/02-first-scrape.md) | Opening a page and extracting typed data, step by step |
| 3 | [Core concepts](getting-started/03-core-concepts.md) | `Khoji`, `KhojiPage`, `Site`, `Selector` and how they fit together |

### 2. Guides — *how to do one thing well*

| Page | Covers |
|---|---|
| [Extracting data](guides/extraction.md) | Every `Selector` option, nested models, lists, regex, defaults |
| [Scrolling and lazy content](guides/scrolling.md) | Infinite feeds, inner scroll panels, limits, `ScrollResult` |
| [Collecting links](guides/links.md) | `page.links()`, filtering, building a small crawler |
| [Site modules](guides/site-modules.md) | Packaging one website's scraping into a reusable class |
| [Configuration](guides/configuration.md) | Every `KhojiConfig` setting, proxies, profiles, browser choice |
| [Errors and debugging](guides/errors-and-debugging.md) | The error hierarchy, handling blocks, saving debug snapshots |
| [Chat sites](guides/chat-sites.md) | Driving WhatsApp Web: chats, messages, sending, auto-replies |

### 3. Advanced — *how it works, and how to extend it*

| Page | Covers |
|---|---|
| [Stealth and anti-bot behaviour](advanced/stealth.md) | What khoji does to look human, and what it deliberately does not |
| [Going below khoji: `page.raw`](advanced/raw-patchright.md) | Clicking, typing, waiting and network control with Patchright |
| [Adding a chat platform](advanced/custom-chat-platform.md) | Writing a `ChatSite` subclass for a new messaging app |
| [Recipes](advanced/recipes.md) | Pagination, crawling, login-once sessions, retries |

### 4. Reference — *exact signatures and behaviour*

| Page | Covers |
|---|---|
| [API reference](reference/api.md) | Every public class, method, field and default |
| [Contributing](reference/contributing.md) | Dev setup, tests, code style, project layout |

## Conventions used in these docs

- All examples are `async`. Run them with `asyncio.run(main())`.
- `k` is a started `Khoji`, `page` is a `KhojiPage`.
- Snippets import only what they use; the first time a name appears, its import is shown.
- Callouts marked **Note** add detail; **Warning** marks something that can lose data, get you
  blocked, or send a message you did not mean to send.

## Responsible use

Scrape only what you are allowed to. Read the site's terms and `robots.txt`, keep request rates
low, and do not collect personal data without a lawful basis. khoji makes a browser look human;
it does not make scraping permitted.
