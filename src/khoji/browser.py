"""`BrowserLauncher`: turns a `KhojiConfig` into a running persistent browser context."""

import os
import sys
from pathlib import Path
from typing import Any

from patchright.async_api import BrowserContext, Playwright

from .config import KhojiConfig


class BrowserLauncher:
    """Launches the stealth browser described by a `KhojiConfig`.

    Attributes:
        config: The browser settings used for every launch.
    """

    def __init__(self, config: KhojiConfig) -> None:
        """Create a launcher.

        Args:
            config: The browser settings.
        """
        self.config = config

    @staticmethod
    def _chrome_candidates() -> list[Path]:
        """List the paths where Google Chrome is normally installed on this platform.

        Returns:
            Candidate executable paths. They are not checked for existence.
        """
        if sys.platform == "darwin":
            return [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
        if sys.platform == "win32":
            roots = (os.environ.get(v) for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"))
            return [Path(r) / "Google" / "Chrome" / "Application" / "chrome.exe" for r in roots if r]
        return [Path("/opt/google/chrome/chrome")]

    @classmethod
    def chrome_installed(cls) -> bool:
        """Report whether Google Chrome is installed in one of its standard locations.

        Returns:
            True if any candidate path exists.
        """
        return any(path.exists() for path in cls._chrome_candidates())

    def _browser_options(self) -> dict[str, Any]:
        """Choose which browser binary to launch.

        Precedence: an explicit `executable_path`, then an explicit `channel`, then Google Chrome
        if it is installed, and finally Patchright's bundled Chromium.

        Returns:
            The launch options that select the binary; empty for the bundled Chromium.
        """
        if self.config.executable_path is not None:
            return {"executable_path": str(self.config.executable_path)}
        if self.config.channel is not None:
            return {"channel": self.config.channel}
        # Real Chrome has a far more common fingerprint than the bundled Chromium.
        if self.chrome_installed():
            return {"channel": "chrome"}
        return {}

    def launch_options(self) -> dict[str, Any]:
        """Build the keyword arguments for `launch_persistent_context`.

        User agent, headers and viewport are never set, so the browser keeps a consistent
        fingerprint.

        Returns:
            Launch options: profile directory, headless flag, browser choice, and the proxy,
            locale and timezone when they are configured.
        """
        config = self.config
        options: dict[str, Any] = {
            "user_data_dir": str(config.user_data_dir),
            "headless": config.headless,
            # A fixed viewport is an automation tell; let the window decide.
            "no_viewport": True,
            **self._browser_options(),
        }
        if config.proxy is not None:
            proxy: dict[str, str] = {"server": config.proxy.server}
            if config.proxy.username is not None:
                proxy["username"] = config.proxy.username
            if config.proxy.password is not None:
                proxy["password"] = config.proxy.password.get_secret_value()
            options["proxy"] = proxy
        if config.locale is not None:
            options["locale"] = config.locale
        if config.timezone_id is not None:
            options["timezone_id"] = config.timezone_id
        return options

    async def launch(self, playwright: Playwright) -> BrowserContext:
        """Launch the browser with a persistent profile.

        Creates the profile directory if it does not exist.

        Args:
            playwright: A started Patchright instance.

        Returns:
            The browser context, with the configured navigation timeout applied.
        """
        self.config.user_data_dir.mkdir(parents=True, exist_ok=True)
        context = await playwright.chromium.launch_persistent_context(**self.launch_options())
        context.set_default_navigation_timeout(self.config.navigation_timeout_ms)
        return context
