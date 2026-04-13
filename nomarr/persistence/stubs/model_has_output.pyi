from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import GetModifierProtocol

@runtime_checkable
class ModelHasOutputKeyNamespace(Protocol):
    get: GetModifierProtocol

    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class ModelHasOutputFromNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class ModelHasOutputToNamespace(Protocol):
    get: GetModifierProtocol

    def delete(self, value: str) -> int: ...

@runtime_checkable
class ModelHasOutputNamespace(Protocol):
    _key: ModelHasOutputKeyNamespace
    _from: ModelHasOutputFromNamespace
    _to: ModelHasOutputToNamespace

    def count(self) -> int: ...
    def get(self, id: str) -> dict[str, Any] | None: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
