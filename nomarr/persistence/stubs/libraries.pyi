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
class LibrariesNamespace(Protocol):
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
    library_contains_file: TraversalVerbProtocol
    library_contains_folder: TraversalVerbProtocol
    library_has_scan: TraversalVerbProtocol
    library_has_pipeline_state: TraversalVerbProtocol
    name: FieldAccessorProtocol
    root_path: FieldAccessorProtocol
    is_enabled: FieldAccessorProtocol
    watch_mode: FieldAccessorProtocol
    file_write_mode: FieldAccessorProtocol
    library_auto_write: FieldAccessorProtocol
    created_at: FieldAccessorProtocol
    updated_at: FieldAccessorProtocol
    vector_group_size: FieldAccessorProtocol
    vector_search_thoroughness: FieldAccessorProtocol
