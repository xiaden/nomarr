from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from ._base import CollectionDeleteVerbProtocol, CollectionGetVerbProtocol, FieldAccessorProtocol

@runtime_checkable
class MlCapacityNamespace(Protocol):
    get: CollectionGetVerbProtocol
    delete: CollectionDeleteVerbProtocol
    truncate: Callable[[], None]
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def count(self, *args: Any, **kwargs: Any) -> int: ...
    def update(self, *args: Any, **kwargs: Any) -> None: ...
    def upsert(self, *args: Any, **kwargs: Any) -> list[str]: ...
    def update_many(self, docs: list[dict[str, Any]]) -> None: ...
    def upsert_batch(self, docs: list[dict[str, Any]], match_fields: str | list[str]) -> list[str]: ...
    def aggregate(self, *args: Any, **kwargs: Any) -> list[Any]: ...
    model_set_hash: FieldAccessorProtocol
    measured_backbone_vram_mb: FieldAccessorProtocol
    estimated_worker_ram_mb: FieldAccessorProtocol
    probe_duration_s: FieldAccessorProtocol
    probed_by: FieldAccessorProtocol
    created_at: FieldAccessorProtocol
    updated_at: FieldAccessorProtocol
