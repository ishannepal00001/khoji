# Scrolling and lazy content

> **Level:** intermediate · **Prerequisites:** [Core concepts](../getting-started/03-core-concepts.md)

Many sites only render what is on screen. Feeds append more items as you near the bottom, images
load as they come into view, and "infinite" lists never show a last page. `scroll_to_end()`
scrolls the page the way a person would until there is nothing more to load.

- [Quick start](#quick-start)
- [How it decides when to stop](#how-it-decides-when-to-stop)
- [What gets scrolled](#what-gets-scrolled)
- [Tuning](#tuning)
- [Reading the result](#reading-the-result)
- [Recipes](#recipes)
- [Limitations](#limitations)

## Quick start

Scroll as part of opening the page:

```python
page = await k.open("https://example.com/feed", scroll=True)
items = await page.extract_all(Item, root=".item")
```

Or scroll a page that is already open, with your own limits:

```python
result = await page.scroll_to_end(max_rounds=200, timeout_ms=120_000)
print(f"{result.rounds} steps, reached the end: {result.reached_end}")
```

`Site.open()` takes the same flag: `await self.open("/feed", scroll=True)`.

Scrolling is **opt-in**. Plain `k.open(url)` never scrolls, so it stays fast and never wanders into
an endless feed by accident.

## How it decides when to stop

```text
          ┌──────────────────────────────┐
          │ find what to scroll          │── nothing scrollable ──► done (rounds=0)
          └──────────────┬───────────────┘
                         ▼
          ┌──────────────────────────────┐
     ┌───►│ more content below the view? │── no ──┐
     │    └──────────────┬───────────────┘        │
     │                   │ yes                    ▼
     │                   ▼               ┌────────────────────┐
     │     limit hit? ── yes ──► stop    │ waited settle_checks│── yes ─► done
     │                   │ no            │ pauses already?     │         (reached_end)
     │                   ▼               └─────────┬──────────┘
     │      one wheel step (~80% of a screen)      │ no: wait
     │                   │                         │
     └──── random pause ◄┴─────────────────────────┘
```

1. **Can it go down?** It checks `scrollTop + visible height < scrollHeight`. A page that fits on
   one screen returns immediately with `rounds=0`.
2. **Step.** It moves the mouse over the scrolling area and turns the wheel by about 80% of the
   visible height, with ±15% jitter. Consecutive views overlap, so nothing is skipped.
3. **Pause.** A random pause from `pause_ms` lets scroll listeners fire and requests come back.
4. **At the bottom, wait.** A feed may still be loading the next batch. It only declares the end
   after `settle_checks` pauses in a row with no new content. If more content appears, it keeps
   scrolling.
5. **Limits.** `max_rounds` and `timeout_ms` stop endless feeds. Hitting one returns
   `reached_end=False`.

### Why the mouse wheel?

Real wheel events are what a person produces. They trigger `scroll` and `wheel` listeners and
`IntersectionObserver`s exactly as a visit would, and they look human to bot detection. If the
wheel does not move the page — because an overlay or fixed header sits under the pointer — khoji
switches to scrolling the element directly for the rest of the run.

## What gets scrolled

With no `container`, khoji picks the target in this order:

1. **The document**, if it can scroll (and neither `<html>` nor `<body>` has `overflow-y: hidden`).
2. Otherwise **the largest scrollable element** on the page: one with `overflow-y` of `auto`,
   `scroll` or `overlay` and more content than fits. This covers web apps whose page is fixed and
   whose feed lives in a panel.

When the page has several scrolling panels (a chat list and a thread, say), choose one:

```python
await page.scroll_to_end(container="#results")
```

A `container` that matches nothing raises `KhojiError`.

## Tuning

```python
await page.scroll_to_end(
    container=None,  # CSS selector of the element to scroll; None = auto-detect
    max_rounds=50,  # at most this many steps
    timeout_ms=30_000,  # at most this long
    pause_ms=(500, 1200),  # random pause after each step, in ms
    settle_checks=2,  # pauses at the bottom with no new content before stopping
)
```

| Situation | Change |
|---|---|
| Long feed that stops early with `reached_end=False` | Raise `max_rounds` and `timeout_ms` |
| Slow site: the feed loads more *after* khoji gives up | Raise `pause_ms` or `settle_checks` |
| Fast local or internal site | Lower `pause_ms`, e.g. `(150, 300)` |
| You want "the first N screens" only | Set `max_rounds=N` and ignore `reached_end` |

> **Warning:** short pauses scroll faster than a person can read. On sites with bot detection,
> keep the defaults or slower.

Rough timing: a step every ~0.85 s on average with the defaults, so 50 rounds is about 45 seconds
of scrolling, or ~35 screens of content.

## Reading the result

`scroll_to_end()` returns a `ScrollResult`:

| Field | Meaning |
|---|---|
| `rounds` | Steps taken. `0` means there was nothing to scroll |
| `height` | Final scroll height in pixels of the element that was scrolled |
| `reached_end` | `True`: bottom reached and nothing more loaded. `False`: `max_rounds` or `timeout_ms` stopped it |

`reached_end=False` is not an error: you still have everything loaded so far. Decide whether that
is enough for your use.

## Recipes

**Scroll, then extract and collect links:**

```python
page = await k.open("https://example.com/feed", scroll=True)
posts = await page.extract_all(Post, root="article")
links = await page.links(root="main", internal=True)
```

**Collect until you have enough** — scroll in short bursts and check between them:

```python
items: list[Item] = []
while len(items) < 100:
    result = await page.scroll_to_end(max_rounds=5)
    items = await page.extract_all(Item, root=".item")
    if result.reached_end:
        break
```

**Lazy images** — scroll so they load, then read the real `src`:

```python
await page.scroll_to_end()
images = await page.extract_all(Image, root="img.lazy")
```

## Limitations

- **Virtualised lists** (common in large web apps) remove items that scroll out of view. After
  scrolling to the end, only the last screens are in the DOM. Extract in bursts as shown in
  *Collect until you have enough*, de-duplicating as you go.
- **"Load more" buttons** need a click, not a scroll. Use `page.raw` to click them in a loop; see
  [Recipes](../advanced/recipes.md#load-more-buttons).
- Scrolling only goes **down**. History that loads when scrolling up (chat threads) is not handled.

---

**Related:** [Collecting links](links.md) · [Extracting data](extraction.md) · [API reference](../reference/api.md#scroll_to_end)
