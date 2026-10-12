"""`Extractor`: fills Pydantic models from the page using `Selector` field metadata."""

import re
import types
from dataclasses import KW_ONLY, dataclass
from functools import cache
from typing import Any, Optional, Union, get_args, get_origin

from patchright.async_api import Locator, Page
from pydantic import BaseModel, ValidationError, create_model

from .errors import ExtractionError

# Field types that mean "collect every match" rather than just the first.
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
    """CSS selector, resolved against the page or, in a nested model, the parent's element."""

    _: KW_ONLY
    attr: str | None = None
    """Read this attribute instead of the element's text."""

    pattern: str | None = None
    """Regex applied to the value; keeps group 1 if there is one, else the whole match."""

    all: bool | None = None
    """Collect every match. Inferred from the field type (list, set, tuple) when unset."""


class Extractor:
    """Builds Pydantic models from a page by reading each field's `Selector`.

    Stateless: one instance can be shared by every page.
    """

    @staticmethod
    def _strip_optional(annotation: Any) -> Any:
        """Unwrap `X | None` to `X`.

        Args:
            annotation: A type annotation.

        Returns:
            The single non-None member of an optional; any other annotation unchanged.
        """
        if get_origin(annotation) in (Union, types.UnionType):
            args = [arg for arg in get_args(annotation) if arg is not type(None)]
            if len(args) == 1:
                return args[0]
        return annotation

    @staticmethod
    def _shape(annotation: Any) -> tuple[bool, type[BaseModel] | None]:
        """Work out how a field should be read from its type annotation.

        Args:
            annotation: The field's type annotation.

        Returns:
            A pair: whether to collect every match (the field is a list, tuple or set), and the
            nested model class if the field holds one, else None.
        """
        annotation = Extractor._strip_optional(annotation)
        many = get_origin(annotation) in _COLLECTIONS
        if many:
            args = get_args(annotation)
            annotation = Extractor._strip_optional(args[0]) if args else Any
        nested = annotation if isinstance(annotation, type) and issubclass(annotation, BaseModel) else None
        return many, nested

    async def _read(self, element: Locator, selector: Selector, nested: type[BaseModel] | None) -> Any:
        """Read one value from one matched element.

        Args:
            element: The element the selector matched.
            selector: The field's selector, giving the attribute and pattern to apply.
            nested: Model to build from the element instead of reading a plain value.

        Returns:
            A nested model instance, or the element's stripped text or attribute with the
            pattern applied. None if the attribute is absent or the pattern does not match.
        """
        if nested is not None:
            return await self._build(element, nested)
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

    async def _collect(self, root: Page | Locator, model: type[BaseModel]) -> dict[str, Any]:
        """Read the raw value of every field of `model` that has a `Selector`.

        Args:
            root: The page or element the selectors are resolved against.
            model: The model being built.

        Returns:
            Raw values keyed by field alias (or name). Fields with no match are left out so that
            their defaults apply.
        """
        data: dict[str, Any] = {}
        for name, field in model.model_fields.items():
            selector = next((m for m in field.metadata if isinstance(m, Selector)), None)
            if selector is None:
                continue
            many, nested = self._shape(field.annotation)
            if selector.all is not None:
                many = selector.all
            key = field.alias or name
            matches = root.locator(selector.css)
            if many:
                values = [await self._read(element, selector, nested) for element in await matches.all()]
                data[key] = [value for value in values if value is not None]
            elif await matches.count():
                value = await self._read(matches.first, selector, nested)
                # Leaving the key out lets the field default apply, and makes a required
                # field fail validation as "missing" rather than as a confusing None.
                if value is not None:
                    data[key] = value
        return data

    @staticmethod
    def _has_selector(model: type[BaseModel], name: str) -> bool:
        """Report whether the field `name` of `model` carries a `Selector`."""
        return any(isinstance(m, Selector) for m in model.model_fields[name].metadata)

    @staticmethod
    @cache
    def _relaxed(model: type[BaseModel]) -> type[BaseModel]:
        """`model` with its required, selector-less fields turned into optional ones.

        A Selector is optional: a field without one has no source on the page, so instead of
        failing as "missing" it falls back to None.

        Args:
            model: The caller's model.

        Returns:
            A subclass with those fields made optional, or `model` itself if it has none.
            Cached per model.
        """
        unsourced = {
            name: (Optional[field.annotation], None)  # noqa: UP045 - the annotation is a runtime value
            for name, field in model.model_fields.items()
            if field.is_required() and not Extractor._has_selector(model, name)
        }
        if not unsourced:
            return model
        return create_model(model.__name__, __base__=model, **unsourced)

    async def _build[M: BaseModel](self, root: Page | Locator, model: type[M]) -> M:
        """Collect and validate one `model` from `root`.

        Args:
            root: The page or element to read from.
            model: The model to build.

        Returns:
            A validated instance of the caller's own class.

        Raises:
            pydantic.ValidationError: If the collected values do not satisfy the model.
        """
        data = await self._collect(root, model)
        relaxed = self._relaxed(model)
        instance = relaxed.model_validate(data)
        if relaxed is model:
            return instance
        # Hand back the caller's own class, not the relaxed stand-in used for validation.
        return model.model_construct(_fields_set=instance.model_fields_set, **dict(instance))

    async def extract[M: BaseModel](self, root: Page | Locator, model: type[M], *, url: str) -> M:
        """Build one `model` from `root`, reporting failures as `ExtractionError`.

        Args:
            root: The page or element to read from.
            model: Pydantic model whose fields carry `Selector` metadata.
            url: URL of the page, used in the error message.

        Returns:
            A validated instance of `model`.

        Raises:
            ExtractionError: If the content does not satisfy the model.
        """
        try:
            return await self._build(root, model)
        except ValidationError as exc:
            raise ExtractionError(
                f"Could not extract {model.__name__} from {url}:\n{exc}", url=url, model=model
            ) from exc
