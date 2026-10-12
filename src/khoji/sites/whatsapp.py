"""`WhatsApp`: WhatsApp Web as a chat site."""

from typing import Any, ClassVar

from patchright.async_api import Locator

from ..chat.models import Chat, Message, SessionState
from ..chat.site import ChatSite


class WhatsApp(ChatSite):
    """WhatsApp Web. Holds only what is specific to its markup; behaviour is in `ChatSite`.

    The first run shows a QR code: scan it from the phone (Settings > Linked devices).
    Khoji's persistent profile keeps the session afterwards.

    Every selector is a constant on this class and nowhere else. WhatsApp changes its markup
    without notice, so when something breaks, call `inspect()` on an open thread and fix the
    constants below.

    Checked against the live page: CHAT_ROWS, CHAT_NAME, COMPOSER, MESSAGE_PANEL, and the
    message rows ([data-id] inside the panel). Not yet seen live: QR_CODE, and the direction
    of an incoming message (tail-in icon / left alignment).
    """

    name = "whatsapp"
    base_url = "https://web.whatsapp.com"

    CHAT_ROWS: ClassVar[str] = "#pane-side [role='listitem'], #pane-side [role='row']"
    """One row of the chat list in the left pane."""

    CHAT_NAME: ClassVar[str] = "span[title]"
    """Relative to a chat row: the spans whose `title` holds the name, then the preview."""

    QR_CODE: ClassVar[str] = "canvas[aria-label*='QR' i], canvas[aria-label*='Scan' i], [data-ref] canvas"
    """The login QR code, present only while logged out."""

    THREAD: ClassVar[str] = "#main"
    """The open conversation pane."""

    COMPOSER: ClassVar[str] = (
        "#main [data-testid='conversation-compose-box-input'], #main footer [contenteditable='true']"
    )
    """The message input box of the open conversation."""

    MESSAGE_PANEL: ClassVar[str] = "#main [data-testid='conversation-panel-messages']"
    """The scrolling panel that holds the open conversation's messages."""

    READ_MESSAGES_JS: ClassVar[str] = """
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
    // "[10:32, 12/10/2026] Alice: " on text messages; absent on media and system rows.
    const stamped = row.querySelector('[data-pre-plain-text]');
    const meta = stamped ? stamped.getAttribute('data-pre-plain-text').trim() : null;
    return {id: row.getAttribute('data-id'), direction, text, meta};
  });
}
"""
    """Runs in the page. One call gives a consistent snapshot of the open thread."""

    INSPECT_JS: ClassVar[str] = """
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
    """Runs in the page. Structure only: attribute names and text lengths, never message text."""

    async def _session_state(self) -> SessionState:
        """Report whether the page shows the chat list, the QR code, or neither yet."""
        page = self.page.raw
        if await page.locator(self.CHAT_ROWS).count():
            return SessionState.LOGGED_IN
        if await page.locator(self.QR_CODE).count():
            return SessionState.LOGGED_OUT
        return SessionState.LOADING

    async def _chat_rows(self) -> list[Locator]:
        """Read the chat rows once, ordered by where they sit on screen.

        The list is virtualized, so DOM order is not screen order; rows are sorted by their
        vertical position instead. Rows without a bounding box are not rendered and are skipped.
        """
        rows = await self.page.raw.locator(self.CHAT_ROWS).all()
        placed = [(box["y"], row) for row in rows if (box := await row.bounding_box())]
        return [row for _, row in sorted(placed, key=lambda item: item[0])]

    async def _read_chat(self, row: Locator, position: int) -> Chat:
        """Build a `Chat` from a row: the first titled span is the name, the second the preview.

        Args:
            row: A chat row locator.
            position: The row's 1-based position from the top.
        """
        titles = await row.locator(self.CHAT_NAME).all()
        name = await titles[0].get_attribute("title") if titles else None
        preview = await titles[1].get_attribute("title") if len(titles) > 1 else None
        return Chat(position=position, name=name or "", preview=preview)

    def _composer(self) -> Locator:
        """Return the locator of the open conversation's message input."""
        return self.page.raw.locator(self.COMPOSER).first

    async def _thread_is_open(self) -> bool:
        """Report whether the conversation pane is present."""
        return bool(await self.page.raw.locator(self.THREAD).count())

    async def _read_messages(self) -> list[Message]:
        """Read the rendered messages of the open thread in one in-page call, oldest first."""
        return [Message(**raw) for raw in await self.page.raw.evaluate(self.READ_MESSAGES_JS)]

    async def _thread_text(self) -> str:
        """Return the visible text of the message panel only, not the chat list beside it."""
        return await self.page.raw.locator(self.MESSAGE_PANEL).first.inner_text()

    async def inspect(self) -> dict[str, Any]:
        """Describe the open thread's markup: test ids, roles, icons and text lengths.

        Returns:
            A structure-only summary; it contains no message text.
        """
        return await self.page.raw.evaluate(self.INSPECT_JS)
