# 2. Your first scrape

> **Level:** beginner · **Time:** 15 minutes · **Previous:** [Installation](01-installation.md) ·
> **Next:** [Core concepts](03-core-concepts.md)

In this tutorial you will scrape the book listing on
[books.toscrape.com](https://books.toscrape.com/), a site built for practising scraping. By the
end you will have a list of typed `Book` objects, and you will know the four steps every khoji
scrape follows:

1. **Describe** the data as a Pydantic model.
2. **Open** the page.
3. **Extract** models from it.
4. **Use** the validated objects.

## Step 1: look at the page

Open the site in your browser and inspect one book (right click → *Inspect*). Each book is an
`<article class="product_pod">`, and inside it:

```html
<article class="product_pod">
  <h3><a href="catalogue/a-light-in-the-attic_1000/index.html"
         title="A Light in the Attic">A Light in the ...</a></h3>
  <p class="price_color">£51.77</p>
  <p class="instock availability">In stock</p>
</article>
```

Note three things:

- The visible title is cut short; the **`title` attribute** has the full one.
- The price is text with a currency sign in front.
- Every book sits in the same kind of element, so we can extract **one model per `article`**.

## Step 2: describe the data

```python
from typing import Annotated

from pydantic import BaseModel

from khoji import Selector


class Book(BaseModel):
    title: Annotated[str, Selector("h3 a", attr="title")]
    price: Annotated[float, Selector(".price_color", pattern=r"\d[\d.]*")]
    in_stock: Annotated[str, Selector(".availability")]
```

Read each field as *"name: Annotated[type, where it is on the page]"*:

| Field | Selector | What happens |
|---|---|---|
| `title` | `h3 a`, `attr="title"` | Reads the `title` attribute instead of the text |
| `price` | `.price_color`, `pattern=...` | Takes the text `£51.77`, keeps the regex match `51.77`, Pydantic turns it into `51.77` (a float) |
| `in_stock` | `.availability` | Reads the element's visible text, trimmed |

Selectors are ordinary CSS. Inside `extract_all` they are resolved **relative to each
`article`**, so `h3 a` means "the `h3 a` inside this book".

## Step 3: open the page and extract

```python
import asyncio

from khoji import Khoji


async def main() -> None:
    async with Khoji() as k:
        page = await k.open("https://books.toscrape.com/")
        books = await page.extract_all(Book, root="article.product_pod")

    print(f"Found {len(books)} books")
    for book in books[:3]:
        print(f"{book.price:>6.2f}  {book.title}")


asyncio.run(main())
```

What each line does:

- `async with Khoji() as k` launches the browser and guarantees it is closed afterwards, even
  if something fails.
- `k.open(url)` opens a tab, loads the page and checks it was not blocked. It returns a
  `KhojiPage`.
- `page.extract_all(Book, root=...)` finds every element matching `root` and builds one `Book`
  from each.

Output:

```text
Found 20 books
 51.77  A Light in the Attic
 53.74  Tipping the Velvet
 50.10  Soumission
```

## Step 4: use the results

`books` is a plain `list[Book]`. Every item is validated, so `book.price` really is a `float`:

```python
cheap = [b for b in books if b.price < 20]
print(books[0].model_dump())  # {'title': 'A Light in the Attic', 'price': 51.77, ...}
print(books[0].model_dump_json())  # ready to write to a file or send to an API
```

## When something does not match

Change the price selector to something that does not exist, `Selector(".nope")`, and run again:

```text
khoji.errors.ExtractionError: Could not extract Book from https://books.toscrape.com/:
1 validation error for Book
price
  Field required [type=missing, ...]
```

A required field with no match fails loudly instead of quietly becoming `None`. To make a field
optional, give it a default:

```python
rating: Annotated[str | None, Selector(".star-rating", attr="class")] = None
```

## Bonus: more of the page

Two more things are worth trying now.

**Follow the links.** Every link on the page, as typed objects:

```python
for link in await page.links(internal=True):
    print(link.url, "-", link.text)
```

**Load lazy content.** On sites with infinite scrolling, pass `scroll=True` so the page is
scrolled to the end before you extract:

```python
page = await k.open("https://example.com/feed", scroll=True)
```

## What you learned

- A model with `Selector` metadata is the description of what to scrape.
- `k.open()` gives you a page; `extract()` gives one model, `extract_all()` gives many.
- Pydantic does the type conversion and rejects data that does not fit.

---

**Next:** [Core concepts →](03-core-concepts.md) explains the objects you just used.
