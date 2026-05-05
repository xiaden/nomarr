from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from ._base import (
    CollectionGetVerbProtocol,
    DeleteWithCascadeProtocol,
    FieldAccessorProtocol,
    TraversalVerbProtocol,
)

@runtime_checkable
class LibraryFilesNamespace(Protocol):
    get: CollectionGetVerbProtocol
    delete: DeleteWithCascadeProtocol
    truncate: Callable[[], None]
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def count(self, *args: Any, **kwargs: Any) -> int: ...
    def update(self, *args: Any, **kwargs: Any) -> None: ...
    def upsert(self, *args: Any, **kwargs: Any) -> list[str]: ...
    def update_many(self, docs: list[dict[str, Any]]) -> None: ...
    def upsert_batch(self, docs: list[dict[str, Any]], match_fields: str | list[str]) -> list[str]: ...
    def aggregate(self, *args: Any, **kwargs: Any) -> list[Any]: ...
    song_has_tags: TraversalVerbProtocol
    file_has_state: TraversalVerbProtocol
    file_has_vectors: TraversalVerbProtocol
    file_has_segment_stats: TraversalVerbProtocol
    library_contains_file: TraversalVerbProtocol
    path: FieldAccessorProtocol
    normalized_path: FieldAccessorProtocol
    library_key: FieldAccessorProtocol
    status: FieldAccessorProtocol
    modified_time: FieldAccessorProtocol
    duration_seconds: FieldAccessorProtocol
    file_size: FieldAccessorProtocol
    album: FieldAccessorProtocol
    title: FieldAccessorProtocol
    artist: FieldAccessorProtocol
    artists: FieldAccessorProtocol
    labels: FieldAccessorProtocol
    genres: FieldAccessorProtocol
    year: FieldAccessorProtocol
    scanned_at: FieldAccessorProtocol
    chromaprint: FieldAccessorProtocol
    is_valid: FieldAccessorProtocol
    last_tagged_at: FieldAccessorProtocol
