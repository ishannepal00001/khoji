# Collecting links

> **Level:** beginner → intermediate · **Prerequisites:** [Core concepts](../getting-started/03-core-concepts.md)

`page.links()` returns every link on the page as a typed `Link`: absolute, de-duplicated, and in
the order they appear.

- [Quick start](#quick-start)
- [The `Link` model](#the-link-model)
- [What is included](#what-is-included)
- [Filtering](#filtering)
- [Building a small crawler](#building-a-small-crawler)

## Quick start

```python
page = await k.open("https://books.toscrape.com/")

for link in await page.links():
    print(link.internal, link.url, link.text)
```

Each line shows whether the link stays on the site, its absolute URL, and its text:

```text
True https://books.toscrape.com/catalogue/category/books_1/index.html Books
True https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html A Light in the ...
...
```

## The `Link` model

```python
from khoji import Link
```

| Field | Type | Example | Notes |
|---|---|---|---|
| `url` | `str` | `https://shop.com/about` | Absolute, `#fragment` removed |
| `text` | `str` | `About us` | Visible text, whitespace collapsed. Falls back to `aria-label`, then `title`, then `""` |
| `title` | `str \| None` | `Our story` | The `title` attribute |
| `rel` | `list[str]` | `["nofollow", "noopener"]` | Tokens of the `rel` attribute |
| `internal` | `bool` | `True` | Same host as the page you are on |

`Link` is a frozen (immutable) Pydantic model. It serialises with `model_dump()` /
`model_dump_json()` and stays valid after the page closes. Use `link.url` as a key when you need
sets or dicts of links.

## What is included

Given this page at `https://shop.com/`:

```html
<a href="/about" rel="nofollow">About us</a>
<a href="/about#team">Team</a>                 <!-- same URL once the fragment is gone -->
<a href="https://example.org/x">Example</a>
<a href="/icon" aria-label="Settings"></a>
<a href="mailto:hi@shop.com">Mail</a>
<a href="javascript:void(0)">Nothing</a>
<a name="anchor">No href</a>
```

`await page.links()` returns:

| url | text | internal |
|---|---|---|
| `https://shop.com/about` | `About us` | `True` |
| `https://example.org/x` | `Example` | `False` |
| `https://shop.com/icon` | `Settings` | `True` |

The rules:

- Only `<a>` elements with an `href` are considered. SVG links are skipped.
- URLs are resolved by the browser, so relative links and `<base href>` are handled.
- `#fragments` are removed and each URL appears **once**, at its first occurrence.
- Only `http` and `https` links are kept by default.
- Links are read from the **live** page, so content added by scripts or by
  [scrolling](scrolling.md) is included.

## Filtering

```python
await page.links(internal=True)  # same host only
await page.links(internal=False)  # other sites only
await page.links(root="main")  # inside the first <main> only
await page.links(schemes=("mailto",))  # e-mail links instead of web links
await page.links(schemes=("http", "https", "mailto"))
```

`internal` compares host names exactly: `www.shop.com` and `shop.com` are different hosts. Filter
yourself for anything looser:

```python
from urllib.parse import urlparse


def same_site(url: str, domain: str) -> bool:
    host = urlparse(url).hostname or ""
    return host == domain or host.endswith("." + domain)


links = [l for l in await page.links() if same_site(l.url, "shop.com")]
```

Other filters are a list comprehension away:

```python
followable = [l for l in links if "nofollow" not in l.rel]
products = [l for l in links if "/product/" in l.url]
```

## Building a small crawler

`links()` plus a queue is a breadth-first crawler. This one stays on one site, visits each page
once, and stops after a fixed number of pages:

```python
import asyncio
from collections import deque

from khoji import Khoji, KhojiError


async def crawl(start: str, limit: int = 20) -> dict[str, str]:
    """Visit up to `limit` pages of one site and return {url: title}."""
    seen, queue, titles = {start}, deque([start]), {}
    async with Khoji() as k:
        while queue and len(titles) < limit:
            url = queue.popleft()
            try:
                page = await k.open(url)
            except KhojiError as exc:
                print(f"skip {url}: {exc}")
                continue
            titles[url] = await page.raw.title()
            for link in await page.links(internal=True):
                if link.url not in seen:
                    seen.add(link.url)
                    queue.append(link.url)
            await page.close()
            await asyncio.sleep(1.5)  # be polite between requests
    return titles
```

Things a real crawler should also do:

- **Close each page** when done, as above, or tabs pile up.
- **Wait between requests.** Hammering a site is rude and gets you blocked.
- **Respect `robots.txt`** (`urllib.robotparser` in the standard library).
- **Normalise URLs** further if the site has variants (`/a` vs `/a/`, tracking query strings).

A longer version with politeness delays is in [Recipes](../advanced/recipes.md#crawl-a-site).

---

**Related:** [Scrolling](scrolling.md) · [Recipes](../advanced/recipes.md) · [API reference](../reference/api.md#links)
