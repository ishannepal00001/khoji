# API reference

Every public name, its signature and its behaviour. Everything below the chat layer is importable
from `khoji`; chat names from `khoji.chat`; built-in sites from `khoji.sites`.

```python
from khoji import (
    Khoji,
    KhojiConfig,
    ProxyConfig,
    KhojiPage,
    Site,
    Selector,
    Extractor,
    Link,
    ScrollResult,
    BrowserLauncher,
    KhojiError,
    NavigationError,
    BlockedError,
    ExtractionError,
    ChatError,
    LoggedOutError,
    SendUnconfirmedError,
)
from khoji.chat import (
    ChatSite,
    ChatSettings,
    Chat,
    Message,
    SessionState,
    Conversation,
    ConversationResult,
    Responder,
)
from khoji.sites import WhatsApp
```

**Contents:** [Khoji](#khoji) · [KhojiConfig](#khojiconfig) · [ProxyConfig](#proxyconfig) ·
[KhojiPage](#khojipage) · [Link](#link) · [ScrollResult](#scrollresult) · [Extraction](#extraction) ·
[Site](#site) · [Errors](#errors) · [Chat layer](#chat-layer) · [BrowserLauncher](#browserlauncher)

---

## Khoji

```python
class Khoji(config: KhojiConfig | None = None)
```

Owns one browser (a persistent Patchright context) and hands out pages. Use as an async context
manager.

| Member | Description |
|---|---|
| `config: KhojiConfig` | The settings this client was created with |
| `context: BrowserContext` | The Patchright context. Raises `KhojiError` if not started |
| `async start() -> Self` | Launch the browser. No-op if running. Cleans up if the launch fails |
| `async close() -> None` | Close the browser and stop Patchright. Safe to call repeatedly |
| `async new_page() -> KhojiPage` | A blank tab of its own: the browser's initial blank tab the first time, new tabs after. Safe to call concurrently |
| `async open(url, *, wait_until="domcontentloaded", scroll=False) -> KhojiPage` | Open `url` in a tab; see below |
| `site(site_cls, **kwargs) -> S` | Instantiate a `Site` subclass bound to this client |

### `Khoji.open`

```python
async def open(url: str, *, wait_until: WaitUntil = "domcontentloaded", scroll: bool = False) -> KhojiPage
```

1. Gets a tab with `new_page()`.
2. Navigates and runs block detection (see `KhojiPage.goto`).
3. If `scroll`, runs `scroll_to_end()` with default limits.
4. On any failure, closes the tab and re-raises.

**Raises:** `NavigationError`, `BlockedError`, `KhojiError` (not started).

Safe to call from concurrent tasks; each call navigates its own tab.

`WaitUntil = Literal["commit", "domcontentloaded", "load", "networkidle"]`.

---

## KhojiConfig

```python
class KhojiConfig(BaseModel)  # frozen, extra="forbid"
```

| Field | Type | Default |
|---|---|---|
| `headless` | `bool` | `False` |
| `channel` | `str \| None` | `None` |
| `executable_path` | `Path \| None` | `None` |
| `user_data_dir` | `Path` | `KhojiConfig.default_profile_dir()` |
| `proxy` | `ProxyConfig \| None` | `None` |
| `locale` | `str \| None` | `None` |
| `timezone_id` | `str \| None` | `None` |
| `navigation_timeout_ms` | `int`, > 0 | `30_000` |
| `block_detection` | `bool` | `True` |
| `challenge_wait_ms` | `int`, ≥ 0 | `10_000` |

`executable_path` and `user_data_dir` have `~` expanded.

| Static method | Returns |
|---|---|
| `default_profile_dir() -> Path` | `$XDG_DATA_HOME/khoji/profile`, else `~/.local/share/khoji/profile`. Not created |

Details: [Configuration](../guides/configuration.md).

## ProxyConfig

```python
class ProxyConfig(BaseModel)  # frozen, extra="forbid"
```

| Field | Type | Default |
|---|---|---|
| `server` | `str` | required — `"http://host:8080"`, `"socks5://host:1080"` |
| `username` | `str \| None` | `None` |
| `password` | `SecretStr \| None` | `None` |

---

## KhojiPage

```python
class KhojiPage(page: Page, config: KhojiConfig, extractor: Extractor | None = None)
```

One browser tab. Normally obtained from `Khoji.open`, `Khoji.new_page` or `Site.open`.

| Member | Description |
|---|---|
| `raw: Page` | The Patchright page |
| `url: str` | Current URL |
| `async goto(url, *, wait_until="domcontentloaded") -> Self` | Navigate, then check for blocks if enabled |
| `async html() -> str` | Rendered HTML |
| `async extract(model, *, root=None) -> M` | One model from the page or the first `root` match |
| `async extract_all(model, *, root) -> list[M]` | One model per `root` match |
| `async scroll_to_end(...) -> ScrollResult` | See below |
| `async links(...) -> list[Link]` | See below |
| `async save_debug(directory, label) -> Path \| None` | Screenshot + HTML; never raises |
| `async close() -> None` | Close the tab |

### `goto`

**Raises:** `NavigationError` if loading fails. `BlockedError` if a challenge does not clear within
`challenge_wait_ms`, or the status is 403/429 with no challenge involved (only with
`block_detection`).

### `scroll_to_end`

```python
async def scroll_to_end(
    *,
    container: str | None = None,
    max_rounds: int = 50,
    timeout_ms: int = 30_000,
    pause_ms: tuple[int, int] = (500, 1200),
    settle_checks: int = 2,
) -> ScrollResult
```

Scrolls down with mouse-wheel steps of ~80% of the visible height (±15%) while there is content
below, pausing a random `pause_ms` after each step. At the bottom it waits up to `settle_checks`
pauses for more content before finishing. `container=None` scrolls the document, or the largest
scrollable element if the document cannot scroll. Falls back to direct `scrollBy` if the wheel
does not move the target.

**Returns** `ScrollResult`; `rounds=0` if nothing could scroll.
**Raises** `KhojiError` if `container` matches nothing.
Guide: [Scrolling](../guides/scrolling.md).

### `links`

```python
async def links(
    *,
    root: str | None = None,
    internal: bool | None = None,
    schemes: tuple[str, ...] = ("http", "https"),
) -> list[Link]
```

Every `<a href>` on the page (or inside the first `root` match), resolved to absolute URLs,
fragments removed, de-duplicated by URL keeping the first occurrence, filtered by `schemes` and
`internal`. Guide: [Collecting links](../guides/links.md).

### `save_debug`

```python
async def save_debug(directory: Path, label: str) -> Path | None
```

Writes `<directory>/<YYYYmmdd-HHMMSS>-<label>.png` and `.html`, creating `directory`. Returns the
path without extension, or `None` if saving failed (logged, not raised).

## Link

```python
class Link(BaseModel)  # frozen
```

| Field | Type | Description |
|---|---|---|
| `url` | `str` | Absolute URL without fragment |
| `text` | `str` | Visible text, whitespace collapsed; else `aria-label`, else `title`, else `""` |
| `title` | `str \| None` | `title` attribute |
| `rel` | `list[str]` | `rel` tokens; default `[]` |
| `internal` | `bool` | Host equals the page's host |

## ScrollResult

```python
class ScrollResult(BaseModel)  # frozen
```

| Field | Type | Description |
|---|---|---|
| `rounds` | `int` | Scroll steps taken |
| `height` | `int` | Final scroll height in px of the scrolled element |
| `reached_end` | `bool` | `False` when stopped by `max_rounds` or `timeout_ms` |

---

## Extraction

### Selector

```python
@dataclass(frozen=True)
class Selector:
    css: str
    attr: str | None = None  # keyword-only
    pattern: str | None = None  # keyword-only
    all: bool | None = None  # keyword-only
```

Used as `Annotated[T, Selector(...)]` metadata on a Pydantic field.

| Field type | Behaviour |
|---|---|
| scalar | First match's text (stripped) or attribute |
| `list` / `tuple` / `set` / `frozenset` | Every match; missing values dropped |
| `BaseModel` subclass | Nested model scoped to the first match |
| `list[BaseModel]` | Nested model per match |

`pattern`: `re.search`; group 1 if the pattern has groups, else the whole match; no match = missing.
`all`: overrides list detection.

Missing values: the key is omitted so field defaults apply; required fields fail as "missing".
Fields without a `Selector` are not scraped; required ones become `None`. The returned object is
always an instance of the caller's model class.

### Extractor

```python
class Extractor()
```

Stateless; one instance can be shared. `KhojiPage` creates one by default.

| Method | Description |
|---|---|
| `async extract(root: Page \| Locator, model, *, url: str) -> M` | Build `model` from `root`; raises `ExtractionError` with `url` |

---

## Site

```python
class Site(khoji: Khoji)
```

| Member | Description |
|---|---|
| `base_url: ClassVar[str]` | Must be set by subclasses |
| `khoji: Khoji` | The bound client |
| `url(path="/") -> str` | `urljoin(base_url, path)` |
| `async open(path="/", *, wait_until="domcontentloaded", scroll=False) -> KhojiPage` | `khoji.open(url(path), ...)`; caller closes the page |

Guide: [Site modules](../guides/site-modules.md).

---

## Errors

| Class | Base | Attributes | Raised when |
|---|---|---|---|
| `KhojiError` | `Exception` | — | Base class; also browser not started, unknown scroll container |
| `NavigationError` | `KhojiError` | — | Navigation failed or timed out |
| `BlockedError` | `KhojiError` | `url: str`, `status: int \| None` | Block or unresolved challenge |
| `ExtractionError` | `KhojiError` | `url: str`, `model: type` | Page did not satisfy the model |
| `ChatError` | `KhojiError` | — | Chat operation impossible |
| `LoggedOutError` | `ChatError` | — | Not logged in, or logged out while waiting |
| `SendUnconfirmedError` | `ChatError` | — | Sent message never confirmed; may have been sent |

---

## Chat layer

### ChatSite

```python
class ChatSite(Site, ABC)(khoji: Khoji, settings: ChatSettings | None = None)
```

| Member | Description |
|---|---|
| `name: ClassVar[str]` | Platform name; logs and debug subfolder |
| `home_path: ClassVar[str]` | Opened by `connect()`; default `"/"` |
| `UNVERIFIED: ClassVar[str]` | Fingerprint of a send confirmed only by visible text |
| `settings: ChatSettings` | Timings and paths |
| `page: KhojiPage` | The site's tab; `ChatError` if not connected |
| `async connect() -> Self` | Open `home_path`, wait for login. `LoggedOutError` on timeout |
| `async close() -> None` | Close the tab. Safe when not connected |
| `async chats() -> list[Chat]` | Settled chat list, top to bottom |
| `async find_chat(name) -> Chat` | Exact name; `ChatError` unless exactly one match |
| `async open_thread(chat) -> None` | Verify the row still matches, click, wait for the composer |
| `async messages(*, settled=False) -> list[Message]` | Rendered messages, oldest first, fingerprinted |
| `new_incoming(messages, after) -> list[Message]` | Static. Incoming messages below everything in `after` |
| `async send(text) -> Message` | Type, send, confirm. `SendUnconfirmedError` on failure |
| `async wait_for_reply(after, deadline) -> list[Message]` | Poll until new incoming messages or `deadline` (monotonic) |
| `async save_debug(label) -> Path \| None` | Into `settings.debug_dir / name` |
| `async inspect() -> dict` | Optional hook; `NotImplementedError` by default |

Abstract hooks: `_session_state`, `_chat_rows`, `_read_chat`, `_composer`, `_thread_is_open`,
`_read_messages`. Optional: `_thread_text`. See [Adding a chat platform](../advanced/custom-chat-platform.md).

### ChatSettings

Frozen Pydantic model. Fields and defaults: see [Chat sites → Settings](../guides/chat-sites.md#settings).

### Chat, Message, SessionState

| `Chat` field | Type |
|---|---|
| `position` | `int` (1-based) |
| `name` | `str` |
| `preview` | `str \| None` = `None` |

| `Message` field | Type |
|---|---|
| `id` | `str \| None` |
| `direction` | `Literal["in", "out"]` |
| `text` | `str` |
| `meta` | `str \| None` = `None` |
| `fingerprint` | `str` = `""` |

`SessionState` (`StrEnum`): `LOGGED_IN`, `LOGGED_OUT`, `LOADING`.

### Conversation

```python
class Conversation(site: ChatSite, chat: Chat, *, responder: Responder | None = None, max_replies: int = 1)
```

| Method | Description |
|---|---|
| `async run(opening: str \| None = None, *, resume: bool = False) -> ConversationResult` | Send, wait, reply loop |

`ConversationResult`: `received: list[Message]`, `replies_sent: int`, `timed_out: bool`.

### Responder

```python
class Responder(ABC):
    async def reply(self, chat: Chat, messages: list[Message]) -> list[str]: ...
```

Called once per incoming burst; return texts to send in order, or `[]`.

### WhatsApp

`ChatSite` for `https://web.whatsapp.com`. Selectors are class constants (`CHAT_ROWS`, `CHAT_NAME`,
`QR_CODE`, `THREAD`, `COMPOSER`, `MESSAGE_PANEL`) plus in-page scripts `READ_MESSAGES_JS` and
`INSPECT_JS`. Implements `inspect()`.

---

## BrowserLauncher

```python
class BrowserLauncher(config: KhojiConfig)
```

Used by `Khoji.start`. Public for custom setups.

| Member | Description |
|---|---|
| `chrome_installed() -> bool` | Class method. Chrome found in its standard location |
| `launch_options() -> dict` | Keyword arguments for `launch_persistent_context` |
| `async launch(playwright) -> BrowserContext` | Create the profile dir, launch, apply the navigation timeout |
