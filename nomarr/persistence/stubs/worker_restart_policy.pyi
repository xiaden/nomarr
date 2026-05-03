from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import (
    CollectionGetProtocol,
    GetModifierProtocol,
    UniqueGetModifierProtocol,
)

@runtime_checkable
class WorkerRestartPolicyUniqueGetOnlyNamespace(Protocol):
    get: UniqueGetModifierProtocol

@runtime_checkable
class WorkerRestartPolicyUniqueGetUpdateUpsertNamespace(Protocol):
    get: UniqueGetModifierProtocol
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class WorkerRestartPolicyGetUpdateNamespace(Protocol):
    get: GetModifierProtocol
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class WorkerRestartPolicyNamespace(Protocol):
    get: CollectionGetProtocol
    _key: WorkerRestartPolicyUniqueGetOnlyNamespace
    _id: WorkerRestartPolicyUniqueGetOnlyNamespace
    component_id: WorkerRestartPolicyUniqueGetUpdateUpsertNamespace
    restart_count: WorkerRestartPolicyGetUpdateNamespace
    last_restart_wall_ms: WorkerRestartPolicyGetUpdateNamespace
    failed_at_wall_ms: WorkerRestartPolicyGetUpdateNamespace
    failure_reason: WorkerRestartPolicyGetUpdateNamespace
    updated_at_wall_ms: WorkerRestartPolicyGetUpdateNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def update_by_filter(self, filter_dict: dict[str, Any], fields: dict[str, Any]) -> None: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
