from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import (
    AggResult,
    CollectionGetProtocol,
    GetModifierProtocol,
    TraversalProtocol,
)

@runtime_checkable
class LibraryFilesGetUpdateNamespace(Protocol):
    get: GetModifierProtocol

    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class LibraryFilesIdNamespace(Protocol):
    get: GetModifierProtocol

    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...
    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...

@runtime_checkable
class LibraryFilesPathNamespace(Protocol):
    get: GetModifierProtocol

    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...
    def update(self, match_value: str, fields: dict[str, Any]) -> None: ...
    def delete(self, value: str) -> int: ...

@runtime_checkable
class LibraryFilesNormalizedPathNamespace(Protocol):
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
class LibraryFilesLibraryKeyNamespace(Protocol):
    get: GetModifierProtocol

    def count(self, value: str) -> int: ...
    def delete(self, value: str) -> int: ...

@runtime_checkable
class LibraryFilesGetOnlyNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class LibraryFilesAggregateUpdateNamespace(Protocol):
    get: GetModifierProtocol

    def aggregate(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[AggResult]: ...
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class LibraryFilesNamespace(Protocol):
    get: CollectionGetProtocol
    _key: LibraryFilesGetUpdateNamespace
    _id: LibraryFilesIdNamespace
    path: LibraryFilesPathNamespace
    normalized_path: LibraryFilesNormalizedPathNamespace
    library_key: LibraryFilesLibraryKeyNamespace
    status: LibraryFilesGetUpdateNamespace
    modified_time: LibraryFilesGetUpdateNamespace
    duration_seconds: LibraryFilesGetOnlyNamespace
    file_size: LibraryFilesGetOnlyNamespace
    album: LibraryFilesAggregateUpdateNamespace
    title: LibraryFilesGetUpdateNamespace
    artist: LibraryFilesAggregateUpdateNamespace
    artists: LibraryFilesGetUpdateNamespace
    labels: LibraryFilesGetUpdateNamespace
    genres: LibraryFilesGetUpdateNamespace
    year: LibraryFilesGetUpdateNamespace
    scanned_at: LibraryFilesGetUpdateNamespace
    chromaprint: LibraryFilesGetUpdateNamespace
    is_valid: LibraryFilesGetUpdateNamespace
    last_tagged_at: LibraryFilesGetUpdateNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def update_by_filter(self, filter_dict: dict[str, Any], fields: dict[str, Any]) -> None: ...
    def cascade(self, ids: list[str]) -> int: ...
    def truncate(self) -> None: ...
    traversal: TraversalProtocol
