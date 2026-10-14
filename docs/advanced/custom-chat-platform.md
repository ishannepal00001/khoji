# Adding a chat platform

> **Level:** advanced · **Prerequisites:** [Chat sites](../guides/chat-sites.md),
> [Going below khoji](raw-patchright.md)

`ChatSite` implements login waits, the chat list, thread safety checks, human typing, send
confirmation and reply polling once. A new platform only answers *"where is X on this page?"*
through a handful of hooks. WhatsApp's whole implementation is about 150 lines, most of it
selectors and one in-page script.

- [The contract](#the-contract)
- [Step by step](#step-by-step)
- [Hook by hook](#hook-by-hook)
- [Rules that keep it reliable](#rules-that-keep-it-reliable)
- [Testing without the real site](#testing-without-the-real-site)

## The contract

```python
from typing import ClassVar

from patchright.async_api import Locator

from khoji.chat import Chat, ChatSite, Message, SessionState


class MyChat(ChatSite):
    name = "mychat"  # logs and debug subfolder
    base_url = "https://chat.example.com"
    home_path = "/"  # opened by connect(); default "/"

    async def _session_state(self) -> SessionState: ...
    async def _chat_rows(self) -> list[Locator]: ...
    async def _read_chat(self, row: Locator, position: int) -> Chat: ...
    def _composer(self) -> Locator: ...
    async def _thread_is_open(self) -> bool: ...
    async def _read_messages(self) -> list[Message]: ...

    # optional
    async def _thread_text(self) -> str: ...
    async def inspect(self) -> dict: ...
```

| Hook | Required | Returns |
|---|---|---|
| `_session_state()` | yes | `LOGGED_IN` when the chat list shows, `LOGGED_OUT` when a login prompt shows, else `LOADING` |
| `_chat_rows()` | yes | Chat list rows, **top to bottom as displayed**, from one read |
| `_read_chat(row, position)` | yes | A `Chat` from one row |
| `_composer()` | yes | Locator of the message input (not async) |
| `_thread_is_open()` | yes | Whether a conversation is open |
| `_read_messages()` | yes | The open thread's messages, **oldest first**, `fingerprint` left empty; `[]` if none open |
| `_thread_text()` | no | Visible text of the message area. Default: the whole page body |
| `inspect()` | no | A structure-only description of the thread markup |

Use `self.page.raw` inside hooks to reach the Patchright page.

## Step by step

1. **Open the app** with khoji (headed), log in by hand, and open DevTools.
2. **Find stable selectors.** Prefer `data-testid`, `role`, `aria-*` and ids over generated class
   names like `.x1n2onr6`, which change with every deploy.
3. **Put every selector in a class constant**, nowhere else. When the site changes, you edit
   one block:

   ```python
   CHAT_ROWS: ClassVar[str] = "#sidebar [role='listitem']"
   CHAT_NAME: ClassVar[str] = ".conversation-name"
   COMPOSER: ClassVar[str] = "footer [contenteditable='true']"
   MESSAGES: ClassVar[str] = "#thread [data-message-id]"
   LOGIN: ClassVar[str] = "form#login"
   ```

4. **Implement the hooks** (below).
5. **Try it read-only** first: `chats()`, `open_thread()`, `messages()`. Only then `send()` — to
   yourself.
6. **Add `inspect()`** so future breakages can be diagnosed without sharing message text.
7. **Export it** from `khoji/sites/__init__.py` if it ships with khoji.

## Hook by hook

### `_session_state`

Check the logged-in sign first; a page in transition can briefly show both.

```python
async def _session_state(self) -> SessionState:
    page = self.page.raw
    if await page.locator(self.CHAT_ROWS).count():
        return SessionState.LOGGED_IN
    if await page.locator(self.LOGIN).count():
        return SessionState.LOGGED_OUT
    return SessionState.LOADING
```

### `_chat_rows` and `_read_chat`

Return rows in **screen order**. Virtualised lists often keep DOM order different from what you
see; sort by position as WhatsApp does:

```python
async def _chat_rows(self) -> list[Locator]:
    rows = await self.page.raw.locator(self.CHAT_ROWS).all()
    placed = [(box["y"], row) for row in rows if (box := await row.bounding_box())]
    return [row for _, row in sorted(placed, key=lambda item: item[0])]


async def _read_chat(self, row: Locator, position: int) -> Chat:
    name = await row.locator(self.CHAT_NAME).first.inner_text()
    return Chat(position=position, name=name.strip())
```

Do **not** wait for the list to settle here. The base class reads repeatedly and compares.

### `_composer` and `_thread_is_open`

```python
def _composer(self) -> Locator:
    return self.page.raw.locator(self.COMPOSER).first


async def _thread_is_open(self) -> bool:
    return bool(await self.page.raw.locator("#thread").count())
```

`open_thread()` waits for the composer to appear after clicking a row, so it must only exist when a
thread is open.

### `_read_messages`

This is where most of the work is. Two approaches:

**Locators** — simple, fine for small threads:

```python
async def _read_messages(self) -> list[Message]:
    rows = await self.page.raw.locator(self.MESSAGES).all()
    return [
        Message(
            id=await row.get_attribute("data-message-id"),
            direction="out" if "outgoing" in (await row.get_attribute("class") or "") else "in",
            text=(await row.inner_text()).strip(),
        )
        for row in rows
    ]
```

**One in-page script** — what WhatsApp uses. Each locator call is a round trip, and the thread can
change between them. A single `evaluate` returns a consistent snapshot and is much faster:

```python
READ_MESSAGES_JS: ClassVar[str] = """
() => [...document.querySelectorAll('#thread [data-message-id]')].map(row => ({
  id: row.dataset.messageId,
  direction: row.classList.contains('outgoing') ? 'out' : 'in',
  text: row.querySelector('.body')?.innerText.trim() ?? '',
  meta: row.querySelector('time')?.getAttribute('datetime') ?? null,
}))
"""


async def _read_messages(self) -> list[Message]:
    return [Message(**raw) for raw in await self.page.raw.evaluate(self.READ_MESSAGES_JS)]
```

Leave `fingerprint` empty. The base class sets it from `id`, or hashes direction and text when
there is no id.

### `_thread_text` (optional)

Used only as a last resort to confirm a send. Override it to read just the message area, so text
in the chat list beside it cannot cause a false confirmation.

### `inspect` (optional)

Return structure only — counts, attribute names, test ids, text *lengths* — never message text.
See `WhatsApp.INSPECT_JS` for a template.

## Rules that keep it reliable

- **Direction must be right.** `Conversation` relies on `"in"`/`"out"` to know what is a reply. Test
  both directions, including consecutive messages from the same side.
- **Oldest first.** Reply detection takes "below everything seen" as new.
- **Stable ids.** If the platform has a message id, return it. Fingerprints from text alone cannot
  tell two identical messages from one another as reliably.
- **No waiting inside hooks.** Hooks read once. Settling, polling and timeouts belong to the base
  class.
- **No sending outside `send()`.** It holds the confirmation and no-retry guarantees.

## Testing without the real site

khoji's own chat tests run against a tiny fake chat app served from `tests/conftest.py`, with a
`FakeChat(ChatSite)` in `tests/test_chat.py` implementing the hooks in about 40 lines. Copy that
pattern: write a small HTML page that behaves like the platform (query flags for edge cases such
as slow login or a swallowed send), and test your hooks against it. Your real-site selectors then
only need a manual check.

---

**Related:** [Chat sites](../guides/chat-sites.md) · [API reference](../reference/api.md#chat-layer)
