"""Typed values for song-tag persistence intents."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Real
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity


@dataclass(frozen=True, slots=True)
class TagRef:
    """Natural tag identity."""

    name: str
    value: object | None = None
    namespace: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("TagRef.name must not be blank")
        if not isinstance(self.namespace, str):
            raise TypeError("TagRef.namespace must be a string")


@dataclass(frozen=True, slots=True)
class SongTagAssignment:
    """A tag assigned to a song."""

    name: str
    value: object
    namespace: str = ""
    confidence: float = 1.0
    source: str = "nomarr"
    song: SongIdentity | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("SongTagAssignment.name must not be blank")
        if not isinstance(self.namespace, str):
            raise TypeError("SongTagAssignment.namespace must be a string")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, Real):
            raise TypeError("SongTagAssignment.confidence must be numeric")
        if not self.source:
            raise ValueError("SongTagAssignment.source must not be blank")

    @property
    def identity(self) -> TagRef:
        return TagRef(self.name, self.value, self.namespace)


@dataclass(frozen=True, slots=True)
class TagCleanupResult:
    """Summary of orphaned-tag cleanup."""

    deleted: int = 0
    orphaned: int = 0

    def __post_init__(self) -> None:
        _validate_count(self.deleted, "deleted")
        _validate_count(self.orphaned, "orphaned")


class RelinkResult(dict[str, int | bool]):
    """Mapping-compatible summary of a tag relink operation."""

    def __init__(self, moved: int = 0, skipped: int = 0, source_orphaned: bool | int = False) -> None:
        _validate_count(moved, "moved")
        _validate_count(skipped, "skipped")
        if isinstance(source_orphaned, bool):
            orphaned: bool | int = source_orphaned
        else:
            _validate_count(source_orphaned, "source_orphaned")
            orphaned = source_orphaned
        super().__init__(moved=moved, skipped=skipped, source_orphaned=orphaned)

    @property
    def moved(self) -> int:
        return int(self["moved"])

    @property
    def skipped(self) -> int:
        return int(self["skipped"])

    @property
    def source_orphaned(self) -> bool | int:
        return self["source_orphaned"]


@dataclass(frozen=True, slots=True)
class TagUsage:
    """Tag usage summary."""

    identity: TagRef
    song_count: int

    def __post_init__(self) -> None:
        if isinstance(self.song_count, bool) or not isinstance(self.song_count, int):
            raise TypeError("song_count must be an integer")
        if self.song_count < 0:
            raise ValueError("song_count must be non-negative")


def _validate_count(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value < 0:
        raise TypeError(f"{field} must be non-negative")


__all__ = ["RelinkResult", "SongTagAssignment", "TagCleanupResult", "TagRef", "TagUsage"]
