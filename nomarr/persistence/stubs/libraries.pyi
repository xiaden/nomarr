from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import (
    CollectionGetProtocol,
    GetModifierProtocol,
    TraversalProtocol,
    UniqueGetModifierProtocol,
)

@runtime_checkable
class LibrariesUniqueGetCollectNamespace(Protocol):
    get: UniqueGetModifierProtocol
    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...

@runtime_checkable
class LibrariesUniqueGetCollectUpdateNamespace(Protocol):
    get: UniqueGetModifierProtocol
    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class LibrariesUniqueGetOnlyNamespace(Protocol):
    get: UniqueGetModifierProtocol

@runtime_checkable
class LibrariesGetCollectNamespace(Protocol):
    get: GetModifierProtocol
    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...

@runtime_checkable
class LibrariesGetOnlyNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class LibrariesNamespace(Protocol):
    get: CollectionGetProtocol
    _key: LibrariesUniqueGetCollectNamespace
    _id: LibrariesUniqueGetCollectUpdateNamespace
    name: LibrariesUniqueGetOnlyNamespace
    root_path: LibrariesUniqueGetOnlyNamespace
    is_enabled: LibrariesGetCollectNamespace
    watch_mode: LibrariesGetCollectNamespace
    file_write_mode: LibrariesGetOnlyNamespace
    library_auto_write: LibrariesGetOnlyNamespace
    created_at: LibrariesGetOnlyNamespace
    updated_at: LibrariesGetOnlyNamespace
    vector_group_size: LibrariesGetOnlyNamespace
    vector_search_thoroughness: LibrariesGetOnlyNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def cascade(self, ids: list[str]) -> int: ...
    traversal: TraversalProtocol
