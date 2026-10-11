"""Message one chat on WhatsApp Web, then keep the page open and wait for the reply.

    uv run python examples/whatsapp.py --dry-run                       # list chats, send nothing
    uv run python examples/whatsapp.py --position 8 "Hello from khoji" # send, then wait for a reply
    uv run python examples/whatsapp.py --position 8 "Hi" --auto-reply  # also answer their replies
    uv run python examples/whatsapp.py --position 8 --listen --auto-reply  # resume without sending first
    uv run python examples/whatsapp.py --position 8 --inspect          # dump thread markup for debugging

The first run shows a QR code: scan it from your phone (Settings > Linked devices).
Khoji's persistent profile keeps you logged in afterwards. Login is never automated.

Everything lives in this one file, in sections: config, selectors, session, chat list,
thread, sender, waiting, main.
"""

import argparse
import asyncio
import hashlib
import logging
import random
import time
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from patchright.async_api import Error as PatchrightError
from patchright.async_api import Locator, Page
from pydantic import BaseModel

from khoji import Khoji, KhojiError, KhojiPage, Site

log = logging.getLogger("whatsapp")


# --------------------------------------------------------------------------- config


class Settings(BaseModel):
    login_timeout_s: float = 180
    """How long to wait for the QR code to be scanned."""

    settle_interval_s: float = 1.0
    settle_attempts: int = 20

    key_delay_ms: tuple[int, int] = (45, 140)
    """Per-key typing delay range."""

    pause_chance: float = 0.06
    """Chance of a short thinking pause after any key."""

    pause_ms: tuple[int, int] = (300, 900)
    pre_send_s: tuple[float, float] = (1.0, 2.5)
    send_verify_s: float = 20

    poll_s: tuple[float, float] = (5, 15)
    """Randomized gap between checks for a reply."""

    burst_s: tuple[float, float] = (4, 8)
    """After a reply arrives, wait this long for follow-up messages before reporting."""

    reading_s: tuple[float, float] = (3, 8)
    """Pause before answering, as if reading the incoming message."""

    wait_hours: float = 12
    debug_dir: Path = Path("debug/whatsapp")


# --------------------------------------------------------------------------- selectors
# Every selector is here and nowhere else. WhatsApp changes its markup without notice, so
# when something breaks, run with --inspect and fix the function below.
#
# Checked against the live page: chat_rows, chat_name, composer, message_panel, and the
# message rows ([data-id] inside the panel). Not yet seen live: qr_code, and the direction
# of an incoming message (tail-in icon / left alignment).


def chat_rows() -> str:
    return "#pane-side [role='listitem'], #pane-side [role='row']"


def chat_name() -> str:
    return "span[title]"


def qr_code() -> str:
    return "canvas[aria-label*='QR' i], canvas[aria-label*='Scan' i], [data-ref] canvas"


def thread() -> str:
    return "#main"


def composer() -> str:
    return "#main [data-testid='conversation-compose-box-input'], #main footer [contenteditable='true']"


def message_panel() -> str:
    return "#main [data-testid='conversation-panel-messages']"


# Runs in the page. One call gives a consistent snapshot of the open thread.
READ_MESSAGES_JS = """
() => {
  const panel = document.querySelector("#main [data-testid='conversation-panel-messages']");
  if (!panel) return [];
  const bounds = panel.getBoundingClientRect();
  const textNodes = "[data-testid='selectable-text'], span.selectable-text";
  return [...panel.querySelectorAll('[data-id]')].map(row => {
    // The bubble's tail says who sent it, but only the first message of a run has one.
    // Otherwise go by alignment: outgoing bubbles sit against the right edge.
    let direction;
    if (row.querySelector("[data-icon='tail-out']")) direction = 'out';
    else if (row.querySelector("[data-icon='tail-in']")) direction = 'in';
    else {
      const bubble = (row.querySelector("[data-testid='msg-container']") || row).getBoundingClientRect();
      direction = bubble.left - bounds.left > bounds.right - bubble.right ? 'out' : 'in';
    }
    const text = [...row.querySelectorAll(textNodes)]
      .filter(node => !node.parentElement.closest(textNodes))
      .map(node => node.innerText).join('\\n').trim();
    return {id: row.getAttribute('data-id'), direction, text};
  });
}
"""

