from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from ._base import (
    CollectionGetVerbProtocol,
    DeleteWithCascadeProtocol,
    FieldAccessorProtocol,
    TraversalVerbProtocol,
)

@runtime_checkable
class TagsNamespace(Protocol):
    get: CollectionGetVerbProtocol
    delete: DeleteWithCascadeProtocol
    truncate: Callable[[], None]
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def count(self, *args: Any, **kwargs: Any) -> int: ...
    def update(self, *args: Any, **kwargs: Any) -> None: ...
    def upsert(self, *args: Any, **kwargs: Any) -> list[str]: ...
    def update_many(self, docs: list[dict[str, Any]]) -> None: ...
    def upsert_batch(self, docs: list[dict[str, Any]], match_fields: str | list[str]) -> list[str]: ...
    def aggregate(self, *args: Any, **kwargs: Any) -> list[Any]: ...
    song_has_tags: TraversalVerbProtocol
    tag_model_output: TraversalVerbProtocol
    name: FieldAccessorProtocol
    value: FieldAccessorProtocol
