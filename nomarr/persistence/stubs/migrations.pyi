from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import CollectionGetProtocol, GetModifierProtocol, GetOneProtocol

@runtime_checkable
class MigrationsNameNamespace(Protocol):
    get: GetOneProtocol

    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...
    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...

@runtime_checkable
class MigrationsStatusNamespace(Protocol):
    get: GetModifierProtocol

    def update(self, match_value: str, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class MigrationsAppliedAtNamespace(Protocol):
    get: GetModifierProtocol

    def update(self, match_value: str, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class MigrationsStartedAtNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class MigrationsMigrationVersionNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class MigrationsDurationMsNamespace(Protocol):
    get: GetModifierProtocol

    def update(self, match_value: int, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class MigrationsNamespace(Protocol):
    get: CollectionGetProtocol
    name: MigrationsNameNamespace
    status: MigrationsStatusNamespace
    applied_at: MigrationsAppliedAtNamespace
    started_at: MigrationsStartedAtNamespace
    migration_version: MigrationsMigrationVersionNamespace
    duration_ms: MigrationsDurationMsNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
