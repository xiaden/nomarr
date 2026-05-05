from __future__ import annotations

from typing import Protocol, runtime_checkable

from ._base import DeleteWithCascadeProtocol, TraversalVerbProtocol

@runtime_checkable
class NavidromeTracksNamespace(Protocol):
    delete: DeleteWithCascadeProtocol
    has_nd_id: TraversalVerbProtocol
    has_plays: TraversalVerbProtocol
