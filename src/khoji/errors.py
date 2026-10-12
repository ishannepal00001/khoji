"""Exceptions raised by khoji.

Every error inherits from `KhojiError`, so a single `except KhojiError` catches them all.
"""


class KhojiError(Exception):
    """Base class for every error khoji raises."""


class NavigationError(KhojiError):
    """The page could not be loaded (DNS failure, timeout, connection reset...)."""


class BlockedError(KhojiError):
    """The site answered with a block or an anti-bot challenge that did not clear.

    Attributes:
        url: The URL that was being opened.
        status: HTTP status of the response, or None when there was no response.
    """

    def __init__(self, message: str, *, url: str, status: int | None = None) -> None:
        """Create the error.

        Args:
            message: Human-readable description of the block.
            url: The URL that was being opened.
            status: HTTP status of the response, if there was one.
        """
        super().__init__(message)
        self.url = url
        self.status = status


class ExtractionError(KhojiError):
    """The page content did not satisfy the requested model.

    Attributes:
        url: The URL of the page that was being extracted.
        model: The model class that could not be built.
    """

    def __init__(self, message: str, *, url: str, model: type) -> None:
        """Create the error.

        Args:
            message: Human-readable description, including the validation errors.
            url: The URL of the page that was being extracted.
            model: The model class that could not be built.
        """
        super().__init__(message)
        self.url = url
        self.model = model


class ChatError(KhojiError):
    """A chat site could not do what was asked: no such chat, an unstable list, a closed thread."""


class LoggedOutError(ChatError):
    """The chat site is not logged in, or logged the session out while it was in use."""


class SendUnconfirmedError(ChatError):
    """A message was typed and submitted but never showed up in the thread.

    It may still have been sent, so check the conversation before sending it again.
    """
