"""`Responder`: decides what to answer in a conversation."""

from abc import ABC, abstractmethod

from .models import Chat, Message


class Responder(ABC):
    """The "brain" of a conversation. Knows nothing about the browser or the platform.

    Subclass it and return the texts to send:

        class Echo(Responder):
            async def reply(self, chat, messages):
                last = [m for m in messages if m.direction == "in"][-1]
                return [f"You said: {last.text}"]
    """

    @abstractmethod
    async def reply(self, chat: Chat, messages: list[Message]) -> list[str]:
        """Return the messages to send in answer to the conversation so far.

        Called once per turn, after the other side has finished a burst of messages.

        Args:
            chat: The chat being answered.
            messages: The conversation as currently rendered, oldest first, including our
                own earlier messages (`direction == "out"`).

        Returns:
            The texts to send, in order. Empty to stay silent this turn.
        """
