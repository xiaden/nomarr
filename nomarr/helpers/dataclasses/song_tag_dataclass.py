"""Domain value objects for song/tag assignments.

These types deliberately contain no database identifiers or table metadata. The
persistence facade maps them to the storage-owned ``songs``, ``tags``, and
``song_tags`` rows internally.

Ownership (per artifacts/designs/parts/song-domain-repair/CONTRACTS.md — song-tag
migration contract, 2026-08-30):

- ``TagRef(name, value, namespace)`` is the complete tag natural key.
- ``SongTagAssignment`` is the domain association; it carries a domain
  ``song: SongIdentity | None`` handle (never a storage ``song_id``).
- ``TagUsage``, ``RelinkResult``, and ``TagCleanupResult`` are typed domain
  results for tag-listing/usage, duplicate-safe relink, and orphan cleanup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
    from nomarr.helpers.dataclasses.tags_dataclass import TagValue


@dataclass(frozen=True, slots=True)
class TagRef:
    """Stable domain identity for one tag value."""

    name: str
    value: TagValue
    namespace: str = ""

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("TagRef.name must not be blank")
        if not isinstance(self.namespace, str):
            raise TypeError("TagRef.namespace must be a string")


@dataclass(frozen=True, slots=True)
class SongTagAssignment:
    """One domain-level tag value assigned to a song.

    ``song`` is optional because per-song write operations already receive their
    song identity separately. It is populated on reads so callers can inspect
    the origin without ever seeing a storage row, a junction edge, or a primary
    key.
    """

    name: str
    value: TagValue
    namespace: str = ""
    confidence: float = 1.0
    source: str = "nomarr"
    song: SongIdentity | None = None

    @property
    def identity(self) -> TagRef:
        """Return this assignment's persistence-free tag identity."""
        return TagRef(name=self.name, value=self.value, namespace=self.namespace)

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("SongTagAssignment.name must not be blank")
        if not isinstance(self.namespace, str):
            raise TypeError("SongTagAssignment.namespace must be a string")
        if not isinstance(self.confidence, (int, float)) or isinstance(self.confidence, bool):
            raise TypeError("SongTagAssignment.confidence must be numeric")
        if not isinstance(self.source, str) or not self.source:
            raise ValueError("SongTagAssignment.source must not be blank")


@dataclass(frozen=True, slots=True)
class TagUsage:
    """A tag and how many songs it is assigned to (typed tag-usage result).

    Replaces the raw ``list[dict]`` tag-with-count projection at the facade
    boundary.
    """

    identity: TagRef
    song_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.song_count, int) or isinstance(self.song_count, bool):
            raise TypeError("TagUsage.song_count must be an int")
        if self.song_count < 0:
            raise ValueError("TagUsage.song_count must not be negative")


@dataclass(frozen=True, slots=True)
class RelinkResult:
    """Outcome of a duplicate-safe (ADR-014) tag relink operation.

    - ``moved``: source edges re-pointed to the target tag.
    - ``skipped``: source edges removed because they collided with an existing
      target edge (deleted before the update).
    - ``source_orphaned``: 1 if the source tag lost all of its assignments as a
      result of this operation (and was not already orphaned), else 0.
    """

    moved: int
    skipped: int
    source_orphaned: int

    def __post_init__(self) -> None:
        for field in (self.moved, self.skipped, self.source_orphaned):
            if not isinstance(field, int) or isinstance(field, bool) or field < 0:
                raise TypeError("RelinkResult counts must be non-negative ints")


@dataclass(frozen=True, slots=True)
class TagCleanupResult:
    """Outcome of the orphan-tag cleanup intent.

    - ``deleted``: orphaned tags deleted.
    - ``orphaned``: orphaned tags discovered by the cleanup scan.
    """

    deleted: int
    orphaned: int

    def __post_init__(self) -> None:
        for field in (self.deleted, self.orphaned):
            if not isinstance(field, int) or isinstance(field, bool) or field < 0:
                raise TypeError("TagCleanupResult counts must be non-negative ints")


__all__ = [
    "RelinkResult",
    "SongTagAssignment",
    "TagCleanupResult",
    "TagRef",
    "TagUsage",
]
