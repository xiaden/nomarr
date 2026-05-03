from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import (
    CollectionGetProtocol,
    GetModifierProtocol,
    UniqueGetModifierProtocol,
)

@runtime_checkable
class MigrationsUniqueGetCollectUpsertNamespace(Protocol):
    get: UniqueGetModifierProtocol
    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class MigrationsGetUpdateNamespace(Protocol):
    get: GetModifierProtocol
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class MigrationsGetOnlyNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class MigrationsNamespace(Protocol):
    get: CollectionGetProtocol
    name: MigrationsUniqueGetCollectUpsertNamespace
    status: MigrationsGetUpdateNamespace
    applied_at: MigrationsGetUpdateNamespace
    started_at: MigrationsGetOnlyNamespace
    migration_version: MigrationsGetOnlyNamespace
    duration_ms: MigrationsGetUpdateNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
