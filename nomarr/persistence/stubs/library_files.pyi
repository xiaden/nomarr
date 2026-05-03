from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import (
    AggResult,
    CollectionGetProtocol,
    DeleteModifierProtocol,
    GetModifierProtocol,
    TraversalProtocol,
    UniqueGetModifierProtocol,
)

@runtime_checkable
class LibraryFilesUniqueGetUpdateNamespace(Protocol):
    get: UniqueGetModifierProtocol
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class LibraryFilesUniqueGetCollectUpdateNamespace(Protocol):
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
class LibraryFilesUniqueGetCollectDeleteUpdateUpsertNamespace(Protocol):
    get: UniqueGetModifierProtocol
    delete: DeleteModifierProtocol
    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class LibraryFilesGetCollectUpdateNamespace(Protocol):
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
class LibraryFilesGetCountDeleteNamespace(Protocol):
    get: GetModifierProtocol
    delete: DeleteModifierProtocol
    def count(self, value: Any) -> int: ...

@runtime_checkable
class LibraryFilesGetUpdateNamespace(Protocol):
    get: GetModifierProtocol
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class LibraryFilesGetOnlyNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class LibraryFilesGetAggregateUpdateNamespace(Protocol):
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
    _key: LibraryFilesUniqueGetUpdateNamespace
    _id: LibraryFilesUniqueGetCollectUpdateNamespace
    path: LibraryFilesUniqueGetCollectDeleteUpdateUpsertNamespace
    normalized_path: LibraryFilesGetCollectUpdateNamespace
    library_key: LibraryFilesGetCountDeleteNamespace
    status: LibraryFilesGetUpdateNamespace
    modified_time: LibraryFilesGetUpdateNamespace
    duration_seconds: LibraryFilesGetOnlyNamespace
    file_size: LibraryFilesGetOnlyNamespace
    album: LibraryFilesGetAggregateUpdateNamespace
    title: LibraryFilesGetUpdateNamespace
    artist: LibraryFilesGetAggregateUpdateNamespace
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
    def update_by_filter(self, filter_dict: dict[str, Any], fields: dict[str, Any]) -> None: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def cascade(self, ids: list[str]) -> int: ...
    def truncate(self) -> None: ...
    traversal: TraversalProtocol
