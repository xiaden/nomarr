from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import (
    CollectionGetProtocol,
    DeleteModifierProtocol,
    GetModifierProtocol,
)

@runtime_checkable
class FileHasVectorsGetOnlyNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class FileHasVectorsGetDeleteNamespace(Protocol):
    get: GetModifierProtocol
    delete: DeleteModifierProtocol

@runtime_checkable
class FileHasVectorsNamespace(Protocol):
    get: CollectionGetProtocol
    _from: FileHasVectorsGetOnlyNamespace
    _to: FileHasVectorsGetDeleteNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
