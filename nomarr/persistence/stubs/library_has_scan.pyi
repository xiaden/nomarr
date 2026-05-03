from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import (
    CollectionGetProtocol,
    DeleteModifierProtocol,
    GetModifierProtocol,
)

@runtime_checkable
class LibraryHasScanGetOnlyNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class LibraryHasScanGetDeleteUpsertNamespace(Protocol):
    get: GetModifierProtocol
    delete: DeleteModifierProtocol
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class LibraryHasScanNamespace(Protocol):
    get: CollectionGetProtocol
    _from: LibraryHasScanGetOnlyNamespace
    _to: LibraryHasScanGetDeleteUpsertNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
