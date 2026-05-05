from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class TraversalVerbProtocol(Protocol):
    def __call__(self, doc_id: str, limit: int | None = ...) -> list[dict[str, Any]]: ...
    def by_ids(self, ids: list[str], limit: int | None = ..., **filters: Any) -> list[dict[str, Any]]: ...

@runtime_checkable
class CalibrationStateNamespace(Protocol):
    model_has_calibration: TraversalVerbProtocol
