# Chat sites

> **Level:** intermediate → advanced · **Prerequisites:** [Site modules](site-modules.md)

khoji can drive chat web apps — reading chats, sending messages and replying automatically —
through a real logged-in browser. WhatsApp Web ships with khoji.

> **Warning:** this sends real messages from your account. Test on a chat with yourself or a
> friend who knows, keep reply limits low, and follow the platform's terms. Automated messaging
> can get an account banned.

- [How it is organised](#how-it-is-organised)
- [Logging in](#logging-in)
- [Reading chats and messages](#reading-chats-and-messages)
- [Sending](#sending)
- [Waiting for replies](#waiting-for-replies)
- [Conversations and responders](#conversations-and-responders)
- [Settings](#settings)
- [Debugging](#debugging)

## How it is organised

```text
Site (sites/base.py)                     base_url, open a page
 └─ ChatSite (chat/site.py)              login wait, chat list, thread, send, wait for reply
     └─ WhatsApp (sites/whatsapp.py)     only selectors and in-page JS

Conversation (chat/conversation.py)      the send → wait → reply loop
Responder (chat/responder.py)            decides what to say; knows nothing about browsers
```

All behaviour lives once in `ChatSite`. A platform class only says *where things are on the page*.
That is why adding a platform is small; see [Adding a chat platform](../advanced/custom-chat-platform.md).

Imports:

```python
from khoji import Khoji
from khoji.chat import Chat, ChatSettings, Conversation, Message, Responder
from khoji.sites import WhatsApp
```

## Logging in

Login is **never automated**. khoji opens the site and waits for you:

```python
async with Khoji() as k, k.site(WhatsApp) as wa:
    ...
```

On the first run, a QR code appears in the browser window. Scan it from your phone
(*Settings → Linked devices*). khoji waits up to `login_timeout_s` (3 minutes by default) for the
chat list, then raises `LoggedOutError` if it never appears.

The persistent profile keeps the session, so later runs go straight to the chat list.

`async with k.site(WhatsApp)` calls `connect()` on entry and `close()` on exit. You can call them
yourself instead.

## Reading chats and messages

### The chat list

```python
chats = await wa.chats()  # loaded chats, top to bottom
alice = await wa.find_chat("Alice")
```

A `Chat` has:

| Field | Meaning |
|---|---|
| `position` | 1-based place in the list, as displayed |
| `name` | Contact or group name |
| `preview` | Latest message preview, if shown |

Chat lists reorder as messages arrive, so khoji reads the list repeatedly until two reads agree.
`find_chat` matches the **exact** name and raises `ChatError` if zero or several chats match.

### Opening a thread

```python
await wa.open_thread(alice)
```

Before clicking, khoji re-reads the list and checks that the row at `alice.position` still shows
`"Alice"`. If the list moved in the meantime, it raises `ChatError` rather than open the wrong
chat — so you can never message the wrong person because of a reorder.

> **Note:** opening a chat marks its messages as read on the platform.

### Messages

```python
messages = await wa.messages(settled=True)
for m in messages:
    print(m.direction, m.text)
```

A `Message` has:

| Field | Meaning |
|---|---|
| `id` | The platform's message id, or `None` |
| `direction` | `"in"` (they sent it) or `"out"` (you sent it) |
| `text` | Message text; empty for media |
| `meta` | Extra details such as time and sender, e.g. `"[10:32, 12/10/2026] Alice: "` |
| `fingerprint` | Stable identity: the id, or a hash of direction + text + occurrence |

`settled=True` waits until two reads agree, for a thread that is still loading. Only **rendered**
messages are returned; older history is not scrolled in.

## Sending

```python
sent = await wa.send("Hello!")
```

`send()` behaves like a person:

1. Clicks the message box and pauses (`pre_send_s`).
2. Types key by key with uneven delays (`key_delay_ms`) and the occasional thinking pause.
3. Presses Enter.
4. **Confirms** the message: the box emptied *and* a new outgoing message with this text appeared.

Line breaks are flattened to spaces, since Enter sends.

If confirmation fails within `send_verify_s`, it raises `SendUnconfirmedError`.

> **Warning:** `SendUnconfirmedError` means *unconfirmed*, not *unsent*. The message may have gone
> out. khoji never retries a send by itself; check the chat before sending again.

If the per-message selectors miss but the text is visible in the thread, `send()` still succeeds
and returns a message whose fingerprint is `WhatsApp.UNVERIFIED`. That is a sign the selectors need
updating.

## Waiting for replies

```python
import time

seen = {m.fingerprint for m in await wa.messages(settled=True)}
deadline = time.monotonic() + 3600
replies = await wa.wait_for_reply(seen, deadline)
```

`wait_for_reply` polls at random gaps (`poll_s`, 5–15 s by default) and returns the new incoming
messages. When a reply arrives it waits a little longer (`burst_s`) in case they send several in a
row, so a burst comes back as one list. It returns `[]` at the deadline, and raises
`LoggedOutError` or `ChatError` if the session ends or the thread closes.

Only messages **below** everything already seen count. Older history that the site loads above is
never mistaken for a reply.

## Conversations and responders

`Conversation` puts send and wait together:

```python
class Echo(Responder):
    async def reply(self, chat: Chat, messages: list[Message]) -> list[str]:
        last = [m for m in messages if m.direction == "in"][-1]
        return [f"You said: {last.text}"]


async with Khoji() as k, k.site(WhatsApp) as wa:
    chat = await wa.find_chat("Alice")
    await wa.open_thread(chat)
    result = await Conversation(wa, chat, responder=Echo(), max_replies=3).run("Hello")

print(result.received, result.replies_sent, result.timed_out)
```

### How `run()` behaves

| Setup | Behaviour |
|---|---|
| No responder | Sends the opening (if any), returns as soon as they reply |
| With responder | Answers each turn until `max_replies` turns are answered, then keeps listening without replying until `wait_hours` |
| `run(opening=None)` | Starts by listening |
| `run(resume=True)` | Anything they sent after your last message counts as unanswered — for picking up after a restart |

A whole burst of their messages is one turn and gets one call to `reply()`. Before each answer
khoji pauses for `reading_s`, as if reading.

### Writing a responder

A `Responder` knows nothing about browsers. It gets the chat and the conversation so far
(oldest first, including your own `"out"` messages) and returns texts to send — or `[]` to stay
silent. That makes it easy to plug in anything, including an LLM:

```python
class Assistant(Responder):
    def __init__(self, llm):
        self.llm = llm

    async def reply(self, chat, messages):
        history = [
            {"role": "user" if m.direction == "in" else "assistant", "content": m.text}
            for m in messages
            if m.text
        ]
        answer = await self.llm.complete(history)
        return [answer] if answer else []
```

`ConversationResult`:

| Field | Meaning |
|---|---|
| `received` | Every incoming message during the run, oldest first |
| `replies_sent` | Turns answered through the responder |
| `timed_out` | `True` if `wait_hours` passed |

## Settings

```python
from khoji.chat import ChatSettings

wa = k.site(WhatsApp, settings=ChatSettings(wait_hours=1, poll_s=(10, 20)))
```

Ranges are `(min, max)`; a value is drawn at random each time.

| Setting | Default | Meaning |
|---|---|---|
| `login_timeout_s` | `180` | How long to wait for you to log in |
| `login_poll_s` | `1.0` | Gap between login checks |
| `settle_interval_s` | `1.0` | Gap between chat-list reads while it settles |
| `thread_settle_interval_s` | `1.5` | Gap between thread reads while it settles |
| `settle_attempts` | `20` | Reads before giving up on something that keeps changing |
| `key_delay_ms` | `(45, 140)` | Per-key typing delay |
| `pause_chance` | `0.06` | Chance of a thinking pause after any key |
| `pause_ms` | `(300, 900)` | Length of a thinking pause |
| `pre_send_s` | `(1.0, 2.5)` | Pause between focusing the box and typing |
| `send_verify_s` | `20` | How long to wait for a sent message to appear |
| `poll_s` | `(5, 15)` | Gap between reply checks |
| `burst_s` | `(4, 8)` | Extra wait after a reply, for follow-ups |
| `reading_s` | `(3, 8)` | Pause before answering |
| `wait_hours` | `12` | How long a conversation waits for a reply |
| `debug_dir` | `debug` | Where `save_debug` writes; a subfolder per site |

> **Warning:** the random delays are what make the activity look human. Shorten them with care.

## Debugging

```python
await wa.save_debug("after-send")  # debug/whatsapp/<timestamp>-after-send.{png,html}
print(await wa.inspect())  # structure-only dump of the open thread's markup
```

`inspect()` reports test ids, roles, icons and text *lengths* — never message text — so its output
is safe to share when asking for help fixing selectors.

A complete read-only example, which prints the latest messages of one chat and sends nothing, is
in [`examples/whatsapp.py`](../../examples/whatsapp.py):

```sh
uv run python examples/whatsapp.py --name "Alice" --limit 10
```

---

**Related:** [Adding a chat platform](../advanced/custom-chat-platform.md) ·
[API reference](../reference/api.md#chat-layer)
