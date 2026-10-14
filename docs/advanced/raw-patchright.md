# Going below khoji: `page.raw`

> **Level:** advanced · **Prerequisites:** [Core concepts](../getting-started/03-core-concepts.md)

khoji covers opening, scrolling, links and extraction. Everything else — clicking, typing, waiting,
frames, network — is done with the underlying Patchright objects, which have the same API as
[Playwright for Python](https://playwright.dev/python/docs/api/class-page).

| khoji | Patchright object | Use for |
|---|---|---|
| `page.raw` | `Page` | Interacting with one tab |
| `k.context` | `BrowserContext` | Cookies, routes, all tabs, permissions |

Mixing them is normal: interact with `page.raw`, then extract with `page.extract`.

- [Interacting with the page](#interacting-with-the-page)
- [Waiting for content](#waiting-for-content)
- [Frames](#frames)
- [Network](#network)
- [Cookies and storage](#cookies-and-storage)
- [Running JavaScript](#running-javascript)
- [Wrapping a tab you created yourself](#wrapping-a-tab-you-created-yourself)

## Interacting with the page

```python
raw = page.raw

await raw.get_by_role("button", name="Accept cookies").click()
await raw.get_by_placeholder("Search").fill("lamps")
await raw.keyboard.press("Enter")
await raw.wait_for_load_state("domcontentloaded")

results = await page.extract_all(Result, root=".result")
```

> **Note:** `fill()` sets a value instantly. On sites watching behaviour, type like a person
> instead: `await locator.press_sequentially("lamps", delay=120)`.

## Waiting for content

Extraction reads the page **as it is right now**. If content arrives later, wait first:

```python
await page.raw.wait_for_selector(".result")  # an element appears
await page.raw.wait_for_load_state("networkidle")  # requests settle
await page.raw.wait_for_function("document.querySelectorAll('.result').length >= 20")
```

Or open with a later load state: `await k.open(url, wait_until="networkidle")`.

## Frames

Content inside an `<iframe>` is a separate document. `page.extract` cannot see into it. Read it
through a frame:

```python
frame = page.raw.frame_locator("iframe#reviews")
texts = await frame.locator(".review").all_inner_texts()
```

## Network

Block heavy resources to load pages faster:

```python
async def block_media(route):
    if route.request.resource_type in {"image", "media", "font"}:
        await route.abort()
    else:
        await route.continue_()


await k.context.route("**/*", block_media)
```

> **Warning:** a browser that never loads images or fonts is unusual. Avoid this on protected sites.

Read an API response the page makes, instead of scraping its rendered HTML:

```python
async with page.raw.expect_response(lambda r: "/api/search" in r.url) as info:
    await page.raw.get_by_role("button", name="Search").click()
data = await (await info.value).json()
```

## Cookies and storage

```python
cookies = await k.context.cookies("https://shop.example")
await k.context.add_cookies([{"name": "lang", "value": "en", "url": "https://shop.example"}])
```

Because the profile is persistent, cookies survive between runs without saving them yourself.

## Running JavaScript

```python
count = await page.raw.evaluate("document.querySelectorAll('.item').length")
info = await page.raw.locator("#app").evaluate("el => el.dataset.state")
```

Return plain JSON-able values. For anything bigger than a few lines, keep the script in a module
constant, the way `WhatsApp.READ_MESSAGES_JS` does: one call gives a consistent snapshot.

## Wrapping a tab you created yourself

If you open a tab through Patchright, wrap it to get khoji's methods:

```python
from khoji import KhojiPage

raw = await k.context.new_page()
page = KhojiPage(raw, k.config)
await page.goto("https://example.com")  # with block detection
links = await page.links()
```

Popups work the same way:

```python
async with page.raw.expect_popup() as popup_info:
    await page.raw.get_by_text("Open report").click()
report = KhojiPage(await popup_info.value, k.config)
```

---

**Related:** [Recipes](recipes.md) · [Playwright Python API](https://playwright.dev/python/docs/api/class-page)
