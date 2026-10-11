class KhojiError(Exception):
    """Base class for every error khoji raises."""


class NavigationError(KhojiError):
    """The page could not be loaded (DNS failure, timeout, connection reset...)."""


class BlockedError(KhojiError):
    """The site answered with a block or an anti-bot challenge that did not clear."""

    def __init__(self, message: str, *, url: str, status: int | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.status = status


class ExtractionError(KhojiError):
    """The page content did not satisfy the requested model."""

    def __init__(self, message: str, *, url: str, model: type) -> None:
        super().__init__(message)
        self.url = url
        self.model = model
