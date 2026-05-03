from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import (
    CollectionGetProtocol,
    GetModifierProtocol,
    UniqueGetModifierProtocol,
)

@runtime_checkable
class LibraryScansUniqueGetOnlyNamespace(Protocol):
    get: UniqueGetModifierProtocol

@runtime_checkable
class LibraryScansUniqueGetUpdateNamespace(Protocol):
    get: UniqueGetModifierProtocol
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class LibraryScansGetCollectUpdateNamespace(Protocol):
    get: GetModifierProtocol
    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class LibraryScansGetUpdateNamespace(Protocol):
    get: GetModifierProtocol
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class LibraryScansNamespace(Protocol):
    get: CollectionGetProtocol
    _key: LibraryScansUniqueGetOnlyNamespace
    _id: LibraryScansUniqueGetOnlyNamespace
    library_key: LibraryScansUniqueGetUpdateNamespace
    status: LibraryScansGetCollectUpdateNamespace
    files_processed: LibraryScansGetUpdateNamespace
    files_total: LibraryScansGetUpdateNamespace
    completed_at: LibraryScansGetUpdateNamespace
    started_at: LibraryScansGetUpdateNamespace
    error: LibraryScansGetUpdateNamespace
    scan_type: LibraryScansGetCollectUpdateNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def update_by_filter(self, filter_dict: dict[str, Any], fields: dict[str, Any]) -> None: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
