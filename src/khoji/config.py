import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


def default_profile_dir() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(data_home) / "khoji" / "profile"


class ProxyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    server: str
    username: str | None = None
    password: SecretStr | None = None


class KhojiConfig(BaseModel):
    """Browser settings.

    User agent, headers and viewport are intentionally not configurable: overriding
    them makes the browser's fingerprint inconsistent, which is what detectors look for.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    headless: bool = False
    """Headless is the easiest thing for a site to detect; keep it off unless you must."""

    channel: str | None = None
    """Browser channel, e.g. "chrome" or "msedge". Defaults to Chrome when installed."""

    executable_path: Path | None = None
    """Explicit browser binary. Takes precedence over `channel`."""

    user_data_dir: Path = Field(default_factory=default_profile_dir)
    """Persistent profile directory. Only one running Khoji may use it at a time."""

    proxy: ProxyConfig | None = None
    locale: str | None = None
    timezone_id: str | None = None

    navigation_timeout_ms: int = Field(default=30_000, gt=0)

    block_detection: bool = True
    """Raise BlockedError when a navigation lands on a block or challenge page."""

    challenge_wait_ms: int = Field(default=10_000, ge=0)
    """How long to wait for an anti-bot challenge to clear by itself before raising."""

    @field_validator("executable_path", "user_data_dir")
    @classmethod
    def _expand_user(cls, value: Path | None) -> Path | None:
        return value.expanduser() if value is not None else None
