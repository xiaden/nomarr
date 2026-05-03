from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import (
    AggResult,
    CollectionGetProtocol,
    GetModifierProtocol,
    TraversalProtocol,
    UniqueGetModifierProtocol,
)

@runtime_checkable
class TagsUniqueGetOnlyNamespace(Protocol):
    get: UniqueGetModifierProtocol

@runtime_checkable
class TagsUniqueGetCollectNamespace(Protocol):
    get: UniqueGetModifierProtocol
    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...

@runtime_checkable
class TagsGetAggregateCollectCountNamespace(Protocol):
    get: GetModifierProtocol
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

@runtime_checkable
class TagsGetUpsertNamespace(Protocol):
    get: GetModifierProtocol
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class TagsNamespace(Protocol):
    get: CollectionGetProtocol
    _key: TagsUniqueGetOnlyNamespace
    _id: TagsUniqueGetCollectNamespace
    name: TagsGetAggregateCollectCountNamespace
    value: TagsGetUpsertNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def cascade(self, ids: list[str]) -> int: ...
    traversal: TraversalProtocol
