import pytest

from khoji import BlockedError, Khoji, KhojiConfig, KhojiError, NavigationError


async def test_http_403_raises_blocked(khoji: Khoji, server: str):
    with pytest.raises(BlockedError) as excinfo:
        await khoji.open(f"{server}/forbidden")
    assert excinfo.value.status == 403


async def test_stuck_challenge_raises_blocked(config: KhojiConfig, server: str):
    async with Khoji(config.model_copy(update={"challenge_wait_ms": 500})) as k:
        with pytest.raises(BlockedError, match="did not clear"):
            await k.open(f"{server}/challenge")


async def test_challenge_that_clears_is_not_a_block(khoji: Khoji, server: str):
    page = await khoji.open(f"{server}/clearing")
    assert await page.raw.title() == "Shop"


async def test_block_detection_can_be_disabled(config: KhojiConfig, server: str):
    async with Khoji(config.model_copy(update={"block_detection": False})) as k:
        page = await k.open(f"{server}/forbidden")
        assert "Forbidden" in await page.html()


async def test_failed_open_does_not_leak_tabs(khoji: Khoji, server: str):
    await khoji.open(f"{server}/products")
    before = len(khoji.context.pages)
    with pytest.raises(BlockedError):
        await khoji.open(f"{server}/forbidden")
    assert len(khoji.context.pages) == before


async def test_unreachable_host_raises_navigation_error(khoji: Khoji):
    with pytest.raises(NavigationError):
        await khoji.open("http://127.0.0.1:1/")


async def test_using_before_start_raises():
    with pytest.raises(KhojiError, match="not started"):
        await Khoji().new_page()


async def test_save_debug_writes_screenshot_and_html(khoji: Khoji, server: str, tmp_path):
    page = await khoji.open(f"{server}/products")
    stem = await page.save_debug(tmp_path / "dumps", "check")
    assert stem is not None
    assert stem.with_name(stem.name + ".png").stat().st_size > 0
    assert "Red widget" in stem.with_name(stem.name + ".html").read_text()