# Structure only: attribute names and text lengths, never the message text itself.
INSPECT_JS = """
() => {
  const main = document.querySelector('#main');
  if (!main) return {error: '#main not found'};
  const attrs = el => Object.fromEntries([...el.attributes].map(a => [a.name, a.value.replace(/[0-9]{6,}/g, '#').slice(0, 60)]));
  return {
    composers: [...main.querySelectorAll("footer [contenteditable='true']")].map(attrs),
    dataIdNodes: main.querySelectorAll('[data-id]').length,
    messageIn: main.querySelectorAll('.message-in').length,
    messageOut: main.querySelectorAll('.message-out').length,
    roles: [...new Set([...main.querySelectorAll('[role]')].map(el => el.getAttribute('role')))],
    testIds: [...main.querySelectorAll('[data-testid]')].reduce((counts, el) => {
      const id = el.getAttribute('data-testid');
      counts[id] = (counts[id] || 0) + 1;
      return counts;
    }, {}),
    lastNodes: [...main.querySelectorAll('[data-id]')].slice(-3).map(el => ({
      tag: el.tagName,
      attrs: attrs(el),
      incoming: !!el.querySelector('.message-in'),
      outgoing: !!el.querySelector('.message-out'),
      textLengths: [...el.querySelectorAll('span.selectable-text')].map(span => span.innerText.length),
      icons: [...el.querySelectorAll('[data-icon]')].map(icon => icon.getAttribute('data-icon')),
    })),
  };
}
"""


# --------------------------------------------------------------------------- models


class State(StrEnum):
    LOGGED_IN = "logged_in"
    LOGGED_OUT = "logged_out"
    LOADING = "loading"


class Chat(BaseModel):
    position: int
    name: str
    preview: str | None = None


class Message(BaseModel):
    id: str | None
    direction: Literal["in", "out"]
    text: str
    meta: str | None = None
    fingerprint: str = ""


# --------------------------------------------------------------------------- site


