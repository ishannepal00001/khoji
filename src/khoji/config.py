"""Browser configuration: validated, immutable settings passed to `Khoji`."""

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class ProxyConfig(BaseModel):
    """Proxy the browser routes its traffic through.

    When a proxy is used, set `KhojiConfig.locale` and `KhojiConfig.timezone_id` to its region.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    server: str
    """Proxy address, e.g. "http://host:8080" or "socks5://host:1080"."""

    username: str | None = None
    """Username for proxy authentication, if the proxy needs one."""

    password: SecretStr | None = None
    """Password for proxy authentication. Kept out of reprs and logs."""


class KhojiConfig(BaseModel):
    """Browser settings.

    User agent, headers and viewport are intentionally not configurable: overriding
    them makes the browser's fingerprint inconsistent, which is what detectors look for.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    @staticmethod
    def default_profile_dir() -> Path:
        """Return the default persistent profile directory.

        Follows the XDG base directory spec: `$XDG_DATA_HOME/khoji/profile`, falling back to
        `~/.local/share/khoji/profile` when the variable is unset or empty.

        Returns:
            The profile directory path. It is not created here.
        """
        data_home = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
        return Path(data_home) / "khoji" / "profile"

    headless: bool = False
    """Headless is the easiest thing for a site to detect; keep it off unless you must."""

    channel: str | None = None
    """Browser channel, e.g. "chrome" or "msedge". Defaults to Chrome when installed."""

    executable_path: Path | None = None
    """Explicit browser binary. Takes precedence over `channel`."""

    user_data_dir: Path = Field(default_factory=default_profile_dir)
    """Persistent profile directory. Only one running Khoji may use it at a time."""

    proxy: ProxyConfig | None = None
    """Proxy to route traffic through. None means a direct connection."""

    locale: str | None = None
    """Browser locale, e.g. "en-US". Defaults to the system locale."""

    timezone_id: str | None = None
    """IANA timezone, e.g. "Asia/Kathmandu". Defaults to the system timezone."""

    navigation_timeout_ms: int = Field(default=30_000, gt=0)
    """How long a navigation may take before it fails with NavigationError."""

    block_detection: bool = True
    """Raise BlockedError when a navigation lands on a block or challenge page."""

    challenge_wait_ms: int = Field(default=10_000, ge=0)
    """How long to wait for an anti-bot challenge to clear by itself before raising."""

    @field_validator("executable_path", "user_data_dir")
    @classmethod
    def _expand_user(cls, value: Path | None) -> Path | None:
        """Expand a leading `~` in path settings.

        Args:
            value: The path as given, or None when the setting is unset.

        Returns:
            The path with `~` replaced by the home directory, or None.
        """
        return value.expanduser() if value is not None else None
