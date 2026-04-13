from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import CollectionGetProtocol, GetModifierProtocol

@runtime_checkable
class CalibrationHistoryGetOnlyNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class CalibrationHistoryCollectNamespace(Protocol):
    get: GetModifierProtocol

    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...

@runtime_checkable
class CalibrationHistoryDeleteNamespace(Protocol):
    get: GetModifierProtocol

    def delete(self, value: str) -> int: ...

@runtime_checkable
class CalibrationHistoryNamespace(Protocol):
    get: CollectionGetProtocol
    _key: CalibrationHistoryGetOnlyNamespace
    _id: CalibrationHistoryGetOnlyNamespace
    calibration_key: CalibrationHistoryDeleteNamespace
    snapshot_at: CalibrationHistoryCollectNamespace
    p5: CalibrationHistoryGetOnlyNamespace
    p95: CalibrationHistoryGetOnlyNamespace
    n: CalibrationHistoryGetOnlyNamespace
    underflow_count: CalibrationHistoryGetOnlyNamespace
    overflow_count: CalibrationHistoryGetOnlyNamespace
    p5_delta: CalibrationHistoryGetOnlyNamespace
    p95_delta: CalibrationHistoryGetOnlyNamespace
    n_delta: CalibrationHistoryGetOnlyNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def truncate(self) -> None: ...
