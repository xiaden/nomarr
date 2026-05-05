from __future__ import annotations

from typing import Protocol, runtime_checkable

from ._base import DeleteWithCascadeProtocol, TraversalVerbProtocol

@runtime_checkable
class LibrariesNamespace(Protocol):
    delete: DeleteWithCascadeProtocol
    library_contains_file: TraversalVerbProtocol
    library_contains_folder: TraversalVerbProtocol
    library_has_scan: TraversalVerbProtocol
    library_has_pipeline_state: TraversalVerbProtocol
