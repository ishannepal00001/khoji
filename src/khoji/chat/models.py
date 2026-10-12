"""Data models shared by every chat site: session state, chats and messages."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class SessionState(StrEnum):
    """What a chat site's page is showing."""

    LOGGED_IN = "logged_in"
    """The chat list is visible."""

    LOGGED_OUT = "logged_out"
    """A login prompt (QR code, password form) is visible."""

    LOADING = "loading"
    """Neither is visible yet."""


class Chat(BaseModel):
    """One row of the chat list."""

    position: int
    """1-based position from the top, as displayed."""

    name: str
    """Contact or group name."""

    preview: str | None = None
    """Preview of the latest message, if the row shows one."""


class Message(BaseModel):
    """One message in the open thread."""

    id: str | None
    """The platform's own id for the message, or None if the markup had none."""

    direction: Literal["in", "out"]
    """"in" for a message they sent, "out" for one we sent."""

    text: str
    """Message text. Empty for non-text messages such as images."""

    meta: str | None = None
    """Extra details the platform shows with the message, such as time and sender, if any."""

    fingerprint: str = ""
    """Stable identity used to tell messages apart: the id, or a hash when there is none."""
