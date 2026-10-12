"""`ChatSite`: the base class for a browser-driven chat platform."""

import hashlib
import logging
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Self

from patchright.async_api import Locator

from ..errors import ChatError, LoggedOutError, SendUnconfirmedError
from ..page import KhojiPage
from ..sites.base import Site
from .models import Chat, Message, SessionState
from .settings import ChatSettings

if TYPE_CHECKING:
    from ..client import Khoji

log = logging.getLogger("khoji.chat")


class ChatSite(Site, ABC):
    """Base class for a chat web app: log in, list chats, open one, send and wait for replies.

    Everything that is the same on every platform lives here. A platform subclass sets `name`
    and `base_url` and implements the hooks (the abstract methods), which only say where
    things are on the page:

        class WhatsApp(ChatSite):
            name = "whatsapp"
            base_url = "https://web.whatsapp.com"
            ...

        async with Khoji() as k, k.site(WhatsApp) as wa:
            chat = await wa.find_chat("Alice")
            await wa.open_thread(chat)
            await wa.send("Hello")

    A chat site owns one tab and one open thread at a time. Login is never automated: the
    user logs in from the browser window and the persistent profile keeps the session.

    Attributes:
        name: Short platform name, used in logs and as the debug subfolder.
        home_path: Path opened by `connect()`, relative to `base_url`.
        settings: Timings and paths used by every method.
    """

    name: ClassVar[str]
    home_path: ClassVar[str] = "/"

    UNVERIFIED: ClassVar[str] = "unverified"
    """Fingerprint of a sent message that was confirmed only by its visible text."""

    _SEND_POLL_MS: ClassVar[int] = 500
    _COMPOSER_TIMEOUT_MS: ClassVar[int] = 20_000

    def __init__(self, khoji: "Khoji", settings: ChatSettings | None = None) -> None:
        """Bind the chat site to a browser. No page is opened until `connect()`.

        Args:
            khoji: A started `Khoji` client.
            settings: Timings and paths. Defaults to `ChatSettings()`.
        """
        super().__init__(khoji)
        self.settings = settings or ChatSettings()
        self._page: KhojiPage | None = None

    @property
    def page(self) -> KhojiPage:
        """The tab this chat site lives in.

        Raises:
            ChatError: If `connect()` has not been called.
        """
        if self._page is None:
            raise ChatError(f"{self.name} is not connected; use `async with` or call connect().")
        return self._page

    # ----- hooks: the only code a platform has to write

    @abstractmethod
    async def _session_state(self) -> SessionState:
        """Report whether the page shows the chat list, a login prompt, or neither yet."""

    @abstractmethod
    async def _chat_rows(self) -> list[Locator]:
        """Read the chat list rows once, ordered top to bottom as displayed.

        Do not wait for the list to settle here; the base class does that.
        """

    @abstractmethod
    async def _read_chat(self, row: Locator, position: int) -> Chat:
        """Build a `Chat` from one chat list row.

        Args:
            row: A row returned by `_chat_rows`.
            position: The row's 1-based position from the top.
        """

    @abstractmethod
    def _composer(self) -> Locator:
        """Return the locator of the open thread's message input."""

    @abstractmethod
    async def _thread_is_open(self) -> bool:
        """Report whether a conversation is currently open."""

    @abstractmethod
    async def _read_messages(self) -> list[Message]:
        """Read the rendered messages of the open thread once, oldest first.

        Leave `fingerprint` empty; the base class fills it in. Return an empty list when no
        thread is open.
        """

    async def _thread_text(self) -> str:
        """Return the visible text of the open thread.

        Used as a last resort to confirm a send when `_read_messages` did not see it. The
        default reads the whole page; override it to read just the message area.
        """
        return await self.page.raw.locator("body").inner_text()

    async def inspect(self) -> dict[str, Any]:
        """Describe the open thread's markup, for fixing selectors when the site changes.

        Optional hook. Implementations should report structure only, never message text.

        Raises:
            NotImplementedError: If the platform does not provide it.
        """
        raise NotImplementedError(f"{self.name} does not implement inspect().")

    # ----- session

    async def connect(self) -> Self:
        """Open the site and wait for the chat list, giving the user time to log in.

        Does nothing if already connected.

        Returns:
            This site, connected.

        Raises:
            LoggedOutError: If the chat list did not appear within `login_timeout_s`. The tab
                is closed first.
        """
        if self._page is not None:
            return self
        self._page = await self.open(self.home_path)
        deadline = time.monotonic() + self.settings.login_timeout_s
        announced = False
        while time.monotonic() < deadline:
            state = await self._session_state()
            if state is SessionState.LOGGED_IN:
                return self
            if state is SessionState.LOGGED_OUT and not announced:
                log.warning("%s: not logged in; log in from the browser window.", self.name)
                announced = True
            await self._sleep(self.settings.login_poll_s)
        await self.close()
        raise LoggedOutError(f"{self.name}: the chat list did not appear. Was the login completed in time?")

    async def close(self) -> None:
        """Close the tab. Safe to call when not connected."""
        page, self._page = self._page, None
        if page is not None:
            await page.close()

    async def __aenter__(self) -> Self:
        """Connect on entering `async with`.

        Returns:
            This site, connected.
        """
        return await self.connect()

    async def __aexit__(self, *exc_info: object) -> None:
        """Close the tab on leaving `async with`. Exceptions are not suppressed.

        Args:
            *exc_info: Exception type, value and traceback, or three Nones.
        """
        await self.close()

    # ----- chat list (read without opening anything)

    async def chats(self) -> list[Chat]:
        """Read the loaded chat list without opening anything.

        Returns:
            The chats from top to bottom, with 1-based positions.

        Raises:
            ChatError: If the chat list would not settle.
        """
        return [chat for _, chat in await self._settled_rows()]

    async def find_chat(self, name: str) -> Chat:
        """Find a chat by its exact name. Positions shift as messages arrive; a name does not.

        Args:
            name: The chat's name exactly as displayed.

        Returns:
            The matching chat.

        Raises:
            ChatError: If no loaded chat, or more than one, has that name.
        """
        matches = [chat for chat in await self.chats() if chat.name == name]
        if len(matches) != 1:
            raise ChatError(f"{self.name}: expected one chat named {name!r}, found {len(matches)}.")
        return matches[0]

    async def open_thread(self, chat: Chat) -> None:
        """Open a chat's conversation.

        The list is read again first and the row at the chat's position must still carry its
        name, so a list that reordered in the meantime cannot lead to the wrong recipient.

        Args:
            chat: A chat from `chats()` or `find_chat()`.

        Raises:
            ChatError: If that position is no longer loaded, or now holds a different chat.
        """
        rows = await self._settled_rows()
        if not 1 <= chat.position <= len(rows):
            raise ChatError(
                f"{self.name}: only {len(rows)} chats are loaded; there is no chat #{chat.position}."
            )
        row, current = rows[chat.position - 1]
        if current.name != chat.name:
            raise ChatError(
                f"{self.name}: chat #{chat.position} changed from {chat.name!r} to {current.name!r}; not opening."
            )
        await row.click()
        await self._composer().wait_for(timeout=self._COMPOSER_TIMEOUT_MS)

    # ----- thread

    async def messages(self, *, settled: bool = False) -> list[Message]:
        """Messages in the open thread, oldest first, each with a stable fingerprint.

        Only messages currently rendered are returned; older history is not scrolled in.

        Args:
            settled: Wait until two consecutive reads agree, for a thread that is still loading.

        Returns:
            The rendered messages. Empty if no thread is open.

        Raises:
            ChatError: If `settled` is set and the thread kept changing.
        """
        if not settled:
            return self._fingerprint(await self._read_messages())
        return await self._settled(
            self.messages,
            key=lambda messages: [message.fingerprint for message in messages],
            interval_s=self.settings.thread_settle_interval_s,
            what="conversation",
            allow_empty=True,
        )

    @staticmethod
    def new_incoming(messages: list[Message], after: set[str]) -> list[Message]:
        """Incoming messages that arrived below everything in `after`.

        Older history that the site loads in above the known messages is not a reply, so
        only messages positioned after the last known one count.

        Args:
            messages: The thread as currently read, oldest first.
            after: Fingerprints of the messages that were already seen.

        Returns:
            The new incoming messages, oldest first. Empty when `after` is non-empty but none
            of its messages are in view.
        """
        known = [index for index, message in enumerate(messages) if message.fingerprint in after]
        if after and not known:
            return []  # the thread is re-rendering; nothing can be judged yet
        newer = messages[known[-1] + 1 :] if known else messages
        return [message for message in newer if message.direction == "in"]

    async def send(self, text: str) -> Message:
        """Type `text` into the open thread like a person, send it, and confirm it appeared.

        Args:
            text: The message. Line breaks are flattened to spaces, since Enter sends.

        Returns:
            The sent message as read back from the thread. Its `id` is None and its
            fingerprint is `UNVERIFIED` when only the visible text confirmed it.

        Raises:
            SendUnconfirmedError: If the message could not be confirmed within
                `send_verify_s`. It may still have been sent, so check the chat before
                sending again.
        """
        settings = self.settings
        text = " ".join(text.split())  # Enter sends, so a newline would split the message
        before = {message.fingerprint for message in await self.messages()}

        box = self._composer()
        await box.click()
        await self._sleep(random.uniform(*settings.pre_send_s))
        await self._type(box, text)
        await box.press("Enter")

        # Sent means: the composer emptied AND a new outgoing message carries our text.
        deadline = time.monotonic() + settings.send_verify_s
        while time.monotonic() < deadline:
            await self.page.raw.wait_for_timeout(self._SEND_POLL_MS)
            if (await box.inner_text()).strip():
                continue
            for message in await self.messages():
                if message.direction == "out" and message.fingerprint not in before and message.text == text:
                    return message
            # Fallback when the per-message selectors miss: the text is visible in the thread.
            if text in " ".join((await self._thread_text()).split()):
                return Message(id=None, direction="out", text=text, fingerprint=self.UNVERIFIED)
        # Never retry blindly: the message may have gone out without us seeing it.
        raise SendUnconfirmedError(
            f"{self.name}: could not confirm the message was sent. Check the chat before sending again."
        )

    async def wait_for_reply(self, after: set[str], deadline: float) -> list[Message]:
        """Keep the page alive until an incoming message appears that is not in `after`.

        Args:
            after: Fingerprints of the messages already seen.
            deadline: When to stop waiting, as a `time.monotonic()` value.

        Returns:
            The new incoming messages, including any that followed within the burst window.
            Empty if the deadline passed first.

        Raises:
            LoggedOutError: If the site logged the session out while waiting.
            ChatError: If the conversation is no longer open.
        """
        settings = self.settings
        checks = 0
        while time.monotonic() < deadline:
            await self._sleep(random.uniform(*settings.poll_s))
            checks += 1
            if await self._session_state() is SessionState.LOGGED_OUT:
                raise LoggedOutError(f"{self.name} logged this session out while waiting.")
            if not await self._thread_is_open():
                raise ChatError(f"{self.name}: the conversation is no longer open.")
            if self.new_incoming(await self.messages(), after):
                # People often send several messages in a row; give the burst time to finish.
                await self._sleep(random.uniform(*settings.burst_s))
                return self.new_incoming(await self.messages(), after)
            if checks % 30 == 0:
                log.info("%s: still waiting for a reply (%d checks so far).", self.name, checks)
        return []

    async def save_debug(self, label: str) -> Path | None:
        """Save a screenshot and the page HTML under `debug_dir/<name>`.

        The files contain whatever is on screen, including chat names and message text.

        Args:
            label: Short tag added to the timestamped file names.

        Returns:
            The path of the saved files without extension, or None if saving failed.
        """
        return await self.page.save_debug(self.settings.debug_dir / self.name, label)

    # ----- helpers

    async def _sleep(self, seconds: float) -> None:
        """Wait on the page's own clock, which keeps the tab alive while waiting.

        Args:
            seconds: How long to wait.
        """
        await self.page.raw.wait_for_timeout(seconds * 1000)

    async def _settled[T](
        self,
        read: Callable[[], Awaitable[T]],
        *,
        key: Callable[[T], list[str]],
        interval_s: float,
        what: str,
        allow_empty: bool,
    ) -> T:
        """Read something that may still be loading until two consecutive reads agree.

        Args:
            read: Performs one read.
            key: Reduces a read to the list compared between reads (names, fingerprints).
            interval_s: Gap between reads.
            what: What is being read, for the error message.
            allow_empty: Whether an empty read can count as settled.

        Returns:
            The first read that matched the one before it.

        Raises:
            ChatError: If no two consecutive reads agreed within `settle_attempts`.
        """
        previous: list[str] | None = None
        for _ in range(self.settings.settle_attempts):
            result = await read()
            current = key(result)
            if current == previous and (current or allow_empty):
                return result
            previous = current
            await self._sleep(interval_s)
        raise ChatError(f"{self.name}: the {what} kept changing; could not read it reliably.")

    async def _read_rows(self) -> list[tuple[Locator, Chat]]:
        """Read the chat list once, pairing each row with the chat it shows."""
        rows = await self._chat_rows()
        return [(row, await self._read_chat(row, position)) for position, row in enumerate(rows, start=1)]

    async def _settled_rows(self) -> list[tuple[Locator, Chat]]:
        """Read the chat list once its order has stopped changing.

        Chat lists are often virtualised and keep reordering while the site syncs after
        loading, so a single read cannot be trusted.

        Raises:
            ChatError: If the order was still changing after `settle_attempts` reads.
        """
        return await self._settled(
            self._read_rows,
            key=lambda rows: [chat.name for _, chat in rows],
            interval_s=self.settings.settle_interval_s,
            what="chat list",
            allow_empty=False,
        )

    async def _type(self, box: Locator, text: str) -> None:
        """Type `text` key by key with uneven delays and the occasional thinking pause.

        Args:
            box: The focused input.
            text: What to type.
        """
        settings = self.settings
        for character in text:
            await box.press_sequentially(character, delay=random.randint(*settings.key_delay_ms))
            if random.random() < settings.pause_chance:
                await self._sleep(random.randint(*settings.pause_ms) / 1000)

    @staticmethod
    def _fingerprint(messages: list[Message]) -> list[Message]:
        """Give every message a fingerprint that stays the same from one read to the next.

        Args:
            messages: Messages as read from the page, oldest first.

        Returns:
            Copies of the messages with `fingerprint` set: the platform id when there is one,
            otherwise a hash of direction and text, numbered so that repeats ("ok", "ok")
            stay distinct.
        """
        seen: dict[str, int] = {}
        result = []
        for message in messages:
            if message.id:
                fingerprint = message.id
            else:
                key = f"{message.direction}|{message.text}"
                seen[key] = seen.get(key, 0) + 1
                fingerprint = hashlib.sha256(f"{key}|{seen[key]}".encode()).hexdigest()[:16]
            result.append(message.model_copy(update={"fingerprint": fingerprint}))
        return result
