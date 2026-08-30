"""Typed values for song-tag persistence intents."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TagRef:
    """Natural tag identity."""

    name: str
    value: str | None = None


@dataclass(frozen=True, slots=True)
class SongTagAssignment:
    """A tag assigned to a song."""

    tag: TagRef


@dataclass(frozen=True, slots=True)
class TagCleanupResult:
    """Summary of orphaned-tag cleanup."""

    removed: int


@dataclass(frozen=True, slots=True)
class TagUsage:
    """Tag usage summary."""

    tag: TagRef
    song_count: int


class RelinkResult(dict[str, int | bool]):
    """Mapping-compatible summary of a tag relink operation."""


__all__ = ["RelinkResult", "SongTagAssignment", "TagCleanupResult", "TagRef", "TagUsage"]
