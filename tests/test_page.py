import asyncio

import pytest

from khoji import Khoji, KhojiError, Link, Site

# Short pauses keep the tests quick; they still leave the feed time to load a batch.
FAST = {"pause_ms": (200, 300)}


async def item_count(page) -> int:
    return await page.raw.locator(".item").count()


async def test_scroll_loads_every_batch(khoji: Khoji, server: str):
    page = await khoji.open(f"{server}/feed")
    assert await item_count(page) == 5

    result = await page.scroll_to_end(**FAST)

    assert await item_count(page) == 15
    assert result.reached_end
    assert result.rounds > 0
    assert result.height >= 15 * 200


async def test_scroll_returns_at_once_when_page_cannot_scroll(khoji: Khoji, server: str):
    page = await khoji.open(f"{server}/products")
    result = await page.scroll_to_end(**FAST)
    assert result.rounds == 0
    assert result.reached_end


async def test_scroll_finds_inner_container(khoji: Khoji, server: str):
    page = await khoji.open(f"{server}/inner-feed")
    result = await page.scroll_to_end(**FAST)
    assert await item_count(page) == 15
    assert result.reached_end
    assert result.rounds > 0


async def test_scroll_explicit_container(khoji: Khoji, server: str):
    page = await khoji.open(f"{server}/inner-feed?batches=2")
    result = await page.scroll_to_end(container="#feed", **FAST)
    assert await item_count(page) == 10
    assert result.reached_end


async def test_scroll_missing_container_raises(khoji: Khoji, server: str):
    page = await khoji.open(f"{server}/feed")
    with pytest.raises(KhojiError, match="#nope"):
        await page.scroll_to_end(container="#nope", **FAST)


async def test_scroll_stops_at_max_rounds(khoji: Khoji, server: str):
    page = await khoji.open(f"{server}/feed?batches=10")
    result = await page.scroll_to_end(max_rounds=1, **FAST)
    assert result.rounds == 1
    assert not result.reached_end


async def test_open_with_scroll(khoji: Khoji, server: str):
    page = await khoji.open(f"{server}/feed?batches=2", scroll=True)
    assert await item_count(page) == 10


async def test_site_open_with_scroll(khoji: Khoji, server: str):
    class Feed(Site):
        base_url = server

    page = await khoji.site(Feed).open("/feed?batches=2", scroll=True)
    assert await item_count(page) == 10


async def test_links(khoji: Khoji, server: str):
    page = await khoji.open(f"{server}/links")
    links = await page.links()

    assert links == [
        Link(url=f"{server}/about", text="About us", rel=["nofollow", "noopener"], internal=True),
        Link(url="https://example.org/x", text="Example", title="Elsewhere", internal=False),
        Link(url=f"{server}/docs", text="", internal=True),
        Link(url=f"{server}/icon", text="Settings", internal=True),
    ]


async def test_links_filters(khoji: Khoji, server: str):
    page = await khoji.open(f"{server}/links")

    assert [link.url for link in await page.links(internal=False)] == ["https://example.org/x"]
    assert len(await page.links(internal=True)) == 3
    assert [link.url for link in await page.links(root="main")] == [f"{server}/docs", f"{server}/icon"]
    mail = await page.links(schemes=("mailto",))
    assert [link.url for link in mail] == ["mailto:hi@example.com"]


async def test_links_include_scrolled_content(khoji: Khoji, server: str):
    page = await khoji.open(f"{server}/feed")
    assert len(await page.links()) == 5
    await page.scroll_to_end(**FAST)
    links = await page.links()
    assert len(links) == 15
    assert links[-1].url == f"{server}/item/14"


async def test_concurrent_opens_get_their_own_tabs(khoji: Khoji, server: str):
    paths = ["/products", "/links", "/feed"]
    pages = await asyncio.gather(*(khoji.open(f"{server}{path}") for path in paths))

    assert len({id(page.raw) for page in pages}) == len(paths)
    assert [page.url for page in pages] == [f"{server}{path}" for path in paths]


async def test_first_open_reuses_the_initial_blank_tab(khoji: Khoji, server: str):
    before = len(khoji.context.pages)
    await khoji.open(f"{server}/products")
    assert len(khoji.context.pages) == before
