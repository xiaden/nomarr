from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import CollectionGetProtocol, GetModifierProtocol

@runtime_checkable
class LibrariesIdNamespace(Protocol):
    get: GetModifierProtocol

    def update(self, match_value: str, fields: dict[str, Any]) -> None: ...
    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...

@runtime_checkable
class LibrariesKeyNamespace(Protocol):
    get: GetModifierProtocol

    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...

@runtime_checkable
class LibrariesUniqueGetNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class LibrariesManyGetNamespace(Protocol):
    get: GetModifierProtocol

    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...

@runtime_checkable
class LibrariesNamespace(Protocol):
    get: CollectionGetProtocol
    _key: LibrariesKeyNamespace
    _id: LibrariesIdNamespace
    name: LibrariesUniqueGetNamespace
    root_path: LibrariesUniqueGetNamespace
    is_enabled: LibrariesManyGetNamespace
    watch_mode: LibrariesManyGetNamespace
    file_write_mode: LibrariesManyGetNamespace
    library_auto_write: LibrariesManyGetNamespace
    created_at: LibrariesManyGetNamespace
    updated_at: LibrariesManyGetNamespace
    vector_group_size: LibrariesManyGetNamespace
    vector_search_thoroughness: LibrariesManyGetNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def cascade(self, ids: list[str]) -> int: ...
    def traversal(
        self,
        start: str | dict[str, Any],
        edge: str,
        *,
        target_filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[dict[str, Any]]: ...
