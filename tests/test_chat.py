import time
from collections.abc import Callable

import pytest
from patchright.async_api import Locator

from khoji import ChatError, Khoji, LoggedOutError, SendUnconfirmedError, Site
from khoji.chat import (
    Chat,
    ChatSettings,
    ChatSite,
    Conversation,
    Message,
    Responder,
    SessionState,
)
from khoji.sites import WhatsApp


class FakeChat(ChatSite):
    """The hooks for the fake chat app served by conftest; nothing here is WhatsApp-shaped."""

    name = "fakechat"

    async def _session_state(self) -> SessionState:
        page = self.page.raw
        if await page.locator(".chat").count():
            return SessionState.LOGGED_IN
        if await page.locator("#login").count():
            return SessionState.LOGGED_OUT
        return SessionState.LOADING

    async def _chat_rows(self) -> list[Locator]:
        return await self.page.raw.locator(".chat").all()

    async def _read_chat(self, row: Locator, position: int) -> Chat:
        return Chat(
            position=position,
            name=await row.locator(".name").inner_text(),
            preview=await row.locator(".preview").inner_text(),
        )

    def _composer(self) -> Locator:
        return self.page.raw.locator("#composer")

    async def _thread_is_open(self) -> bool:
        return bool(await self.page.raw.locator("#main:not([hidden])").count())

    async def _read_messages(self) -> list[Message]:
        rows = await self.page.raw.locator("#main:not([hidden]) .msg").all()
        return [
            Message(
                id=await row.get_attribute("data-id"),
                direction="out" if "out" in (await row.get_attribute("class") or "") else "in",
                text=await row.inner_text(),
            )
            for row in rows
        ]

    async def _thread_text(self) -> str:
        return await self.page.raw.locator("#panel").inner_text()


class Canned(Responder):
    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.calls = 0

    async def reply(self, chat: Chat, messages: list[Message]) -> list[str]:
        self.calls += 1
        return self.texts


@pytest.fixture
def settings(tmp_path) -> ChatSettings:
    return ChatSettings(
        login_timeout_s=3,
        login_poll_s=0.05,
        settle_interval_s=0.02,
        thread_settle_interval_s=0.02,
        key_delay_ms=(1, 2),
        pause_chance=0,
        pre_send_s=(0.01, 0.02),
        send_verify_s=3,
        poll_s=(0.05, 0.1),
        burst_s=(0.4, 0.5),
        reading_s=(0.01, 0.02),
        wait_hours=2 / 3600,
        debug_dir=tmp_path / "debug",
    )


@pytest.fixture
def fake(khoji: Khoji, server: str, settings: ChatSettings) -> Callable[..., FakeChat]:
    """Build a FakeChat bound to the test server; `query` selects the fake app's behaviour."""

    def build(query: str = "", **changes: object) -> FakeChat:
        bound = type("BoundFakeChat", (FakeChat,), {"base_url": server, "home_path": f"/chat{query}"})
        return khoji.site(bound, settings=settings.model_copy(update=changes))

    return build


async def opened(site: FakeChat, name: str = "Alice") -> Chat:
    await site.connect()
    chat = await site.find_chat(name)
    await site.open_thread(chat)
    return chat


# ----- structure


def test_chat_site_is_a_site_and_abstract(khoji: Khoji):
    assert issubclass(ChatSite, Site)
    assert issubclass(WhatsApp, ChatSite)
    with pytest.raises(TypeError):
        ChatSite(khoji)


async def test_using_before_connect_raises(fake):
    with pytest.raises(ChatError, match="not connected"):
        await fake().chats()


# ----- session


async def test_connect_waits_for_a_late_login(fake):
    async with fake("?login=late") as site:
        assert [chat.name for chat in await site.chats()] == ["Alice", "Bob", "Carol"]


async def test_connect_times_out_when_never_logged_in(khoji: Khoji, fake):
    site = fake("?login=never", login_timeout_s=0.3)
    before = len(khoji.context.pages)
    with pytest.raises(LoggedOutError):
        await site.connect()
    assert len(khoji.context.pages) <= before


# ----- chat list


async def test_chats_are_listed_in_order_with_positions(fake):
    async with fake() as site:
        chats = await site.chats()
    assert [(chat.position, chat.name) for chat in chats] == [(1, "Alice"), (2, "Bob"), (3, "Carol")]
    assert chats[0].preview == "last message"


async def test_find_chat_needs_exactly_one_match(fake):
    async with fake("?dupes=1") as site:
        assert (await site.find_chat("Alice")).position == 1
        with pytest.raises(ChatError, match="found 2"):
            await site.find_chat("Bob")
        with pytest.raises(ChatError, match="found 0"):
            await site.find_chat("Nobody")


async def test_open_thread_refuses_a_chat_that_moved(fake):
    async with fake() as site:
        alice = await site.find_chat("Alice")
        await site.page.raw.evaluate("fake.rename(0, 'Zed')", isolated_context=False)
        with pytest.raises(ChatError, match="changed from 'Alice' to 'Zed'"):
            await site.open_thread(alice)
        with pytest.raises(ChatError, match="no chat #9"):
            await site.open_thread(Chat(position=9, name="Alice"))


# ----- thread


async def test_messages_are_read_with_stable_fingerprints(fake):
    async with fake() as site:
        await opened(site)
        first = await site.messages(settled=True)
        second = await site.messages()
    assert [(m.direction, m.text) for m in first] == [("in", "hi from Alice")]
    assert [m.fingerprint for m in first] == [m.fingerprint for m in second] == ["m1"]


