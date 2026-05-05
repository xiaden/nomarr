from __future__ import annotations

from typing import Protocol, runtime_checkable

from ._base import DeleteWithCascadeProtocol, TraversalVerbProtocol

@runtime_checkable
class LibraryFilesNamespace(Protocol):
    delete: DeleteWithCascadeProtocol
    song_has_tags: TraversalVerbProtocol
    file_has_state: TraversalVerbProtocol
    file_has_vectors: TraversalVerbProtocol
    file_has_segment_stats: TraversalVerbProtocol
    library_contains_file: TraversalVerbProtocol
