# Extracting data

> **Level:** beginner → intermediate · **Prerequisites:** [Your first scrape](../getting-started/02-first-scrape.md)

khoji extracts data by reading `Selector` metadata from a Pydantic model. This guide covers every
option and how each kind of field is read.

- [The `Selector`](#the-selector)
- [Field shapes](#field-shapes)
- [`extract` and `extract_all`](#extract-and-extract_all)
- [Missing data and defaults](#missing-data-and-defaults)
- [Fields without a selector](#fields-without-a-selector)
- [Validation and type conversion](#validation-and-type-conversion)
- [Patterns that come up often](#patterns-that-come-up-often)

## The `Selector`

```python
Selector(css, *, attr=None, pattern=None, all=None)
```

| Argument | Type | Meaning |
|---|---|---|
| `css` | `str` | CSS selector. Resolved against the page, or against the parent element in nested models and `extract_all` |
| `attr` | `str \| None` | Read this attribute instead of the element's text |
| `pattern` | `str \| None` | Regex applied to the value. Keeps group 1 if the pattern has a group, else the whole match |
| `all` | `bool \| None` | Collect every match. Normally inferred from the field's type |

Attach it with `typing.Annotated`:

```python
from typing import Annotated
from pydantic import BaseModel
from khoji import Selector


class Article(BaseModel):
    headline: Annotated[str, Selector("h1")]
```

### How a value is read

For each match, khoji:

1. Takes the element's **visible text** (`innerText`, stripped of surrounding whitespace), or the
   attribute named by `attr`.
2. If `pattern` is set, runs `re.search`. No match → the value is treated as missing.
3. Hands the result to Pydantic for conversion to the field's type.

```python
# <span class="price">Rs. 1250.50 only</span>
price: Annotated[float, Selector(".price", pattern=r"\d[\d.]*")]  # 1250.5

# <a class="more" href="/page/2">More</a>
next_page: Annotated[int, Selector("a.more", attr="href", pattern=r"/page/(\d+)")]  # 2
```

> **Note:** `innerText` is what a person sees: hidden elements contribute nothing and line breaks
> follow the layout. If you need the raw DOM text of hidden elements, read it through `page.raw`
> (`locator.text_content()`).

## Field shapes

The field's type decides how many matches are read and what is built from them.

| Field type | Reads | Result |
|---|---|---|
| `str`, `int`, `float`, ... | First match | One value |
| `list[str]` (also `tuple`, `set`, `frozenset`) | Every match | One value per match; matches whose value is missing are dropped |
| `SomeModel` | First match | A nested model, with its selectors scoped to that element |
| `list[SomeModel]` | Every match | One nested model per match |
| `X \| None` | Same as `X` | `None` allowed when there is no match and a default is given |

### Lists

```python
tags: Annotated[list[str], Selector(".tag")]
# <span class="tag">new</span><span class="tag">sale</span>  ->  ["new", "sale"]
```

No matches gives an empty list.

### Nested models

A nested model's selectors are resolved **inside** the element its own selector matched:

```python
class Seller(BaseModel):
    name: Annotated[str, Selector(".name")]
    rating: Annotated[float, Selector(".rating")]


class Card(BaseModel):
    title: Annotated[str, Selector("h2")]
    seller: Annotated[Seller, Selector(".seller")]  # .name and .rating are looked up inside .seller


class Listing(BaseModel):
    heading: Annotated[str, Selector("h1")]
    cards: Annotated[list[Card], Selector(".card")]  # one Card per .card
```

You can nest as deep as the page goes. This is how you scrape a whole page into one object.

### Forcing `all`

`all` overrides the type-based guess. The main use is collecting every match into a field that is
not a list, then combining the matches in a `mode="before"` validator:

```python
from pydantic import field_validator


class Post(BaseModel):
    body: Annotated[str, Selector("article p", all=True)]  # every paragraph...

    @field_validator("body", mode="before")
    @classmethod
    def join(cls, paragraphs: list[str]) -> str:
        return "\n\n".join(paragraphs)  # ...joined into one string
```

## `extract` and `extract_all`

```python
item = await page.extract(Model)  # whole page
item = await page.extract(Model, root=".product")  # first .product only
items = await page.extract_all(Model, root=".card")  # one per .card
```

| | `extract` | `extract_all` |
|---|---|---|
| Returns | One model | `list[Model]`, in document order |
| `root` | Optional; scopes to the first match | Required; one model per match |
| Nothing matches `root` | Selectors run against an empty scope; required fields fail | Returns `[]` |
| One element does not fit | `ExtractionError` | `ExtractionError` (the whole call fails) |

Choose `extract` with a `list[...]` field when you also want page-level data (a heading, a "next"
link) alongside the items. Choose `extract_all` when you only want the items.

## Missing data and defaults

| Field | No match on the page |
|---|---|
| `x: Annotated[str, Selector(...)]` | `ExtractionError` — "Field required" |
| `x: Annotated[str, Selector(...)] = "n/a"` | `"n/a"` |
| `x: Annotated[str \| None, Selector(...)] = None` | `None` |
| `x: Annotated[list[str], Selector(...)]` | `[]` |

A missing attribute and a pattern that does not match both count as "no match", so the default
applies there too.

## Fields without a selector

A field with no `Selector` has no source on the page. It is never scraped:

- If it has a default, the default is used.
- If it is required, it becomes `None` instead of failing.

This lets you reuse one model both for scraping and for data you fill in later:

```python
class Stock(BaseModel):
    name: Annotated[str, Selector(".name")]
    warehouse: str  # filled in later; None after extraction


stock = await page.extract(Stock)
stock = stock.model_copy(update={"warehouse": "KTM-1"})
```

The object you get back is always an instance of **your** class.

## Validation and type conversion

Pydantic validates the extracted data, so all its features apply:

```python
from datetime import date
from pydantic import Field, HttpUrl, field_validator


class Event(BaseModel):
    title: Annotated[str, Selector("h1")]
    day: Annotated[date, Selector("time", attr="datetime")]  # "2026-10-14" -> date
    seats: Annotated[int, Selector(".seats", pattern=r"\d+"), Field(ge=0)]
    page: Annotated[HttpUrl, Selector("link[rel=canonical]", attr="href")]

    @field_validator("title")
    @classmethod
    def tidy(cls, value: str) -> str:
        return value.title()
```

If anything fails, `ExtractionError` carries the full Pydantic message, the `url` and the `model`.

## Patterns that come up often

**Prices with thousands separators** — strip in a validator:

```python
price: Annotated[float, Selector(".price", pattern=r"[\d,]+\.?\d*")]


@field_validator("price", mode="before")
@classmethod
def no_commas(cls, value: str) -> str:
    return value.replace(",", "")
```

**Absolute URLs from relative `href`s** — `page.links()` already gives absolute URLs. With a
selector, resolve against the page URL:

```python
from urllib.parse import urljoin

card = await page.extract(Card)
url = urljoin(page.url, card.href)
```

**Data inside JSON-LD** — `<script>` content is not visible text, so `Selector` cannot read it.
Read it through `page.raw` and validate it with an ordinary model:

```python
import json

raw = await page.raw.locator("script[type='application/ld+json']").first.text_content()
product = ProductLd.model_validate(json.loads(raw))
```

**Content that appears after scrolling** — scroll first, then extract. See
[Scrolling](scrolling.md).

---

**Related:** [Scrolling](scrolling.md) · [Collecting links](links.md) · [API reference](../reference/api.md#extraction)
