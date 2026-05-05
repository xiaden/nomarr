from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from ._base import CollectionDeleteVerbProtocol, CollectionGetVerbProtocol, FieldAccessorProtocol

@runtime_checkable
class HealthNamespace(Protocol):
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
    component: FieldAccessorProtocol
    component_id: FieldAccessorProtocol
    component_type: FieldAccessorProtocol
    status: FieldAccessorProtocol
    message: FieldAccessorProtocol
    last_heartbeat: FieldAccessorProtocol
    current_job: FieldAccessorProtocol
    metadata: FieldAccessorProtocol
    pid: FieldAccessorProtocol
    exit_code: FieldAccessorProtocol
    restart_count: FieldAccessorProtocol
    last_restart: FieldAccessorProtocol
    error: FieldAccessorProtocol
    last_snapshot: FieldAccessorProtocol
    created_at: FieldAccessorProtocol
    snapshot_type: FieldAccessorProtocol
