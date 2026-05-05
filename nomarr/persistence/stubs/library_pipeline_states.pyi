from __future__ import annotations

from typing import Protocol, runtime_checkable

from ._base import TraversalVerbProtocol

@runtime_checkable
class LibraryPipelineStatesNamespace(Protocol):
    library_has_pipeline_state: TraversalVerbProtocol