def test_fingerprints_without_ids_keep_repeats_distinct():
    raw = [Message(id=None, direction="in", text="ok"), Message(id=None, direction="in", text="ok")]
    once = ChatSite._fingerprint(raw)
    assert once[0].fingerprint != once[1].fingerprint
    assert [m.fingerprint for m in once] == [m.fingerprint for m in ChatSite._fingerprint(raw)]


def test_new_incoming_only_counts_messages_below_the_known_ones():
    def message(fingerprint: str, direction: str) -> Message:
        return Message(id=fingerprint, direction=direction, text=fingerprint, fingerprint=fingerprint)

    thread = [message("old", "in"), message("a", "out"), message("b", "in"), message("c", "out")]
    assert [m.id for m in ChatSite.new_incoming(thread, {"a"})] == ["b"]
    assert ChatSite.new_incoming(thread, {"a", "b", "c"}) == []
    # History loaded above the known messages is not a reply.
    assert ChatSite.new_incoming(thread, {"b", "c"}) == []
    # None of the known messages are in view: the thread is re-rendering.
    assert ChatSite.new_incoming(thread, {"gone"}) == []
    assert [m.id for m in ChatSite.new_incoming(thread, set())] == ["old", "b"]


async def test_send_returns_the_confirmed_message(fake):
    async with fake() as site:
        await opened(site)
        sent = await site.send("hello\nthere")
        thread = await site.messages()
    assert (sent.direction, sent.text) == ("out", "hello there")
    assert sent.fingerprint == thread[-1].fingerprint != ChatSite.UNVERIFIED


async def test_send_that_never_appears_is_unconfirmed(fake):
    async with fake("?send=swallow", send_verify_s=1) as site:
        await opened(site)
        with pytest.raises(SendUnconfirmedError):
            await site.send("hello")


async def test_wait_for_reply_returns_the_whole_burst(fake):
    async with fake() as site:
        await opened(site)
        after = {m.fingerprint for m in await site.messages()}
        await site.page.raw.evaluate("fake.replyLater(2, 150)", isolated_context=False)
        replies = await site.wait_for_reply(after, time.monotonic() + 5)
    assert [m.text for m in replies] == ["burst 0", "burst 1"]


async def test_wait_for_reply_gives_up_at_the_deadline(fake):
    async with fake() as site:
        await opened(site)
        after = {m.fingerprint for m in await site.messages()}
        assert await site.wait_for_reply(after, time.monotonic() + 0.3) == []


async def test_wait_for_reply_notices_a_closed_thread_and_a_logout(fake):
    async with fake() as site:
        await opened(site)
        await site.page.raw.evaluate("fake.closeThread()", isolated_context=False)
        with pytest.raises(ChatError, match="no longer open"):
            await site.wait_for_reply(set(), time.monotonic() + 5)
        await site.page.raw.evaluate("fake.logout()", isolated_context=False)
        with pytest.raises(LoggedOutError):
            await site.wait_for_reply(set(), time.monotonic() + 5)


async def test_save_debug_writes_into_the_sites_folder(fake, settings: ChatSettings):
    async with fake() as site:
        stem = await site.save_debug("check")
    assert stem is not None and stem.parent == settings.debug_dir / "fakechat"
    assert stem.with_name(stem.name + ".png").exists()
    assert "Fake chat" in stem.with_name(stem.name + ".html").read_text()


# ----- conversation


async def test_conversation_without_responder_returns_on_the_first_reply(fake):
    async with fake("?replyto=ping") as site:
        chat = await opened(site)
        result = await Conversation(site, chat).run("ping")
    assert [m.text for m in result.received] == ["reply to ping"]
    assert (result.replies_sent, result.timed_out) == (0, False)


async def test_conversation_times_out_when_nobody_answers(fake):
    async with fake(wait_hours=0.5 / 3600) as site:
        chat = await opened(site)
        result = await Conversation(site, chat, responder=Canned("pong")).run()
    assert (result.received, result.replies_sent, result.timed_out) == ([], 0, True)


async def test_conversation_answers_each_turn_up_to_the_limit(fake):
    # Every "ping" we send gets a reply, and the responder answers with another "ping".
    responder = Canned("ping")
    async with fake("?replyto=ping", wait_hours=4 / 3600) as site:
        chat = await opened(site)
        result = await Conversation(site, chat, responder=responder, max_replies=2).run("ping")
        outgoing = [m.text for m in await site.messages() if m.direction == "out"]
    assert result.replies_sent == responder.calls == 2
    assert outgoing == ["ping", "ping", "ping"]
    assert len(result.received) == 3 and result.timed_out


def test_resume_treats_messages_after_our_last_one_as_unanswered():
    def message(fingerprint: str, direction: str) -> Message:
        return Message(id=fingerprint, direction=direction, text=fingerprint, fingerprint=fingerprint)

    thread = [message("a", "in"), message("b", "out"), message("c", "in")]
    assert Conversation._seen(thread, from_last_out=False) == {"a", "b", "c"}
    assert Conversation._seen(thread, from_last_out=True) == {"a", "b"}
    # None of our messages in view: no turn boundary to trust, so nothing is unanswered.
    only_theirs = [message("a", "in"), message("c", "in")]
    assert Conversation._seen(only_theirs, from_last_out=True) == {"a", "c"}
