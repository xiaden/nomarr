"""
Navidrome domain DTOs.

Data transfer objects for smart playlist queries and Navidrome integration.
These form cross-layer contracts between interfaces, services, and workflows.

Rules:
- Import only stdlib and typing (no nomarr.* imports)
- Pure data structures only (no I/O, no DB access, no business logic)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class TagCondition:
    """
    A single tag condition in a smart playlist query.

    Represents: tag:KEY OPERATOR VALUE
    """

    tag_key: str
    """Full tag key with namespace (e.g., "nom:mood_happy")"""

    operator: Literal[">", "<", ">=", "<=", "=", "!=", "contains"]
    """Comparison operator"""

    value: float | int | str
    """Value to compare against (typed)"""


@dataclass
class SmartPlaylistFilter:
    """
    Structured filter representing a smart playlist query.

    Contains conditions grouped by logic operators (AND/OR).
    """

    all_conditions: list[TagCondition]
    """Conditions joined by AND (all must match)"""

    any_conditions: list[TagCondition]
    """Conditions joined by OR (any must match)"""

    @property
    def is_simple_and(self) -> bool:
        """True if all conditions are AND (no OR)."""
        return len(self.all_conditions) > 0 and len(self.any_conditions) == 0

    @property
    def is_simple_or(self) -> bool:
        """True if all conditions are OR (no AND)."""
        return len(self.any_conditions) > 0 and len(self.all_conditions) == 0


@dataclass
class PlaylistPreviewResult:
    """
    Result from smart playlist preview operation.

    Contains both the total count of matching tracks and a sample of tracks
    for preview purposes.
    """

    total_count: int
    """Total number of tracks matching the query"""

    sample_tracks: list[dict[str, str]]
    """Sample of matching tracks (each dict has: path, title, artist, album)"""

    query: str
    """Original query string"""