class WhatsApp(Site):
    base_url = "https://web.whatsapp.com"

    def __init__(self, khoji: Khoji, settings: Settings | None = None) -> None:
        super().__init__(khoji)
        self.settings = settings or Settings()

    # ----- session

    async def state(self, page: Page) -> State:
        if await page.locator(chat_rows()).count():
            return State.LOGGED_IN
        if await page.locator(qr_code()).count():
            return State.LOGGED_OUT
        return State.LOADING

    async def open_chats(self) -> KhojiPage:
        """Open WhatsApp Web and wait for the chat list, giving time for a QR scan if needed."""
        page = await self.open("/")
        deadline = time.monotonic() + self.settings.login_timeout_s
        announced = False
        while time.monotonic() < deadline:
            state = await self.state(page.raw)
            if state is State.LOGGED_IN:
                return page
            if state is State.LOGGED_OUT and not announced:
                log.warning("Not logged in: scan the QR code in the browser window.")
                announced = True
            await page.raw.wait_for_timeout(1_000)
        await page.close()
        raise KhojiError("The chat list did not appear. Was the QR code scanned in time?")

    # ----- chat list (read without opening anything)

    async def chat_rows(self, page: Page) -> list[Locator]:
        """Chat rows from top to bottom as displayed.

        The list is virtualized, so DOM order is not screen order, and it keeps reordering
        while WhatsApp syncs after loading. Wait until two consecutive reads agree.
        """
        previous: list[str] = []
        for _ in range(self.settings.settle_attempts):
            rows = await page.locator(chat_rows()).all()
            placed = [(box["y"], row) for row in rows if (box := await row.bounding_box())]
            ordered = [row for _, row in sorted(placed, key=lambda item: item[0])]
            names = [await self._name(row) for row in ordered]
            if names and names == previous:
                return ordered
            previous = names
            await page.wait_for_timeout(self.settings.settle_interval_s * 1000)
        raise KhojiError("The chat list kept changing; could not read a stable order.")

    @staticmethod
    async def _name(row: Locator) -> str:
        return await row.locator(chat_name()).first.get_attribute("title") or ""

    async def snapshot(self, page: Page) -> list[Chat]:
        chats = []
        for position, row in enumerate(await self.chat_rows(page), start=1):
            titles = await row.locator(chat_name()).all()
            preview = await titles[1].get_attribute("title") if len(titles) > 1 else None
            chats.append(Chat(position=position, name=await self._name(row), preview=preview))
        return chats

    # ----- thread

    async def open_thread(self, page: Page, position: int) -> str:
        """Open the chat at `position` (1-based, as displayed) and return its name."""
        rows = await self.chat_rows(page)
        if position > len(rows):
            raise KhojiError(f"Only {len(rows)} chats are loaded; there is no chat #{position}.")
        row = rows[position - 1]
        name = await self._name(row)
        await row.click()
        await page.locator(composer()).first.wait_for(timeout=20_000)
        return name

    @staticmethod
    def _new_incoming(messages: list[Message], after: set[str]) -> list[Message]:
        """Incoming messages that arrived below everything in `after`.

        Older history that WhatsApp loads in above the known messages is not a reply, so
        only messages positioned after the last known one count.
        """
        known = [index for index, message in enumerate(messages) if message.fingerprint in after]
        if after and not known:
            return []  # the thread is re-rendering; nothing can be judged yet
        newer = messages[known[-1] + 1 :] if known else messages
        return [message for message in newer if message.direction == "in"]

    async def settled_messages(self, page: Page) -> list[Message]:
        """Read the thread once it has stopped loading: two consecutive reads must agree."""
        previous: list[str] | None = None
        for _ in range(self.settings.settle_attempts):
            messages = await self.messages(page)
            ids = [message.fingerprint for message in messages]
            if ids == previous:
                return messages
            previous = ids
            await page.wait_for_timeout(self.settings.settle_interval_s * 1500)
        raise KhojiError("The conversation kept changing; could not read it reliably.")

    async def messages(self, page: Page) -> list[Message]:
        """Messages in the open thread, oldest first, each with a stable fingerprint."""
        seen: dict[str, int] = {}
        messages = []
        for raw in await page.evaluate(READ_MESSAGES_JS):
            message = Message(**raw)
            if message.id:
                message.fingerprint = message.id
            else:
                # No stable id: hash direction and text, and number repeats ("ok", "ok")
                # so identical messages stay distinct.
                key = f"{message.direction}|{message.text}"
                seen[key] = seen.get(key, 0) + 1
                message.fingerprint = hashlib.sha256(f"{key}|{seen[key]}".encode()).hexdigest()[:16]
            messages.append(message)
        return messages

    # ----- sender

    async def send(self, page: Page, text: str) -> Message:
        """Type `text` into the open thread like a person, send it, and confirm it appeared."""
        settings = self.settings
        text = " ".join(text.split())  # Enter sends, so a newline would split the message
        before = {message.fingerprint for message in await self.messages(page)}

        box = page.locator(composer()).first
        await box.click()
        await page.wait_for_timeout(random.uniform(*settings.pre_send_s) * 1000)
        for character in text:
            await box.press_sequentially(character, delay=random.randint(*settings.key_delay_ms))
            if random.random() < settings.pause_chance:
                await page.wait_for_timeout(random.randint(*settings.pause_ms))
        await box.press("Enter")

        # Sent means: the composer emptied AND a new outgoing message carries our text.
        deadline = time.monotonic() + settings.send_verify_s
        while time.monotonic() < deadline:
            await page.wait_for_timeout(500)
            if (await box.inner_text()).strip():
                continue
            for message in await self.messages(page):
                if message.direction == "out" and message.fingerprint not in before and message.text == text:
                    return message
            # Fallback when the per-message selectors miss: the text is visible in the thread.
            shown = " ".join((await page.locator(message_panel()).first.inner_text()).split())
            if text in shown:
                return Message(id=None, direction="out", text=text, fingerprint="unverified")
        # Never retry blindly: the message may have gone out without us seeing it.
        raise KhojiError("Could not confirm the message was sent. Check the chat before sending again.")

    # ----- waiting

    async def wait_for_reply(self, page: Page, after: set[str], deadline: float) -> list[Message]:
        """Keep the page alive until an incoming message appears that is not in `after`.

        Returns an empty list if `deadline` (a `time.monotonic()` value) passes first.
        """
        settings = self.settings
        checks = 0
        while time.monotonic() < deadline:
            await page.wait_for_timeout(random.uniform(*settings.poll_s) * 1000)
            checks += 1
            if await page.locator(qr_code()).count():
                raise KhojiError("WhatsApp logged this session out while waiting.")
            if not await page.locator(thread()).count():
                raise KhojiError("The conversation is no longer open.")
            if self._new_incoming(await self.messages(page), after):
                # People often send several messages in a row; give the burst time to finish.
                await page.wait_for_timeout(random.uniform(*settings.burst_s) * 1000)
                return self._new_incoming(await self.messages(page), after)
            if checks % 30 == 0:
                log.info("Still waiting for a reply (%d checks so far).", checks)
        return []


