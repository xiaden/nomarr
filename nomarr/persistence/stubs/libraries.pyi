from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class TraversalVerbProtocol(Protocol):
    def __call__(self, doc_id: str, limit: int | None = ...) -> list[dict[str, Any]]: ...
    def by_ids(self, ids: list[str], limit: int | None = ..., **filters: Any) -> list[dict[str, Any]]: ...

@runtime_checkable
class DeleteWithCascadeProtocol(Protocol):
    def __call__(self, *args: Any, **kwargs: Any) -> int: ...
    def cascade(self, *args: Any, **kwargs: Any) -> int: ...

@runtime_checkable
class LibrariesNamespace(Protocol):
    delete: DeleteWithCascadeProtocol
    library_contains_file: TraversalVerbProtocol
    library_contains_folder: TraversalVerbProtocol
    library_has_scan: TraversalVerbProtocol
    library_has_pipeline_state: TraversalVerbProtocol
