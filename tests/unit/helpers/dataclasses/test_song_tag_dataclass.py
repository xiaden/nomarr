"""Unit tests for the song/tag domain value objects.

``TASK-song-intent-facade-correction-A`` Phase 6 (P6-S1): prove the frozen/slotted
domain value objects that replace the persistence row/edge shapes at the tag
facade boundary. These value objects carry no database identifiers, table
metadata, or storage row shapes — see
``nomarr/helpers/dataclasses/song_tag_dataclass.py``.

Contract under test (per the song-domain-repair contracts ledger, 2026-08-30):
- ``TagRef(name, value, namespace)`` — complete tag natural key.
- ``SongTagAssignment`` — the domain association, carrying a domain ``song``
  handle (never a storage ``song_id``).
- ``TagUsage``, ``RelinkResult``, ``TagCleanupResult`` — typed domain results.
- Song natural identity is ``SongIdentity(library: LibraryIdentity,
  normalized_path)`` (ADR-043).
"""

from __future__ import annotations

import pytest

from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
)
from nomarr.helpers.dataclasses.song_tag_dataclass import (
    RelinkResult,
    SongTagAssignment,
    TagCleanupResult,
    TagRef,
    TagUsage,
)

_LIBRARY = LibraryIdentity(name="TestLib", root_path="/music")


def _song(path: str = "a.mp3") -> SongIdentity:
    return SongIdentity(library=_LIBRARY, normalized_path=path)


# ── TagRef ──────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestTagRef:
    def test_is_frozen_and_slotted(self) -> None:
        identity = TagRef(name="artist", value="X")
        with pytest.raises(AttributeError):
            identity.name = "genre"  # type: ignore[misc]
        assert not hasattr(identity, "__dict__")

    def test_equality_by_value(self) -> None:
        assert TagRef("artist", "X") == TagRef("artist", "X")
        assert TagRef("artist", "X") != TagRef("artist", "Y")
        assert TagRef("artist", "X", "nom") != TagRef("artist", "X", "")

    def test_namespace_defaults_to_empty_string(self) -> None:
        assert TagRef("artist", "X").namespace == ""

    def test_blank_name_rejected(self) -> None:
        with pytest.raises(ValueError):
            TagRef(name="   ", value="X")
        with pytest.raises(ValueError):
            TagRef(name="", value="X")

    def test_namespace_must_be_string(self) -> None:
        with pytest.raises(TypeError):
            TagRef(name="artist", value="X", namespace=123)  # type: ignore[arg-type]

    def test_value_accepts_scalar_tag_values(self) -> None:
        # TagValue = str | int | float | bool
        assert TagRef("year", 1999).value == 1999
        assert TagRef("rating", 4.5).value == 4.5
        assert TagRef("compilation", True).value is True


# ── SongTagAssignment ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSongTagAssignment:
    def test_is_frozen_and_slotted(self) -> None:
        assignment = SongTagAssignment(name="artist", value="X")
        with pytest.raises(AttributeError):
            assignment.name = "genre"  # type: ignore[misc]
        assert not hasattr(assignment, "__dict__")

    def test_equality_by_value(self) -> None:
        assert SongTagAssignment("artist", "X") == SongTagAssignment("artist", "X")
        assert SongTagAssignment("artist", "X") != SongTagAssignment("artist", "Y")

    def test_defaults_confidence_source_and_song(self) -> None:
        assignment = SongTagAssignment(name="artist", value="X")
        assert assignment.confidence == 1.0
        assert assignment.source == "nomarr"
        assert assignment.song is None
        assert assignment.namespace == ""

    def test_identity_property_returns_persistence_free_tag_identity(self) -> None:
        assignment = SongTagAssignment(name="artist", value="X", namespace="nom")
        assert assignment.identity == TagRef(name="artist", value="X", namespace="nom")

    def test_blank_name_rejected(self) -> None:
        with pytest.raises(ValueError):
            SongTagAssignment(name="", value="X")

    def test_namespace_must_be_string(self) -> None:
        with pytest.raises(TypeError):
            SongTagAssignment(name="artist", value="X", namespace=1)  # type: ignore[arg-type]

    def test_confidence_must_be_numeric_and_reject_bool(self) -> None:
        SongTagAssignment(name="artist", value="X", confidence=0.5)
        SongTagAssignment(name="artist", value="X", confidence=1)
        with pytest.raises(TypeError):
            SongTagAssignment(name="artist", value="X", confidence="high")  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            SongTagAssignment(name="artist", value="X", confidence=True)  # type: ignore[arg-type]

    def test_source_must_be_non_empty_string(self) -> None:
        with pytest.raises(ValueError):
            SongTagAssignment(name="artist", value="X", source="")

    def test_carries_domain_song_handle_never_storage_id(self) -> None:
        song = _song()
        assignment = SongTagAssignment(name="artist", value="X", song=song)
        assert assignment.song == song
        assert isinstance(assignment.song, SongIdentity)
        assert not hasattr(assignment, "song_id")


