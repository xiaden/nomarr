from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import CollectionGetProtocol, GetModifierProtocol

@runtime_checkable
class CalibrationStateKeyNamespace(Protocol):
    get: GetModifierProtocol

    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class CalibrationStateIdNamespace(Protocol):
    get: GetModifierProtocol

    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...

@runtime_checkable
class CalibrationStateGetOnlyNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class CalibrationStateCollectUpsertNamespace(Protocol):
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
class CalibrationStateUpdateNamespace(Protocol):
    get: GetModifierProtocol

    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class CalibrationStateUpdatedAtNamespace(Protocol):
    get: GetModifierProtocol

    def count(self, value: int | None) -> int: ...

@runtime_checkable
class CalibrationStateNamespace(Protocol):
    get: CollectionGetProtocol
    _key: CalibrationStateKeyNamespace
    _id: CalibrationStateIdNamespace
    head_name: CalibrationStateCollectUpsertNamespace
    label: CalibrationStateCollectUpsertNamespace
    calibration_def_hash: CalibrationStateUpdateNamespace
    histogram: CalibrationStateUpdateNamespace
    histogram_bins: CalibrationStateUpdateNamespace
    p5: CalibrationStateUpdateNamespace
    p95: CalibrationStateUpdateNamespace
    n: CalibrationStateUpdateNamespace
    underflow_count: CalibrationStateUpdateNamespace
    overflow_count: CalibrationStateUpdateNamespace
    updated_at: CalibrationStateUpdatedAtNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def update_by_filter(self, filter_dict: dict[str, Any], fields: dict[str, Any]) -> None: ...
    def cascade(self, ids: list[str]) -> int: ...
    def truncate(self) -> None: ...
