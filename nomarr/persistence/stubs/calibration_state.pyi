from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import (
    CollectionGetProtocol,
    GetModifierProtocol,
    UniqueGetModifierProtocol,
)

@runtime_checkable
class CalibrationStateUniqueGetUpsertNamespace(Protocol):
    get: UniqueGetModifierProtocol
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class CalibrationStateUniqueGetCollectNamespace(Protocol):
    get: UniqueGetModifierProtocol
    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...

@runtime_checkable
class CalibrationStateGetCollectUpsertNamespace(Protocol):
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
class CalibrationStateGetUpdateNamespace(Protocol):
    get: GetModifierProtocol
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class CalibrationStateGetCountNamespace(Protocol):
    get: GetModifierProtocol
    def count(self, value: Any) -> int: ...

@runtime_checkable
class CalibrationStateNamespace(Protocol):
    get: CollectionGetProtocol
    _key: CalibrationStateUniqueGetUpsertNamespace
    _id: CalibrationStateUniqueGetCollectNamespace
    head_name: CalibrationStateGetCollectUpsertNamespace
    label: CalibrationStateGetCollectUpsertNamespace
    calibration_def_hash: CalibrationStateGetUpdateNamespace
    histogram: CalibrationStateGetUpdateNamespace
    histogram_bins: CalibrationStateGetUpdateNamespace
    p5: CalibrationStateGetUpdateNamespace
    p95: CalibrationStateGetUpdateNamespace
    n: CalibrationStateGetUpdateNamespace
    underflow_count: CalibrationStateGetUpdateNamespace
    overflow_count: CalibrationStateGetUpdateNamespace
    updated_at: CalibrationStateGetCountNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def update_by_filter(self, filter_dict: dict[str, Any], fields: dict[str, Any]) -> None: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def cascade(self, ids: list[str]) -> int: ...
    def truncate(self) -> None: ...
