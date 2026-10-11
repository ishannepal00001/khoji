import re
import types
from dataclasses import KW_ONLY, dataclass
from typing import Any, Union, get_args, get_origin

from patchright.async_api import Locator, Page
from pydantic import BaseModel, ValidationError

from .errors import ExtractionError

_COLLECTIONS = (list, tuple, set, frozenset)


@dataclass(frozen=True, slots=True)
class Selector:
    """Where a model field comes from on the page.

    Use it as `Annotated` metadata on the field:

        title: Annotated[str, Selector("h1")]
        link: Annotated[str | None, Selector("a.more", attr="href")] = None
        price: Annotated[float, Selector(".price", pattern=r"\\d[\\d.]*")]
        tags: Annotated[list[str], Selector(".tag")]
        seller: Annotated[Seller, Selector(".seller")]  # nested model, scoped to the match
    """

    css: str
    _: KW_ONLY
    attr: str | None = None
    """Read this attribute instead of the element's text."""

    pattern: str | None = None
    """Regex applied to the value; keeps group 1 if there is one, else the whole match."""

    all: bool | None = None
    """Collect every match. Inferred from the field type (list, set, tuple) when unset."""


def _strip_optional(annotation: Any) -> Any:
    if get_origin(annotation) in (Union, types.UnionType):
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _shape(annotation: Any) -> tuple[bool, type[BaseModel] | None]:
    """Return (collect every match, nested model if the field holds one)."""
    annotation = _strip_optional(annotation)
    many = get_origin(annotation) in _COLLECTIONS
    if many:
        args = get_args(annotation)
        annotation = _strip_optional(args[0]) if args else Any
    nested = annotation if isinstance(annotation, type) and issubclass(annotation, BaseModel) else None
    return many, nested


async def _read(element: Locator, selector: Selector, nested: type[BaseModel] | None) -> Any:
    if nested is not None:
        return await _collect(element, nested)
    if selector.attr is not None:
        value = await element.get_attribute(selector.attr)
    else:
        value = (await element.inner_text()).strip()
    if value is None or selector.pattern is None:
        return value
    match = re.search(selector.pattern, value)
    if match is None:
        return None
    return match.group(1) if match.re.groups else match.group(0)


async def _collect(root: Page | Locator, model: type[BaseModel]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        selector = next((m for m in field.metadata if isinstance(m, Selector)), None)
        if selector is None:
            continue
        many, nested = _shape(field.annotation)
        if selector.all is not None:
            many = selector.all
        key = field.alias or name
        matches = root.locator(selector.css)
        if many:
            values = [await _read(element, selector, nested) for element in await matches.all()]
            data[key] = [value for value in values if value is not None]
        elif await matches.count():
            value = await _read(matches.first, selector, nested)
            # Leaving the key out lets the field default apply, and makes a required
            # field fail validation as "missing" rather than as a confusing None.
            if value is not None:
                data[key] = value
    return data


async def extract_model[M: BaseModel](root: Page | Locator, model: type[M], *, url: str) -> M:
    data = await _collect(root, model)
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ExtractionError(
            f"Could not extract {model.__name__} from {url}:\n{exc}", url=url, model=model
        ) from exc