# --------------------------------------------------------------------------- brain
# Knows nothing about the browser or WhatsApp. Swap the body for anything smarter later;
# the rest of the script only relies on this signature.


TECHNICAL_REPLIES = (
    (
        "Fun fact while you are here: a TLS 1.3 handshake finishes in a single round trip because the "
        "client sends its ephemeral X25519 key share in the ClientHello, the server answers with its own "
        "share plus a certificate signed over the transcript hash, and both sides derive the traffic "
        "secrets with HKDF, so application data can flow right after the server Finished message."
    ),
    (
        "Also worth knowing: a B-tree index keeps lookups at O(log n) by storing sorted keys in fixed "
        "size pages with a high fanout, so a table with a hundred million rows is usually only four "
        "levels deep, and a write-ahead log makes page splits crash safe by recording the change before "
        "the page itself is flushed to disk."
    ),
    (
        "One more: the Linux CFS scheduler picks the task with the smallest virtual runtime from a "
        "red-black tree, weights that runtime by the nice value, and preempts the running task once it "
        "exceeds its fair slice, which is why a CPU bound process at nice 19 still makes progress next "
        "to an interactive one instead of starving."
    ),
)


def generate_reply(thread_id: str, messages: list[Message]) -> list[str]:
    """Return the messages to send in answer to the conversation so far.

    Whatever they said, answer with the next technical paragraph that has not been sent in
    this conversation yet, so the same text never goes out twice (also across restarts).
    """
    already_sent = {message.text for message in messages if message.direction == "out"}
    for paragraph in TECHNICAL_REPLIES:
        if paragraph not in already_sent:
            return [paragraph]
    return []


# --------------------------------------------------------------------------- main


async def save_debug(page: Page, settings: Settings, label: str) -> None:
    """Keep a screenshot and the page HTML when something goes wrong."""
    try:
        settings.debug_dir.mkdir(parents=True, exist_ok=True)
        stem = settings.debug_dir / f"{datetime.now():%Y%m%d-%H%M%S}-{label}"
        await page.screenshot(path=f"{stem}.png")
        Path(f"{stem}.html").write_text(await page.content())
        log.error("Saved debug files to %s.{png,html}", stem)
    except (PatchrightError, OSError) as exc:
        log.error("Could not save debug files: %s", exc)


