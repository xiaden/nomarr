from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from ._base import CollectionDeleteVerbProtocol, CollectionGetVerbProtocol, FieldAccessorProtocol

@runtime_checkable
class CalibrationHistoryNamespace(Protocol):
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
    calibration_key: FieldAccessorProtocol
    snapshot_at: FieldAccessorProtocol
    p5: FieldAccessorProtocol
    p95: FieldAccessorProtocol
    n: FieldAccessorProtocol
    underflow_count: FieldAccessorProtocol
    overflow_count: FieldAccessorProtocol
    p5_delta: FieldAccessorProtocol
    p95_delta: FieldAccessorProtocol
    n_delta: FieldAccessorProtocol
