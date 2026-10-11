"""Search Google and print the organic results.

uv run python examples/google.py "playwright python"
"""

import asyncio
import sys
from typing import Annotated
from urllib.parse import urljoin

from pydantic import BaseModel, field_validator

from khoji import BlockedError, Khoji, Selector, Site


class Result(BaseModel):
    title: Annotated[str, Selector("h3")]
    # The breadcrumb reads "https://example.com › docs"; keep the URL at the front.
    site: Annotated[str | None, Selector("cite", pattern=r"^https?://\S+")] = None
    # Google no longer puts the destination in the markup: the href is its own redirect link.
    link: Annotated[str, Selector(":scope", attr="href")]

    @field_validator("link")
    @classmethod
    def _absolute(cls, value: str) -> str:
        return urljoin(Google.base_url, value)


class Google(Site):
    base_url = "https://www.google.com"

    async def search(self, query: str) -> list[Result]:
        page = await self.open("/")
        try:
            # Typing into the box like a person is far less suspicious than opening /search?q=...
            box = page.raw.locator("textarea[name=q], input[name=q]").first
            await box.click()
            await box.press_sequentially(query, delay=60)
            await box.press("Enter")
            await page.raw.wait_for_url("**/search**")
            if "/sorry/" in page.url:
                raise BlockedError("Google asked for a CAPTCHA", url=page.url, status=429)
            await page.raw.locator("#search a:has(h3)").first.wait_for()
            # Each organic result is a link wrapping its <h3> title.
            return await page.extract_all(Result, root="#search a:has(h3)")
        finally:
            await page.close()


async def main() -> None:
    query = " ".join(sys.argv[1:]) or "playwright python"
    async with Khoji() as k:
        results = await k.site(Google).search(query)

    for index, result in enumerate(results, start=1):
        print(f"{index:>2}. {result.title}\n    {result.site}")


if __name__ == "__main__":
    asyncio.run(main())
