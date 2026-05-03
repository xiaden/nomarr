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
class HealthUniqueGetOnlyNamespace(Protocol):
    get: UniqueGetModifierProtocol

@runtime_checkable
class HealthUniqueGetCollectNamespace(Protocol):
    get: UniqueGetModifierProtocol
    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...

@runtime_checkable
class HealthUniqueGetCollectDeleteUpsertNamespace(Protocol):
    get: UniqueGetModifierProtocol
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
class HealthUniqueGetCollectUpdateUpsertNamespace(Protocol):
    get: UniqueGetModifierProtocol
    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class HealthGetCollectUpsertNamespace(Protocol):
    get: GetModifierProtocol
    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class HealthGetAggregateCollectUpdateUpsertNamespace(Protocol):
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
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class HealthGetUpdateUpsertNamespace(Protocol):
    get: GetModifierProtocol
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class HealthGetUpdateNamespace(Protocol):
    get: GetModifierProtocol
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class HealthGetUpsertNamespace(Protocol):
    get: GetModifierProtocol
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class HealthNamespace(Protocol):
    get: CollectionGetProtocol
    _key: HealthUniqueGetOnlyNamespace
    _id: HealthUniqueGetCollectNamespace
    component: HealthUniqueGetCollectDeleteUpsertNamespace
    component_id: HealthUniqueGetCollectUpdateUpsertNamespace
    component_type: HealthGetCollectUpsertNamespace
    status: HealthGetAggregateCollectUpdateUpsertNamespace
    message: HealthGetUpdateUpsertNamespace
    last_heartbeat: HealthGetUpdateUpsertNamespace
    current_job: HealthGetUpdateUpsertNamespace
    metadata: HealthGetUpdateUpsertNamespace
    pid: HealthGetUpdateUpsertNamespace
    exit_code: HealthGetUpdateNamespace
    restart_count: HealthGetUpdateNamespace
    last_restart: HealthGetUpdateNamespace
    error: HealthGetUpdateNamespace
    last_snapshot: HealthGetUpdateNamespace
    created_at: HealthGetUpsertNamespace
    snapshot_type: HealthGetCollectUpsertNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
