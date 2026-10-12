from pathlib import Path

import pytest
from pydantic import ValidationError

from khoji import KhojiConfig, ProxyConfig
from khoji.browser import BrowserLauncher


def test_defaults():
    config = KhojiConfig()
    assert config.headless is False
    assert config.block_detection is True
    assert config.user_data_dir.parts[-2:] == ("khoji", "profile")


def test_profile_dir_follows_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert KhojiConfig().user_data_dir == tmp_path / "khoji" / "profile"


def test_tilde_in_paths_is_expanded():
    config = KhojiConfig(user_data_dir="~/profiles/shop")
    assert config.user_data_dir == Path.home() / "profiles" / "shop"


def test_unknown_option_rejected():
    # user_agent is deliberately not configurable.
    with pytest.raises(ValidationError):
        KhojiConfig(user_agent="Mozilla/5.0")


def test_invalid_timeout_rejected():
    with pytest.raises(ValidationError):
        KhojiConfig(navigation_timeout_ms=0)


def test_proxy_password_is_not_leaked_in_repr():
    proxy = ProxyConfig(server="http://proxy:8080", username="u", password="hunter2")
    assert "hunter2" not in repr(proxy)
    assert "hunter2" not in repr(KhojiConfig(proxy=proxy))


def test_launch_options_never_override_fingerprint(tmp_path):
    options = BrowserLauncher(KhojiConfig(user_data_dir=tmp_path)).launch_options()
    assert options["no_viewport"] is True
    assert options["headless"] is False
    assert not {"user_agent", "extra_http_headers", "viewport"} & options.keys()


def test_launch_options_pass_proxy_and_locale(tmp_path):
    config = KhojiConfig(
        user_data_dir=tmp_path,
        proxy=ProxyConfig(server="http://proxy:8080", username="u", password="hunter2"),
        locale="en-GB",
        timezone_id="Asia/Kathmandu",
    )
    options = BrowserLauncher(config).launch_options()
    assert options["proxy"] == {"server": "http://proxy:8080", "username": "u", "password": "hunter2"}
    assert options["locale"] == "en-GB"
    assert options["timezone_id"] == "Asia/Kathmandu"


def test_executable_path_wins_over_channel(tmp_path):
    config = KhojiConfig(user_data_dir=tmp_path, executable_path=Path("/usr/bin/chromium"), channel="chrome")
    options = BrowserLauncher(config).launch_options()
    assert options["executable_path"] == "/usr/bin/chromium"
    assert "channel" not in options
