# Configuration

> **Level:** intermediate · **Prerequisites:** [Core concepts](../getting-started/03-core-concepts.md)

All browser settings live in one immutable, validated object: `KhojiConfig`. Pass it to `Khoji`.

```python
from khoji import Khoji, KhojiConfig, ProxyConfig

config = KhojiConfig(
    headless=False,
    channel="chrome",
    user_data_dir="~/profiles/shop",
    proxy=ProxyConfig(server="http://host:8080", username="u", password="p"),
    locale="en-US",
    timezone_id="Asia/Kathmandu",
    navigation_timeout_ms=30_000,
    block_detection=True,
    challenge_wait_ms=10_000,
)

async with Khoji(config) as k:
    ...
```

- [All settings](#all-settings)
- [Choosing the browser](#choosing-the-browser)
- [Profiles](#profiles)
- [Headless](#headless)
- [Proxies, locale and timezone](#proxies-locale-and-timezone)
- [Block detection](#block-detection)
- [What you cannot configure, and why](#what-you-cannot-configure-and-why)

## All settings

| Setting | Type | Default | Meaning |
|---|---|---|---|
| `headless` | `bool` | `False` | Run without a window. Easy for sites to detect |
| `channel` | `str \| None` | `None` | Browser channel, e.g. `"chrome"`, `"msedge"`. `None` = Chrome if installed, else bundled Chromium |
| `executable_path` | `Path \| None` | `None` | Exact browser binary. Overrides `channel` |
| `user_data_dir` | `Path` | `$XDG_DATA_HOME/khoji/profile` | Persistent profile folder. `~` is expanded |
| `proxy` | `ProxyConfig \| None` | `None` | Route traffic through a proxy |
| `locale` | `str \| None` | system | Browser locale, e.g. `"en-US"` |
| `timezone_id` | `str \| None` | system | IANA timezone, e.g. `"Asia/Kathmandu"` |
| `navigation_timeout_ms` | `int > 0` | `30_000` | How long a navigation may take before `NavigationError` |
| `block_detection` | `bool` | `True` | Raise `BlockedError` on block and challenge pages |
| `challenge_wait_ms` | `int ≥ 0` | `10_000` | How long to let a challenge clear by itself |

`KhojiConfig` is **frozen** and **strict**: misspelled settings are rejected, and you cannot change
a setting after creation. Make a variant with `model_copy`:

```python
fast = config.model_copy(update={"block_detection": False})
```

## Choosing the browser

khoji picks the binary in this order:

1. `executable_path`, if set.
2. `channel`, if set.
3. Google Chrome, if it is installed in its standard location.
4. Patchright's bundled Chromium.

Prefer real Chrome. It is what most visitors use, so its fingerprint blends in; the bundled
Chromium is rarer and stricter detectors notice.

## Profiles

khoji always uses a **persistent profile**: a folder holding cookies, local storage, cache and
logins. That is how you log in once and stay logged in across runs.

- The default is `~/.local/share/khoji/profile` (or `$XDG_DATA_HOME/khoji/profile`).
- **One profile, one process.** Chrome locks the profile while it runs. Two `Khoji` instances
  cannot share a `user_data_dir` at the same time; give concurrent runs their own.
- Use separate profiles for separate identities (accounts, regions):

```python
work = KhojiConfig(user_data_dir="~/profiles/work")
personal = KhojiConfig(user_data_dir="~/profiles/personal")
```

- To start fresh, delete the folder while khoji is not running.

> **Warning:** a profile contains live session cookies. Treat it like a password: do not commit
> it or share it.

## Headless

```python
KhojiConfig(headless=True)
```

Headless browsers differ from headed ones in many small ways, and anti-bot vendors check for
them. Keep `headless=False` against protected sites. Headless is fine for:

- tests against a local server (khoji's own tests use it),
- sites with no bot protection.

On a server without a display, prefer a virtual display over headless:

```sh
xvfb-run uv run python scraper.py
```

## Proxies, locale and timezone

```python
from khoji import ProxyConfig

proxy = ProxyConfig(
    server="socks5://host:1080",  # or "http://host:8080"
    username="user",  # optional
    password="secret",  # optional; kept out of reprs and logs
)
config = KhojiConfig(proxy=proxy, locale="de-DE", timezone_id="Europe/Berlin")
```

**Match the proxy's region.** A German IP with a Nepali timezone and an English locale is
inconsistent, and inconsistency is what detectors look for. Set `locale` and `timezone_id` to
where the proxy exits.

`password` is a Pydantic `SecretStr`: printing the config shows `**********`.

## Block detection

With `block_detection=True` (the default), every `goto`/`open` checks the result:

| Check | Signs |
|---|---|
| Challenge title | "Just a moment", "Attention required" (Cloudflare), "Access denied" (Akamai), "Pardon our interruption" (Imperva) |
| Challenge element | Cloudflare `#challenge-form` and friends, DataDome captcha iframe, PerimeterX `#px-captcha` |
| Status | HTTP 403 or 429 with no challenge involved |

Many challenges are non-interactive: Patchright passes them and the page replaces itself. khoji
polls every 250 ms for up to `challenge_wait_ms`. A challenge that clears in time is **not** an
error, even though it was served with a 403.

Turn detection off when a site legitimately returns 403 for content you want, or to handle blocks
yourself:

```python
KhojiConfig(block_detection=False)
```

## What you cannot configure, and why

User agent, extra HTTP headers and viewport size are **intentionally not settings**. Overriding
them makes the browser's fingerprint inconsistent: a Windows user agent on a Linux TLS stack, a
viewport that does not match the window. The real browser's own values are always consistent,
so khoji leaves them alone. The viewport follows the window size (`no_viewport`).

If you truly need one of these, reach the context through `k.context` — but expect to be detected
more often. See [Stealth](../advanced/stealth.md).

---

**Related:** [Stealth and anti-bot behaviour](../advanced/stealth.md) ·
[Errors and debugging](errors-and-debugging.md) · [API reference](../reference/api.md#khojiconfig)
