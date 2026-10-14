"""Typed results returned by `KhojiPage`: links and scroll outcomes."""

from pydantic import BaseModel, ConfigDict


class Link(BaseModel):
    """One link on a page, as returned by `KhojiPage.links()`."""

    model_config = ConfigDict(frozen=True)

    url: str
    """Absolute URL, resolved by the browser against the page."""

    text: str
    """Visible text with whitespace collapsed; the aria-label or title when it has none."""

    title: str | None = None
    """The link's `title` attribute, if set."""

    rel: list[str] = []
    """Tokens of the `rel` attribute, e.g. ["nofollow", "noopener"]."""

    internal: bool
    """Whether the link points to the same host as the page."""


class ScrollResult(BaseModel):
    """What `KhojiPage.scroll_to_end()` did."""

    model_config = ConfigDict(frozen=True)

    rounds: int
    """Scroll steps taken. 0 means there was nothing to scroll."""

    height: int
    """Final scroll height, in pixels, of the element that was scrolled."""

    reached_end: bool
    """True if the bottom was reached and nothing more loaded; False if a limit stopped it."""
