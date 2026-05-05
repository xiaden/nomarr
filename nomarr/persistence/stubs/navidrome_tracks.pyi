from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from ._base import (
    CollectionGetVerbProtocol,
    DeleteWithCascadeProtocol,
    TraversalVerbProtocol,
)

@runtime_checkable
class NavidromeTracksNamespace(Protocol):
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
    has_nd_id: TraversalVerbProtocol
    has_plays: TraversalVerbProtocol
