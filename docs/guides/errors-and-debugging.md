# Errors and debugging

> **Level:** intermediate · **Prerequisites:** [Core concepts](../getting-started/03-core-concepts.md)

- [The error hierarchy](#the-error-hierarchy)
- [Each error in detail](#each-error-in-detail)
- [Handling errors](#handling-errors)
- [Debug snapshots](#debug-snapshots)
- [Logging](#logging)
- [A debugging checklist](#a-debugging-checklist)

## The error hierarchy

```text
KhojiError                      everything khoji raises
├── NavigationError             the page could not be loaded
├── BlockedError                block or challenge page           .url  .status
├── ExtractionError             page did not fit the model        .url  .model
└── ChatError                   chat site could not do it
    ├── LoggedOutError          not logged in / logged out
    └── SendUnconfirmedError    sent message never appeared
```

All are importable from `khoji`. Errors from Patchright itself (e.g. a click timing out on
`page.raw`) are **not** wrapped; catch `patchright.async_api.Error` for those.

## Each error in detail

### `NavigationError`

The page did not load: DNS failure, refused connection, TLS error, or a navigation longer than
`navigation_timeout_ms`. The original Patchright error is the `__cause__`.

**Usually:** retry later, check the URL, or raise the timeout for slow sites.

### `BlockedError`

The site refused you. Raised by `open()`/`goto()` when block detection is on and either:

- an anti-bot challenge did not clear within `challenge_wait_ms`, or
- the response was 403 or 429 with no challenge involved.

| Attribute | Meaning |
|---|---|
| `url` | The URL that was requested |
| `status` | HTTP status, or `None` if there was no response |

**Usually:** slow down, use real Chrome and a headed window, use a residential proxy that matches
your locale and timezone, or open the page by hand once in the same profile to pass an
interactive challenge. khoji does not solve interactive CAPTCHAs.

### `ExtractionError`

The page did not satisfy your model. The message contains Pydantic's full validation report.

| Attribute | Meaning |
|---|---|
| `url` | The page's URL |
| `model` | The model class that failed |

**Usually:** a selector no longer matches (the site changed), or the content is not there yet
(lazy loading — [scroll](scrolling.md) or wait first).

### `ChatError`, `LoggedOutError`, `SendUnconfirmedError`

Raised by [chat sites](chat-sites.md). The important one is `SendUnconfirmedError`: the message
was submitted but khoji could not see it appear. **It may still have been sent.** khoji never
retries sends by itself; check the chat before sending again.

### Plain `KhojiError`

Raised directly when:

- you use `k.context`, `k.new_page()` or `k.open()` before the browser is started;
- `scroll_to_end(container=...)` matches no element.

## Handling errors

Catch the specific errors you can act on, and let the rest propagate:

```python
from khoji import BlockedError, ExtractionError, Khoji, NavigationError

async with Khoji() as k:
    try:
        page = await k.open(url)
        item = await page.extract(Item)
    except BlockedError as exc:
        print(f"Blocked ({exc.status}) on {exc.url}; backing off")
    except NavigationError:
        print("Could not load; will retry later")
    except ExtractionError as exc:
        print(f"{exc.model.__name__} did not match {exc.url}:\n{exc}")
```

A simple retry with backoff for transient failures:

```python
import asyncio


async def open_with_retry(k, url, attempts=3):
    for attempt in range(1, attempts + 1):
        try:
            return await k.open(url)
        except NavigationError:
            if attempt == attempts:
                raise
            await asyncio.sleep(2**attempt)
```

> **Note:** do not retry `BlockedError` in a tight loop. Repeated hits after a block usually make
> it last longer.

## Debug snapshots

When something goes wrong, the fastest fix is seeing what the browser saw:

```python
from pathlib import Path

try:
    item = await page.extract(Item)
except ExtractionError:
    await page.save_debug(Path("debug"), "item")
    raise
```

This writes two files with a timestamped name:

```text
debug/20261014-153012-item.png    screenshot
debug/20261014-153012-item.html   rendered HTML
```

`save_debug` never raises: if it cannot save, it logs the problem and returns `None`, so it cannot
hide the original error. Open the HTML in a browser and test your selectors in DevTools with
`document.querySelectorAll(...)`.

> **Warning:** snapshots contain whatever was on screen — including personal data if you were
> logged in. Keep `debug/` out of version control.

## Logging

khoji logs with the standard `logging` module under the `khoji` logger (chat sites use
`khoji.chat`). Turn it on to see scroll limits, chat waits and debug-file paths:

```python
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
```

## A debugging checklist

1. **Watch it.** Run headed (the default) and look at the window.
2. **Snapshot it.** `save_debug()` at the failure point.
3. **Test selectors** in the saved HTML with DevTools.
4. **Lazy content?** Try `scroll=True` or `page.raw.wait_for_selector(...)` before extracting.
5. **Wrong frame?** Content inside an `<iframe>` is not in the page's DOM; use
   `page.raw.frame_locator(...)`.
6. **Blocked?** Check `exc.status` and the screenshot; see [Stealth](../advanced/stealth.md).

---

**Related:** [Configuration](configuration.md#block-detection) · [API reference](../reference/api.md#errors)
