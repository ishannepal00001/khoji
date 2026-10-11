from typing import Annotated

import pytest
from pydantic import BaseModel

from khoji import ExtractionError, Khoji, Selector, Site


class Seller(BaseModel):
    name: Annotated[str, Selector(".name")]
    rating: Annotated[float, Selector(".rating")]


class Card(BaseModel):
    name: Annotated[str, Selector("h2")]
    price: Annotated[float, Selector(".price", pattern=r"\d[\d.]*")]
    image: Annotated[str | None, Selector("img.hero", attr="src")] = None
    tags: Annotated[list[str], Selector(".tag")]
    seller: Annotated[Seller, Selector(".seller")]
    currency: Annotated[str, Selector(".currency")] = "NPR"
    note: str = "not scraped"


class Listing(BaseModel):
    title: Annotated[str, Selector("h1.title")]
    next_page: Annotated[str, Selector("a.more", attr="href")]
    page_number: Annotated[int, Selector("a.more", attr="href", pattern=r"/page/(\d+)")]
    cards: Annotated[list[Card], Selector(".card")]


class Stock(BaseModel):
    name: Annotated[str, Selector(".name")]
    warehouse: str


class Partial(BaseModel):
    name: Annotated[str, Selector("h2")]
    sku: str
    quantity: int
    note: str = "n/a"
    seller: Annotated[Stock, Selector(".seller")]


class NeedsMissing(BaseModel):
    sku: Annotated[str, Selector(".sku")]


async def test_extract_whole_page(khoji: Khoji, server: str):
    page = await khoji.open(f"{server}/products")
    listing = await page.extract(Listing)

    assert listing.title == "Widgets"
    assert listing.next_page == "/page/2"
    assert listing.page_number == 2
    assert [card.name for card in listing.cards] == ["Red widget", "Blue widget"]

    red, blue = listing.cards
    assert red.price == 1250.50
    assert red.image == "/img/red.png"
    assert red.tags == ["new", "sale"]
    assert red.seller == Seller(name="Acme", rating=4.5)
    assert blue.price == 80
    assert blue.image is None
    assert blue.tags == []


async def test_missing_element_falls_back_to_default(khoji: Khoji, server: str):
    page = await khoji.open(f"{server}/products")
    card = await page.extract(Card, root=".card")
    assert card.name == "Red widget"
    assert card.currency == "NPR"
    assert card.note == "not scraped"


async def test_extract_all_scopes_to_each_root(khoji: Khoji, server: str):
    page = await khoji.open(f"{server}/products")
    cards = await page.extract_all(Card, root=".card")
    assert [(card.name, card.seller.name) for card in cards] == [
        ("Red widget", "Acme"),
        ("Blue widget", "Globex"),
    ]


async def test_fields_without_a_selector_are_optional(khoji: Khoji, server: str):
    page = await khoji.open(f"{server}/products")
    item = await page.extract(Partial, root=".card")

    assert type(item) is Partial
    assert item.name == "Red widget"
    assert item.sku is None and item.quantity is None  # no selector, no default
    assert item.note == "n/a"  # no selector, default kept
    assert item.seller == Stock.model_construct(name="Acme", warehouse=None)  # nested too
    assert item.model_dump()["seller"] == {"name": "Acme", "warehouse": None}

    items = await page.extract_all(Partial, root=".card")
    assert [i.name for i in items] == ["Red widget", "Blue widget"]


async def test_selector_fields_are_still_validated(khoji: Khoji, server: str):
    class Bad(BaseModel):
        price: Annotated[float, Selector("h2")]
        sku: str

    page = await khoji.open(f"{server}/products")
    with pytest.raises(ExtractionError, match="price"):
        await page.extract(Bad, root=".card")


async def test_required_field_missing_raises(khoji: Khoji, server: str):
    page = await khoji.open(f"{server}/products")
    with pytest.raises(ExtractionError) as excinfo:
        await page.extract(NeedsMissing)
    assert excinfo.value.model is NeedsMissing
    assert excinfo.value.url.endswith("/products")
    assert "sku" in str(excinfo.value)


async def test_site_module(khoji: Khoji, server: str):
    class Shop(Site):
        base_url = server

        async def cards(self) -> list[Card]:
            page = await self.open("/products")
            return await page.extract_all(Card, root=".card")

    cards = await khoji.site(Shop).cards()
    assert len(cards) == 2
