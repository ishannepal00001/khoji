# 1. Installation

> **Level:** beginner · **Time:** 5 minutes · **Next:** [Your first scrape](02-first-scrape.md)

## Requirements

| Requirement | Version | Why |
|---|---|---|
| Python | 3.13 or newer | khoji uses modern generic syntax (`def f[T](...)`) |
| [uv](https://docs.astral.sh/uv/) | any recent | Recommended package manager; `pip` also works |
| A Chromium browser | — | Google Chrome if installed, otherwise Patchright's bundled Chromium |

## Install the library

From a checkout of the repository:

```sh
uv sync
```

This creates a virtual environment and installs khoji with its two dependencies:

- **[Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python)** — a patched
  Playwright that removes the automation leaks bot detectors look for.
- **[Pydantic](https://docs.pydantic.dev/)** — validates and converts the data you extract.

To use khoji from another project, add it as a path or git dependency:

```sh
uv add /path/to/khoji
```

## Install a browser

khoji needs a Chromium-based browser. You have two options.

### Option A: Google Chrome (recommended)

If Google Chrome is installed in its standard location, khoji uses it automatically. Real Chrome
has the most common fingerprint on the web, so it does best against strict bot detection.

| OS | Where khoji looks |
|---|---|
| Linux | `/opt/google/chrome/chrome` |
| macOS | `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` |
| Windows | `Google\Chrome\Application\chrome.exe` under Program Files or Local AppData |

On Arch Linux, install `google-chrome` from the AUR. `patchright install chrome` only supports
Debian and Ubuntu.

### Option B: bundled Chromium

```sh
uv run patchright install chromium
```

khoji falls back to this when Chrome is not found. It works for most sites, but its fingerprint
is rarer.

## Check that it works

Save this as `check.py`:

```python
import asyncio

from khoji import Khoji


async def main() -> None:
    async with Khoji() as k:
        page = await k.open("https://example.com")
        print(await page.raw.title())


asyncio.run(main())
```

Run it:

```sh
uv run python check.py
```

A browser window opens, loads the page, and closes again. The terminal prints:

```text
Example Domain
```

> **Note:** the window is visible on purpose. khoji runs headed by default because headless
> browsers are the easiest thing for a site to detect. See
> [Configuration](../guides/configuration.md#headless) if you need headless.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Executable doesn't exist` | Install a browser (Option A or B above) |
| Error about the profile being in use | Another khoji run is using the same profile. Close it, or give this run its own `user_data_dir` ([details](../guides/configuration.md#profiles)) |
| Window never appears on a server | There is no display. Use `xvfb-run uv run python check.py`, or set `headless=True` |
| `SyntaxError` on import | Python is older than 3.13 |

---

**Next:** [Your first scrape →](02-first-scrape.md)