# ── Song natural identity ────────────────────────────────────────────────────


@pytest.mark.unit
class TestSongNaturalIdentity:
    def test_song_identity_is_library_identity_plus_normalized_path(self) -> None:
        song = _song("a.mp3")
        assert song.library == _LIBRARY
        assert isinstance(song.library, LibraryIdentity)
        assert song.normalized_path == "a.mp3"

    def test_song_identity_rejects_non_library_reference(self) -> None:
        with pytest.raises(TypeError):
            SongIdentity(library=123, normalized_path="a.mp3")  # type: ignore[arg-type]

    def test_song_identity_rejects_blank_normalized_path(self) -> None:
        with pytest.raises(ValueError):
            SongIdentity(library=_LIBRARY, normalized_path="")

    def test_song_identity_equality(self) -> None:
        assert _song("a.mp3") == SongIdentity(library=_LIBRARY, normalized_path="a.mp3")
        assert _song("a.mp3") != _song("b.mp3")

    def test_library_identity_validation(self) -> None:
        with pytest.raises(ValueError):
            LibraryIdentity(name="", root_path="/music")
        with pytest.raises(ValueError):
            LibraryIdentity(name="TestLib", root_path="")


# ── TagUsage ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestTagUsage:
    def test_is_frozen_and_slotted(self) -> None:
        usage = TagUsage(identity=TagRef("artist", "X"), song_count=3)
        with pytest.raises(AttributeError):
            usage.song_count = 4  # type: ignore[misc]
        assert not hasattr(usage, "__dict__")

    def test_equality_by_value(self) -> None:
        u1 = TagUsage(identity=TagRef("artist", "X"), song_count=3)
        u2 = TagUsage(identity=TagRef("artist", "X"), song_count=3)
        assert u1 == u2

    def test_song_count_must_be_non_negative_int(self) -> None:
        with pytest.raises(TypeError):
            TagUsage(identity=TagRef("artist", "X"), song_count=3.5)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            TagUsage(identity=TagRef("artist", "X"), song_count=-1)
        with pytest.raises(TypeError):
            TagUsage(identity=TagRef("artist", "X"), song_count=True)  # type: ignore[arg-type]


# ── RelinkResult / TagCleanupResult ──────────────────────────────────────────


@pytest.mark.unit
class TestRelinkResult:
    def test_counts_are_non_negative_ints(self) -> None:
        result = RelinkResult(moved=2, skipped=1, source_orphaned=0)
        assert (result.moved, result.skipped, result.source_orphaned) == (2, 1, 0)
        # Both negative and non-int counts raise TypeError per the dataclass.
        with pytest.raises(TypeError):
            RelinkResult(moved=-1, skipped=0, source_orphaned=0)
        with pytest.raises(TypeError):
            RelinkResult(moved=1.5, skipped=0, source_orphaned=0)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            RelinkResult(moved=True, skipped=0, source_orphaned=0)  # type: ignore[arg-type]

    def test_equality_and_frozen(self) -> None:
        assert RelinkResult(1, 0, 0) == RelinkResult(1, 0, 0)
        with pytest.raises(AttributeError):
            RelinkResult(1, 0, 0).moved = 9  # type: ignore[misc]


@pytest.mark.unit
class TestTagCleanupResult:
    def test_counts_are_non_negative_ints(self) -> None:
        result = TagCleanupResult(deleted=4, orphaned=7)
        assert (result.deleted, result.orphaned) == (4, 7)
        with pytest.raises(TypeError):
            TagCleanupResult(deleted=-1, orphaned=0)
        with pytest.raises(TypeError):
            TagCleanupResult(deleted=4.0, orphaned=0)  # type: ignore[arg-type]

    def test_zero_result_semantics(self) -> None:
        assert TagCleanupResult(deleted=0, orphaned=0) == TagCleanupResult(deleted=0, orphaned=0)


# ── Empty-result semantics at the assignment/usage boundaries ────────────────


@pytest.mark.unit
class TestEmptyResultSemantics:
    def test_zero_song_count_usage_is_valid(self) -> None:
        assert TagUsage(identity=TagRef("artist", "X"), song_count=0).song_count == 0

    def test_zero_relink_counts_are_valid(self) -> None:
        assert RelinkResult(moved=0, skipped=0, source_orphaned=0) is not None

    def test_assignment_without_song_handle_is_a_flat_read_value(self) -> None:
        # Flat reads do not attribute each assignment back to a song.
        flat = SongTagAssignment(name="artist", value="X")
        assert flat.song is None
        assert flat.identity == TagRef(name="artist", value="X")
