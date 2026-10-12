"""`ChatSettings`: timings and paths used by every chat site."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict


class ChatSettings(BaseModel):
    """Timings and paths for a chat site. Ranges are (min, max) and a value is drawn at random.

    The randomised delays are what make typing and polling look like a person rather than a
    script, so shorten them with care.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    login_timeout_s: float = 180
    """How long to wait for the user to log in (for example, to scan a QR code)."""

    login_poll_s: float = 1.0
    """Gap between checks while waiting for the login."""

    settle_interval_s: float = 1.0
    """Gap between two reads when waiting for the chat list to stop changing."""

    thread_settle_interval_s: float = 1.5
    """Gap between two reads when waiting for the open thread to stop changing."""

    settle_attempts: int = 20
    """How many reads to try before giving up on something that keeps changing."""

    key_delay_ms: tuple[int, int] = (45, 140)
    """Per-key typing delay range."""

    pause_chance: float = 0.06
    """Chance of a short thinking pause after any key."""

    pause_ms: tuple[int, int] = (300, 900)
    """Length of a thinking pause."""

    pre_send_s: tuple[float, float] = (1.0, 2.5)
    """Pause between focusing the composer and typing the first key."""

    send_verify_s: float = 20
    """How long to wait for a sent message to show up in the thread."""

    poll_s: tuple[float, float] = (5, 15)
    """Randomized gap between checks for a reply."""

    burst_s: tuple[float, float] = (4, 8)
    """After a reply arrives, wait this long for follow-up messages before reporting."""

    reading_s: tuple[float, float] = (3, 8)
    """Pause before answering, as if reading the incoming message."""

    wait_hours: float = 12
    """How long a conversation keeps waiting for a reply before stopping."""

    debug_dir: Path = Path("debug")
    """Where debug dumps are saved; each site uses a subfolder named after itself."""
