import os
import sys
from pathlib import Path
from typing import Any

from patchright.async_api import BrowserContext, Playwright

from .config import KhojiConfig


def _chrome_candidates() -> list[Path]:
    if sys.platform == "darwin":
        return [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
    if sys.platform == "win32":
        roots = (os.environ.get(v) for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"))
        return [Path(r) / "Google" / "Chrome" / "Application" / "chrome.exe" for r in roots if r]
    return [Path("/opt/google/chrome/chrome")]


def chrome_installed() -> bool:
    return any(path.exists() for path in _chrome_candidates())


def _browser_options(config: KhojiConfig) -> dict[str, Any]:
    if config.executable_path is not None:
        return {"executable_path": str(config.executable_path)}
    if config.channel is not None:
        return {"channel": config.channel}
    # Real Chrome has a far more common fingerprint than the bundled Chromium.
    if chrome_installed():
        return {"channel": "chrome"}
    return {}


def launch_options(config: KhojiConfig) -> dict[str, Any]:
    options: dict[str, Any] = {
        "user_data_dir": str(config.user_data_dir),
        "headless": config.headless,
        # A fixed viewport is an automation tell; let the window decide.
        "no_viewport": True,
        **_browser_options(config),
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


async def launch(playwright: Playwright, config: KhojiConfig) -> BrowserContext:
    config.user_data_dir.mkdir(parents=True, exist_ok=True)
    context = await playwright.chromium.launch_persistent_context(**launch_options(config))
    context.set_default_navigation_timeout(config.navigation_timeout_ms)
    return context
