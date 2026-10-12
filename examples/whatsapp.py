"""Read the latest messages of one WhatsApp chat and print them. Sends nothing.

    uv run python examples/whatsapp.py                    # top chat, last 30 messages
    uv run python examples/whatsapp.py --name "Alice"     # pick the chat by its exact name
    uv run python examples/whatsapp.py --position 3 --limit 10

The first run shows a QR code: scan it from your phone (Settings > Linked devices).
Opening a chat marks its messages as read.
"""

import argparse
import asyncio
import logging

from khoji import Khoji, KhojiError
from khoji.chat import Chat, Message
from khoji.sites import WhatsApp


class MessageReader:
    """Opens one WhatsApp chat and prints its latest messages.

    Attributes:
        name: Exact chat name to open, or None to go by position.
        position: 1-based position in the chat list, used when `name` is None.
        limit: How many of the latest messages to print.
    """

    def __init__(self, *, name: str | None, position: int, limit: int) -> None:
        """Create a reader.

        Args:
            name: Exact chat name to open, or None to go by position.
            position: 1-based position in the chat list, used when `name` is None.
            limit: How many of the latest messages to print.
        """
        self.name = name
        self.position = position
        self.limit = limit

    async def _pick(self, whatsapp: WhatsApp) -> Chat:
        """Choose the chat to open, by name if one was given, else by position.

        Args:
            whatsapp: The connected site.

        Returns:
            The chosen chat.

        Raises:
            ChatError: If the name does not match exactly one chat, or the position is not loaded.
        """
        if self.name is not None:
            return await whatsapp.find_chat(self.name)
        chats = await whatsapp.chats()
        if not 1 <= self.position <= len(chats):
            raise KhojiError(f"Only {len(chats)} chats are loaded; there is no chat #{self.position}.")
        return chats[self.position - 1]

    @staticmethod
    def _show(number: int, message: Message) -> None:
        """Print one message with everything that was read for it.

        Args:
            number: The message's place in the printed list, starting at 1.
            message: The message to print.
        """
        arrow = "->" if message.direction == "out" else "<-"
        print(f"{number:>3} {arrow} {message.direction:<3} {message.meta or '[no time/sender in markup]'}")
        print(f"       text: {message.text or '[non-text message]'}")
        print(f"       id:   {message.id}")

    async def run(self) -> int:
        """Connect, open the chat and print its latest messages.

        Returns:
            The process exit code: 0 on success, 1 on an error (debug files are saved).
        """
        async with Khoji() as k:
            whatsapp = k.site(WhatsApp)
            try:
                await whatsapp.connect()
                chat = await self._pick(whatsapp)
                await whatsapp.open_thread(chat)
                messages = await whatsapp.messages(settled=True)
                latest = messages[-self.limit :]
                print(f"Chat #{chat.position}: {chat.name}")
                print(f"{len(messages)} messages are rendered; showing the latest {len(latest)}.\n")
                for number, message in enumerate(latest, start=1):
                    self._show(number, message)
                incoming = sum(message.direction == "in" for message in latest)
                with_text = sum(bool(message.text) for message in latest)
                print(f"\n{incoming} incoming, {len(latest) - incoming} outgoing, {with_text} with text.")
                return 0
            except KhojiError as exc:
                await whatsapp.save_debug("error")
                print(f"Failed: {exc}")
                return 1
            finally:
                await whatsapp.close()


def main() -> None:
    """Parse the command line and run the reader.

    Raises:
        SystemExit: Always, carrying the exit code from `MessageReader.run`.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", help="open the chat with this exact name")
    parser.add_argument(
        "--position", type=int, default=1, help="which chat, counted from the top (default 1)"
    )
    parser.add_argument("--limit", type=int, default=30, help="how many of the latest messages (default 30)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    reader = MessageReader(name=args.name, position=args.position, limit=args.limit)
    raise SystemExit(asyncio.run(reader.run()))


if __name__ == "__main__":
    main()
