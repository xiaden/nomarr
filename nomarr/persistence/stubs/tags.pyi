from __future__ import annotations

from typing import Protocol, runtime_checkable

from ._base import DeleteWithCascadeProtocol, TraversalVerbProtocol

@runtime_checkable
class TagsNamespace(Protocol):
    delete: DeleteWithCascadeProtocol
    song_has_tags: TraversalVerbProtocol
    tag_model_output: TraversalVerbProtocol
