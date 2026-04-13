from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import GetModifierProtocol

@runtime_checkable
class ModelHasCalibrationKeyNamespace(Protocol):
    get: GetModifierProtocol

    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class ModelHasCalibrationFromNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class ModelHasCalibrationToNamespace(Protocol):
    get: GetModifierProtocol

    def delete(self, value: str) -> int: ...

@runtime_checkable
class ModelHasCalibrationNamespace(Protocol):
    _key: ModelHasCalibrationKeyNamespace
    _from: ModelHasCalibrationFromNamespace
    _to: ModelHasCalibrationToNamespace

    def count(self) -> int: ...
    def get(self, id: str) -> dict[str, Any] | None: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
