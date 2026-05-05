from __future__ import annotations

from typing import Protocol, runtime_checkable

from ._base import TraversalVerbProtocol

@runtime_checkable
class SegmentScoresStatsNamespace(Protocol):
    file_has_segment_stats: TraversalVerbProtocol
