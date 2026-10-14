# Contributing

## Setup

```sh
uv sync
uv run patchright install chromium
```

## Checks

```sh
uv run pytest                                   # all tests
uv run pytest tests/test_page.py -q             # one file
uv run ruff check && uv run ruff format --check # lint and format
```

Tests launch a **headless** browser against a local HTTP server started by `tests/conftest.py`.
No network access is needed, and nothing touches your real profile (each test gets a temporary
`user_data_dir`).

## Project layout

```text
src/khoji/
├── __init__.py        public exports
├── client.py          Khoji: browser lifecycle, open(), site()
├── browser.py         BrowserLauncher: config → persistent context
├── config.py          KhojiConfig, ProxyConfig
├── page.py            KhojiPage: navigation, block detection, scroll, links, extraction
├── extract.py         Selector, Extractor
├── models.py          Link, ScrollResult
├── errors.py          error hierarchy
├── sites/
│   ├── base.py        Site
│   └── whatsapp.py    WhatsApp (selectors + in-page JS only)
└── chat/
    ├── site.py        ChatSite: all platform-independent chat behaviour
    ├── conversation.py
    ├── responder.py
    ├── models.py      Chat, Message, SessionState
    └── settings.py    ChatSettings
tests/
├── conftest.py        local server, fixture pages, headless Khoji fixture
├── test_page.py       scrolling and links
├── test_extract.py    extraction
├── test_block.py      block detection
├── test_chat.py       chat layer against a fake chat app
└── test_config.py
examples/
└── whatsapp.py        read-only WhatsApp example
docs/                  this documentation
```

## Adding a test page

Fixture pages are strings in `tests/conftest.py`, served from the `ROUTES` dict:

```python
ROUTES = {
    "/products": (200, PRODUCTS),
    "/feed": (200, FEED),
    ...
}
```

Add your HTML as a constant, register a path, and use the `server` and `khoji` fixtures:

```python
async def test_something(khoji: Khoji, server: str):
    page = await khoji.open(f"{server}/my-page")
    ...
```

Query strings are ignored for routing, so a page can read flags from `location.search` to vary its
behaviour (see `CHAT` and `FEED`).

## Code style

- Line length 110, enforced by ruff.
- Google-style docstrings with `Args`, `Returns`, `Raises` on every public function.
- Settings and results are frozen Pydantic models; reject unknown fields with `extra="forbid"`.
- In-page JavaScript lives in module or class constants, and one `evaluate` call returns one
  consistent snapshot.
- Platform classes hold selectors only; behaviour belongs in the base class.
- Never add settings for user agent, headers or viewport (see [Stealth](../advanced/stealth.md)).

## Documentation

Docs live in `docs/` as Markdown. When you change public behaviour:

1. Update the relevant guide in `docs/guides/`.
2. Update [the API reference](api.md).
3. Update the short summary in the root `README.md` if the feature is listed there.
