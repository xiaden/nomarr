from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from ._base import CollectionDeleteVerbProtocol, CollectionGetVerbProtocol, FieldAccessorProtocol

@runtime_checkable
class VectorsTrackColdNamespace(Protocol):
    get: CollectionGetVerbProtocol
    delete: CollectionDeleteVerbProtocol
    truncate: Callable[[], None]
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def count(self, *args: Any, **kwargs: Any) -> int: ...
    def update(self, *args: Any, **kwargs: Any) -> None: ...
    def upsert(self, *args: Any, **kwargs: Any) -> list[str]: ...
    def upsert_batch(self, docs: list[dict[str, Any]], match_fields: str | list[str]) -> list[str]: ...
    def aggregate(self, *args: Any, **kwargs: Any) -> list[Any]: ...
    def ann_search(
        self,
        query_vector: list[float],
        limit: int,
        nprobe: int,
        *,
        filter: dict[str, Any] | None = ...,
    ) -> list[dict[str, Any]]: ...
    def get_vector(self, file_id: str) -> dict[str, Any] | None: ...
    def update_many(self, docs: list[dict[str, Any]]) -> None: ...
    file_id: FieldAccessorProtocol
    vector: FieldAccessorProtocol
