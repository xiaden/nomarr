"""Typed values for song-tag persistence intents."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Real
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity


@dataclass(frozen=True, slots=True)
class TagRef:
    """Natural tag identity."""

    name: str
    value: object | None = None
    namespace: str = "default"

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("TagRef.name must not be blank")
        if not isinstance(self.namespace, str):
            raise TypeError("TagRef.namespace must be a string")
        if not self.namespace.strip():
            # Ordinary namespace normalization is one canonical rule: omitted or
            # empty ordinary namespace becomes the literal ``default``. An
            # explicit ``nom`` is preserved (non-blank). No path treats NULL as
            # an ordinary namespace (non-str ``None`` is rejected above).
            object.__setattr__(self, "namespace", "default")


@dataclass(frozen=True, slots=True)
class SongTagAssignment:
    """A tag assigned to a song."""

    name: str
    value: object
    namespace: str = "default"
    confidence: float = 1.0
    source: str = "nomarr"
    song: SongIdentity | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("SongTagAssignment.name must not be blank")
        if not isinstance(self.namespace, str):
            raise TypeError("SongTagAssignment.namespace must be a string")
        if not self.namespace.strip():
            # Ordinary namespace normalization: blank becomes literal
            # ``default``; explicit ``nom`` is preserved. No NULL-as-ordinary.
            object.__setattr__(self, "namespace", "default")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, Real):
            raise TypeError("SongTagAssignment.confidence must be numeric")
        if not self.source:
            raise ValueError("SongTagAssignment.source must not be blank")

    @property
    def identity(self) -> TagRef:
        return TagRef(self.name, self.value, self.namespace)


MoodTier = Literal["nom:mood-strict", "nom:mood-regular", "nom:mood-loose"]
MoodMarkerStatus = Literal["calibrated", "uncalibrated", "UNPROVEN"]
MoodWriteStatus = Literal[
    "UPDATED",
    "UNCHANGED",
    "MISSING_LOCATOR",
    "INVALID_VALUE",
    "INFRA_FAILURE",
    "AMBIGUOUS_COMMIT",
]


@dataclass(frozen=True, slots=True)
class MoodAssignments:
    """Canonical semantic values for the three mood tiers.

    Values are stored as immutable, de-duplicated tuples.  The tier names are
    the complete tag names used by the mood owner; persistence assigns the
    ``nom`` namespace privately and never receives rows or generated IDs.
    """

    strict: tuple[str, ...] = ()
    regular: tuple[str, ...] = ()
    loose: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("strict", "regular", "loose"):
            values = getattr(self, field_name)
            if isinstance(values, (str, bytes)):
                raise TypeError(f"MoodAssignments.{field_name} must be a sequence")
            canonical: list[str] = []
            for value in values:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("mood values must be non-blank strings")
                value = value.strip()
                if value not in canonical:
                    canonical.append(value)
            object.__setattr__(self, field_name, tuple(canonical))

    @property
    def tiers(self) -> tuple[tuple[MoodTier, tuple[str, ...]], ...]:
        """Return the complete canonical tier/value representation."""
        return (
            ("nom:mood-strict", self.strict),
            ("nom:mood-regular", self.regular),
            ("nom:mood-loose", self.loose),
        )


@dataclass(frozen=True, slots=True)
class CalibrationMoodMarker:
    """Semantic publication marker owned by the mood tag boundary."""

    status: Literal["calibrated", "uncalibrated"]
    version: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"calibrated", "uncalibrated"}:
            raise ValueError("unsupported calibration marker status")
        if self.status == "calibrated":
            if (
                self.version is None
                or len(self.version) != 32
                or any(c not in "0123456789abcdef" for c in self.version)
            ):
                raise ValueError("calibration version must be lowercase 32-hex")
        elif self.version is not None:
            raise ValueError("uncalibrated marker cannot carry a version")

    @classmethod
    def calibrated(cls, version: str) -> CalibrationMoodMarker:
        return cls("calibrated", version)

    @classmethod
    def uncalibrated(cls) -> CalibrationMoodMarker:
        return cls("uncalibrated")


@dataclass(frozen=True, slots=True)
class MoodReplacementCommand:
    """One locator-addressed mood replacement command."""

    song: SongIdentity
    assignments: MoodAssignments | None
    marker: CalibrationMoodMarker

    def __post_init__(self) -> None:
        if not isinstance(self.marker, CalibrationMoodMarker):
            raise TypeError("marker must be a CalibrationMoodMarker")


@dataclass(frozen=True, slots=True)
class MoodWriteResult:
    """Coarse redacted outcome of one mood replacement."""

    status: MoodWriteStatus
    assignment_count: int = 0

    def __post_init__(self) -> None:
        _validate_count(self.assignment_count, "assignment_count")
        if self.status not in {
            "UPDATED",
            "UNCHANGED",
            "MISSING_LOCATOR",
            "INVALID_VALUE",
            "INFRA_FAILURE",
            "AMBIGUOUS_COMMIT",
        }:
            raise ValueError("unsupported mood-write status")


@dataclass(frozen=True, slots=True)
class MoodBatchResult:
    """Coarse redacted outcome of a bounded mood batch."""

    status: MoodWriteStatus
    command_count: int = 0
    changed_count: int = 0

    def __post_init__(self) -> None:
        _validate_count(self.command_count, "command_count")
        _validate_count(self.changed_count, "changed_count")
        if self.status not in {
            "UPDATED",
            "UNCHANGED",
            "MISSING_LOCATOR",
            "INVALID_VALUE",
            "INFRA_FAILURE",
            "AMBIGUOUS_COMMIT",
        }:
            raise ValueError("unsupported mood-batch status")


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


__all__ = [
    "CalibrationMoodMarker",
    "MoodAssignments",
    "MoodBatchResult",
    "MoodReplacementCommand",
    "MoodWriteResult",
    "RelinkResult",
    "SongTagAssignment",
    "TagCleanupResult",
    "TagRef",
    "TagUsage",
]
