"""Navidrome domain DTOs.

Data transfer objects for smart playlist queries and Navidrome integration.
These form cross-layer contracts between interfaces, services, and workflows.

Rules:
- Import only stdlib and typing (no nomarr.* imports)
- Pure data structures only (no I/O, no DB access, no business logic)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Maximum nesting depth for rule groups to prevent stack overflow
MAX_RULE_GROUP_DEPTH = 5


@dataclass
class TagCondition:
    """A single tag condition in a smart playlist query.

    Represents: tag:KEY OPERATOR VALUE
    """

    tag_key: str
    """Full tag key with namespace (e.g., "nom:mood_happy")"""

    operator: Literal[">", "<", ">=", "<=", "=", "!=", "contains"]
    """Comparison operator"""

    value: float | int | str
    """Value to compare against (typed)"""


@dataclass
class RuleGroup:
    """Recursive rule group for nested smart playlist queries.

    Supports nesting of AND/OR groups: (A AND B) OR (C AND D)
    """

    logic: Literal["AND", "OR"]
    """Logic operator for this group"""

    conditions: list[TagCondition]
    """Tag conditions directly in this group"""

    groups: list[RuleGroup]
    """Nested child groups (recursive structure)"""

    @property
    def depth(self) -> int:
        """Calculate max nesting depth of this group tree."""
        if not self.groups:
            return 1
        return 1 + max(g.depth for g in self.groups)



@dataclass
class SmartPlaylistFilter:
    """Structured filter representing a smart playlist query.

    Now supports nested rule groups via root RuleGroup.
    For backward compatibility, flat queries are represented as a single root group.
    """

    root: RuleGroup
    """Root rule group containing the query structure"""

    @property
    def is_simple_and(self) -> bool:
        """True if root is AND with no nested groups."""
        return self.root.logic == "AND" and len(self.root.groups) == 0

    @property
    def is_simple_or(self) -> bool:
        """True if root is OR with no nested groups."""
        return self.root.logic == "OR" and len(self.root.groups) == 0


@dataclass
class PlaylistPreviewResult:
    """Result from smart playlist preview operation.

    Contains both the total count of matching tracks and a sample of tracks
    for preview purposes.
    """

    total_count: int
    """Total number of tracks matching the query"""

    sample_tracks: list[dict[str, str]]
    """Sample of matching tracks (each dict has: path, title, artist, album)"""

    query: str
    """Original query string"""


@dataclass
class PreviewTagStatsResult:
    """Result from navidrome_service.preview_tag_stats()."""

    stats: dict[str, dict[str, str | int | float]]


@dataclass
class GeneratePlaylistResult:
    """Result from navidrome_service.generate_playlist()."""

    playlist_structure: dict[str, str | int | list[dict[str, str]]]


@dataclass
class TemplateSummaryItem:
    """Single template item from get_template_summary()."""

    template_id: str
    name: str
    description: str


@dataclass
class GetTemplateSummaryResult:
    """Result from navidrome_service.get_template_summary()."""

    templates: list[TemplateSummaryItem]


@dataclass
class GenerateTemplateFilesResult:
    """Result from navidrome_service.generate_template_files()."""

    files_generated: dict[str, str]
