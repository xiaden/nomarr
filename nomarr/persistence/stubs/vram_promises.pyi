from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import (
    AggResult,
    CollectionGetProtocol,
    DeleteModifierProtocol,
    GetModifierProtocol,
    UniqueGetModifierProtocol,
)

@runtime_checkable
class VramPromisesUniqueGetOnlyNamespace(Protocol):
    get: UniqueGetModifierProtocol

@runtime_checkable
class VramPromisesGetCollectDeleteNamespace(Protocol):
    get: GetModifierProtocol
    delete: DeleteModifierProtocol
    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...

@runtime_checkable
class VramPromisesGetUpdateNamespace(Protocol):
    get: GetModifierProtocol
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class VramPromisesGetAggregateCollectNamespace(Protocol):
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

@runtime_checkable
class VramPromisesNamespace(Protocol):
    get: CollectionGetProtocol
    _key: VramPromisesUniqueGetOnlyNamespace
    _id: VramPromisesUniqueGetOnlyNamespace
    worker_id: VramPromisesGetCollectDeleteNamespace
    pid: VramPromisesGetUpdateNamespace
    model_path: VramPromisesGetCollectDeleteNamespace
    promised_mb: VramPromisesGetAggregateCollectNamespace
    total_mb: VramPromisesGetUpdateNamespace
    used_mb: VramPromisesGetUpdateNamespace
    last_seen_ms: VramPromisesGetUpdateNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
