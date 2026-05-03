from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import (
    CollectionGetProtocol,
    DeleteModifierProtocol,
    GetModifierProtocol,
    UniqueGetModifierProtocol,
)

@runtime_checkable
class MlCapacityUniqueGetOnlyNamespace(Protocol):
    get: UniqueGetModifierProtocol

@runtime_checkable
class MlCapacityUniqueGetDeleteUpsertNamespace(Protocol):
    get: UniqueGetModifierProtocol
    delete: DeleteModifierProtocol
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class MlCapacityGetUpdateNamespace(Protocol):
    get: GetModifierProtocol
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class MlCapacityGetOnlyNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class MlCapacityNamespace(Protocol):
    get: CollectionGetProtocol
    _key: MlCapacityUniqueGetOnlyNamespace
    _id: MlCapacityUniqueGetOnlyNamespace
    model_set_hash: MlCapacityUniqueGetDeleteUpsertNamespace
    measured_backbone_vram_mb: MlCapacityGetUpdateNamespace
    estimated_worker_ram_mb: MlCapacityGetUpdateNamespace
    probe_duration_s: MlCapacityGetUpdateNamespace
    probed_by: MlCapacityGetUpdateNamespace
    created_at: MlCapacityGetOnlyNamespace
    updated_at: MlCapacityGetUpdateNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def update_by_filter(self, filter_dict: dict[str, Any], fields: dict[str, Any]) -> None: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
