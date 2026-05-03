from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import (
    CollectionGetProtocol,
    DeleteModifierProtocol,
    GetModifierProtocol,
    UniqueGetModifierProtocol,
)

@runtime_checkable
class ModelHasCalibrationUniqueGetUpsertNamespace(Protocol):
    get: UniqueGetModifierProtocol
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class ModelHasCalibrationGetOnlyNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class ModelHasCalibrationGetDeleteNamespace(Protocol):
    get: GetModifierProtocol
    delete: DeleteModifierProtocol

@runtime_checkable
class ModelHasCalibrationNamespace(Protocol):
    get: CollectionGetProtocol
    _key: ModelHasCalibrationUniqueGetUpsertNamespace
    _from: ModelHasCalibrationGetOnlyNamespace
    _to: ModelHasCalibrationGetDeleteNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
