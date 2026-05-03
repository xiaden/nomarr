from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import (
    AggResult,
    CollectionGetProtocol,
    DeleteModifierProtocol,
    GetModifierProtocol,
)

@runtime_checkable
class SongHasTagsGetDeleteNamespace(Protocol):
    get: GetModifierProtocol
    delete: DeleteModifierProtocol

@runtime_checkable
class SongHasTagsGetAggregateCollectCountDeleteUpsertNamespace(Protocol):
    get: GetModifierProtocol
    delete: DeleteModifierProtocol
    def count(self, value: Any) -> int: ...
    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...
    def aggregate(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[AggResult]: ...
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class SongHasTagsNamespace(Protocol):
    get: CollectionGetProtocol
    _from: SongHasTagsGetDeleteNamespace
    _to: SongHasTagsGetAggregateCollectCountDeleteUpsertNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def truncate(self) -> None: ...
