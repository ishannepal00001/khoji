"""`Conversation`: the send, wait, reply loop over one open chat thread."""

import logging
import random
import time

from pydantic import BaseModel

from .models import Chat, Message
from .responder import Responder
from .site import ChatSite

log = logging.getLogger("khoji.chat")


class ConversationResult(BaseModel):
    """What happened during `Conversation.run`."""

    received: list[Message]
    """Every incoming message that arrived during the run, oldest first."""

    replies_sent: int
    """How many turns were answered through the responder."""

    timed_out: bool
    """True if the run ended because `wait_hours` passed, False if it ended after a reply."""


class Conversation:
    """Runs one conversation on a chat site whose thread is already open.

        await site.open_thread(chat)
        result = await Conversation(site, chat, responder=MyResponder()).run("Hello")

    Without a responder it sends the opening message (if any) and returns as soon as the
    other side answers. With one, it keeps answering until `max_replies` turns have been
    answered, then keeps listening without replying until the time limit.

    Attributes:
        site: The connected chat site.
        chat: The chat whose thread is open.
        responder: Decides what to answer, or None to only listen.
        max_replies: How many turns to answer before going quiet.
    """

    def __init__(
        self, site: ChatSite, chat: Chat, *, responder: Responder | None = None, max_replies: int = 1
    ) -> None:
        """Create a conversation.

        Args:
            site: A connected chat site with `chat`'s thread open.
            chat: The chat being talked to.
            responder: Decides what to answer. None means listen only.
            max_replies: How many turns to answer before going quiet.
        """
        self.site = site
        self.chat = chat
        self.responder = responder
        self.max_replies = max_replies

    async def run(self, opening: str | None = None, *, resume: bool = False) -> ConversationResult:
        """Send the opening message, then wait for replies and answer them.

        Args:
            opening: Text to send first. None to start by listening.
            resume: Treat messages they sent after our last message as still unanswered,
                for picking a conversation back up after a restart.

        Returns:
            What was received and how many turns were answered.

        Raises:
            SendUnconfirmedError: If a message could not be confirmed as sent.
            LoggedOutError: If the site logged the session out while waiting.
            ChatError: If the conversation was closed or would not settle.
        """
        site, settings = self.site, self.site.settings
        name = self.chat.name
        received: list[Message] = []
        replies_sent = 0
        # True when the thread's last outgoing message marks the start of the turn being
        # waited on, so that anything already below it is a reply and not old history.
        from_last_out = resume

        if opening is not None:
            sent = await site.send(opening)
            log.info("Sent to %s.", name)
            if sent.fingerprint == site.UNVERIFIED:
                # The message went out but the per-message selectors did not see it, so
                # replies would be missed too.
                log.warning("%s: message selectors did not match; see inspect().", site.name)
            else:
                from_last_out = True

        deadline = time.monotonic() + settings.wait_hours * 3600
        log.info("Waiting up to %g hours for %s to reply.", settings.wait_hours, name)
        while True:
            current = await site.messages(settled=True)
            after = self._seen(current, from_last_out=from_last_out)
            from_last_out = False
            incoming = await site.wait_for_reply(after, deadline)
            if not incoming:
                log.info("Stopped waiting: no new message from %s before the time limit.", name)
                return ConversationResult(received=received, replies_sent=replies_sent, timed_out=True)
            received.extend(incoming)
            log.info("%s sent %d message(s).", name, len(incoming))

            if self.responder is None:
                return ConversationResult(received=received, replies_sent=replies_sent, timed_out=False)
            if replies_sent >= self.max_replies:
                log.info("Reply limit of %d reached; still listening, not replying.", self.max_replies)
                continue
            # The whole burst is one turn and gets one answer.
            for text in await self.responder.reply(self.chat, await site.messages()):
                await site.page.raw.wait_for_timeout(random.uniform(*settings.reading_s) * 1000)
                sent = await site.send(text)
                log.info("Replied to %s.", name)
                # A reply can land while the send is still being confirmed; do not miss it.
                from_last_out = sent.fingerprint != site.UNVERIFIED
            replies_sent += 1

    @staticmethod
    def _seen(current: list[Message], *, from_last_out: bool) -> set[str]:
        """Work out which messages count as already seen at the start of a turn.

        Args:
            current: The thread as currently read, oldest first.
            from_last_out: Whether our last outgoing message marks the start of the turn:
                true right after we sent something, and when resuming a conversation.

        Returns:
            Fingerprints of the seen messages. Normally all of them. With `from_last_out`,
            only those up to our last outgoing message, so anything they sent after it is
            still unanswered. With none of our messages in view there is no turn boundary to
            trust, so everything counts as seen.
        """
        if from_last_out:
            last_out = max((i for i, m in enumerate(current) if m.direction == "out"), default=-1)
            if last_out >= 0:
                current = current[: last_out + 1]
        return {message.fingerprint for message in current}