async def run(args: argparse.Namespace) -> int:
    settings = Settings(wait_hours=args.wait_hours)
    async with Khoji() as k:
        whatsapp = WhatsApp(k, settings)
        page = (await whatsapp.open_chats()).raw
        try:
            chats = await whatsapp.snapshot(page)
            if args.name:
                # Positions shift as chats get new messages; a name does not.
                matches = [chat for chat in chats if chat.name == args.name]
                if len(matches) != 1:
                    raise KhojiError(f"Expected one chat named {args.name!r}, found {len(matches)}.")
                args.position = matches[0].position
            for chat in chats[: max(args.position, 5) + 2]:
                marker = "->" if chat.position == args.position else "  "
                print(f"{marker} {chat.position}. {chat.name}")
            target = next((chat for chat in chats if chat.position == args.position), None)
            if target is None:
                raise KhojiError(f"Only {len(chats)} chats are loaded; there is no chat #{args.position}.")

            if args.dry_run:
                print(f"Dry run: would message chat #{target.position}, {target.name}. Nothing was sent.")
                return 0

            name = await whatsapp.open_thread(page, args.position)
            if name != target.name:
                raise KhojiError(f"Chat #{args.position} changed from {target.name} to {name}; not sending.")

            if args.inspect:
                await page.wait_for_timeout(3_000)  # let the history render
                print(await page.evaluate(INSPECT_JS))
                return 0

            if args.message:
                sent = await whatsapp.send(page, args.message)
                print(f"Sent to {name}: {sent.text}")
                if not sent.id:
                    # The message went out but the per-message selectors did not see it, so
                    # replies would be missed too. Show the markup so they can be fixed.
                    print("WARNING: message selectors did not match. Markup:")
                    print(await page.evaluate(INSPECT_JS))

            deadline = time.monotonic() + settings.wait_hours * 3600
            replies_sent = 0
            print(f"Waiting up to {settings.wait_hours:g} hours for {name} to reply. Leave the window open.")
            pending_from_before = args.listen
            while True:
                current = await whatsapp.settled_messages(page)
                after = {message.fingerprint for message in current}
                if pending_from_before:
                    # Resuming: anything they sent after our last message is still unanswered.
                    pending_from_before = False
                    last_out = max((i for i, m in enumerate(current) if m.direction == "out"), default=-1)
                    # With none of our messages in view there is no turn boundary to trust,
                    # so treat everything as already seen rather than as unanswered.
                    if last_out >= 0:
                        after = {message.fingerprint for message in current[: last_out + 1]}
                    summary = [(m.direction, len(m.text)) for m in current[-4:]]
                    print(f"Resumed: {len(current)} messages loaded, last few (direction, length): {summary}")
                incoming = await whatsapp.wait_for_reply(page, after, deadline)
                if not incoming:
                    print(f"Stopped waiting: no new message from {name} before the time limit.")
                    return 0 if replies_sent else 2
                for message in incoming:
                    print(f"{name} said: {message.text or '[non-text message]'}")

                if not args.auto_reply:
                    return 0
                if replies_sent >= args.max_replies:
                    print(f"Reply limit of {args.max_replies} reached; still listening, not replying.")
                    continue
                # The whole burst is one turn and gets one answer.
                for text in generate_reply(name, await whatsapp.messages(page)):
                    await page.wait_for_timeout(random.uniform(*settings.reading_s) * 1000)
                    sent = await whatsapp.send(page, text)
                    print(f"Replied to {name}: {sent.text}")
                replies_sent += 1
        except (KhojiError, PatchrightError) as exc:
            await save_debug(page, settings, "error")
            print(f"Failed: {exc}")
            return 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("message", nargs="?", help="text to send")
    parser.add_argument(
        "--position", type=int, default=2, help="which chat to message, counted from the top (default 2)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="list the chats and the recipient; send nothing"
    )
    parser.add_argument(
        "--inspect", action="store_true", help="open the chat and dump its markup; send nothing"
    )
    parser.add_argument(
        "--wait-hours", type=float, default=Settings().wait_hours, help="how long to wait for a reply"
    )
    parser.add_argument("--name", help="pick the chat by its exact name instead of --position")
    parser.add_argument("--auto-reply", action="store_true", help="answer their replies (see generate_reply)")
    parser.add_argument("--max-replies", type=int, default=1, help="stop answering after this many replies")
    parser.add_argument("--listen", action="store_true", help="open the chat and wait without sending first")
    args = parser.parse_args()
    if not (args.dry_run or args.inspect or args.listen or args.message):
        parser.error("give a message to send, or use --dry-run / --inspect / --listen")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
