from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import (
    AggResult,
    CollectionGetProtocol,
    DeleteModifierProtocol,
    GetModifierProtocol,
    TraversalProtocol,
    UniqueGetModifierProtocol,
)

@runtime_checkable
class NavidromePlaycountsUniqueGetUpsertNamespace(Protocol):
    get: UniqueGetModifierProtocol
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class NavidromePlaycountsUniqueGetOnlyNamespace(Protocol):
    get: UniqueGetModifierProtocol

@runtime_checkable
class NavidromePlaycountsGetAggregateCollectUpsertNamespace(Protocol):
    get: GetModifierProtocol
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
class NavidromePlaycountsGetCollectDeleteUpsertNamespace(Protocol):
    get: GetModifierProtocol
    delete: DeleteModifierProtocol
    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class NavidromePlaycountsNamespace(Protocol):
    get: CollectionGetProtocol
    _key: NavidromePlaycountsUniqueGetUpsertNamespace
    _id: NavidromePlaycountsUniqueGetOnlyNamespace
    playcount: NavidromePlaycountsGetAggregateCollectUpsertNamespace
    userid: NavidromePlaycountsGetCollectDeleteUpsertNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def update_by_filter(self, filter_dict: dict[str, Any], fields: dict[str, Any]) -> None: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    traversal: TraversalProtocol
