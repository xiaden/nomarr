from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import (
    CollectionGetProtocol,
    DeleteModifierProtocol,
    GetModifierProtocol,
    UniqueGetModifierProtocol,
)

@runtime_checkable
class ModelHasOutputUniqueGetUpsertNamespace(Protocol):
    get: UniqueGetModifierProtocol
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class ModelHasOutputGetOnlyNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class ModelHasOutputGetDeleteNamespace(Protocol):
    get: GetModifierProtocol
    delete: DeleteModifierProtocol

@runtime_checkable
class ModelHasOutputNamespace(Protocol):
    get: CollectionGetProtocol
    _key: ModelHasOutputUniqueGetUpsertNamespace
    _from: ModelHasOutputGetOnlyNamespace
    _to: ModelHasOutputGetDeleteNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
