"""Chat layer: what a browser-driven chat site can do, independent of the platform.

`ChatSite` is the base class a platform subclasses (see `khoji.sites.WhatsApp`),
`Conversation` runs the send, wait, reply loop on top of it, and `Responder` decides what
to answer.
"""

from .conversation import Conversation, ConversationResult
from .models import Chat, Message, SessionState
from .responder import Responder
from .settings import ChatSettings
from .site import ChatSite

__all__ = [
    "Chat",
    "ChatSettings",
    "ChatSite",
    "Conversation",
    "ConversationResult",
    "Message",
    "Responder",
    "SessionState",
]
