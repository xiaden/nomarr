"""Contract tests for the persistence-owned song-tag mappers.

``TASK-song-intent-facade-correction-A`` Phase 6 (P6-S2): prove that
``nomarr/persistence/mappers/song_tag_mapper.py`` converts storage rows/dicts to
domain value objects internally, so ``TagRow``/``SongRow``/raw edge shapes never
leak past the persistence facade. Assignment mapping preserves the independent
``namespace`` column plus ``confidence``/``source`` provenance (per the
song-domain-repair contracts ledger; the canonical ``tag_mapper`` drops these).
"""

from __future__ import annotations

import pytest

from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
)
from nomarr.helpers.dataclasses.song_dataclass import Song, SongTagMatch
from nomarr.helpers.dataclasses.song_tag_dataclass import (
    SongTagAssignment,
    TagRef,
    TagUsage,
)
from nomarr.persistence.mappers.song_tag_mapper import (
    song_from_row,
    song_tag_assignment_from_batch_row,
    song_tag_assignment_from_row,
    song_tag_match_from_row,
    tag_identity_from_row,
    tag_usage_from_row,
)

_LIBRARY = LibraryIdentity(name="TestLib", root_path="/music")
_SONG = SongIdentity(library=_LIBRARY, normalized_path="a.mp3")


@pytest.mark.unit
class TestTagRefFromRow:
    def test_maps_complete_natural_identity(self) -> None:
        identity = tag_identity_from_row({"name": "artist", "value": "X", "namespace": "nom"})
        assert isinstance(identity, TagRef)
        assert identity == TagRef(name="artist", value="X", namespace="nom")

    def test_value_coerced_to_string(self) -> None:
        # Tag values persist as strings in storage; the mapper coerces them.
        identity = tag_identity_from_row({"name": "year", "value": 1999, "namespace": ""})
        assert identity.value == "1999"

    def test_missing_namespace_defaults_to_empty(self) -> None:
        assert tag_identity_from_row({"name": "artist", "value": "X"}).namespace == ""

    def test_never_leaks_tag_row_id(self) -> None:
        identity = tag_identity_from_row({"id": 5, "name": "artist", "value": "X", "namespace": ""})
        assert isinstance(identity, TagRef)
        assert not isinstance(identity, dict)
        assert not hasattr(identity, "id")


@pytest.mark.unit
class TestSongTagAssignmentFromRow:
    def test_maps_assignment_with_provenance(self) -> None:
        assignment = song_tag_assignment_from_row(
            {"name": "artist", "value": "X", "namespace": "nom", "confidence": 0.9, "source": "ml"},
            song=_SONG,
        )
        assert isinstance(assignment, SongTagAssignment)
        assert assignment.name == "artist"
        assert assignment.value == "X"
        assert assignment.namespace == "nom"
        assert assignment.confidence == 0.9
        assert assignment.source == "ml"
        assert assignment.song == _SONG

    def test_defaults_confidence_and_source(self) -> None:
        assignment = song_tag_assignment_from_row(
            {"name": "artist", "value": "X"},
            song=_SONG,
        )
        assert assignment.confidence == 1.0
        assert assignment.source == "nomarr"

    def test_zero_confidence_is_preserved_not_defaulted(self) -> None:
        # A stored confidence of exactly 0.0 is a genuine value, not a falsy
        # sentinel: the mapper must preserve it rather than substituting 1.0.
        assignment = song_tag_assignment_from_row(
            {"name": "artist", "value": "X", "namespace": "nom", "confidence": 0.0},
            song=_SONG,
        )
        assert assignment.confidence == 0.0

    def test_song_handle_optional_for_flat_reads(self) -> None:
        assignment = song_tag_assignment_from_row({"name": "artist", "value": "X"})
        assert assignment.song is None

    def test_returns_domain_value_not_row_dict(self) -> None:
        assignment = song_tag_assignment_from_row({"name": "artist", "value": "X"})
        assert isinstance(assignment, SongTagAssignment)
        assert not isinstance(assignment, dict)


@pytest.mark.unit
class TestSongTagAssignmentFromBatchRow:
    def test_maps_batch_row_shape_with_owning_song(self) -> None:
        assignment = song_tag_assignment_from_batch_row(
            {
                "song_id": 7,
                "tag_id": 1,
                "tag_name": "artist",
                "tag_value": "X",
                "namespace": "nom",
                "source": "nomarr",
                "confidence": 0.8,
            },
            _SONG,
        )
        assert isinstance(assignment, SongTagAssignment)
        assert assignment.name == "artist"
        assert assignment.value == "X"
        assert assignment.namespace == "nom"
        assert assignment.song == _SONG
        assert assignment.confidence == 0.8
        # The storage song_id stays internal to the row; never crosses.
        assert not hasattr(assignment, "song_id")


@pytest.mark.unit
class TestSongFromRow:
    def test_delegates_to_domain_song_projection(self) -> None:
        song = song_from_row(
            {
                "id": 10,
                "library_id": 1,
                "folder_id": None,
                "path": "/music/a.mp3",
                "normalized_path": "a.mp3",
                "file_size": 100,
                "modified_time": 1000,
                "duration_seconds": 120.5,
                "chromaprint": None,
                "needs_tagging": 1,
                "is_valid": 1,
                "tagged": 1,
                "calibration_hash": None,
                "write_claimed_by": None,
                "last_tagged_at": None,
                "scanned_at": 1000,
                "created_at": 1000,
            }
        )
        assert isinstance(song, Song)
        assert song.song_id == 10
        assert song.normalized_path == "a.mp3"
        assert not isinstance(song, dict)


@pytest.mark.unit
class TestSongTagMatchFromRow:
    def test_maps_domain_song_match(self) -> None:
        match = song_tag_match_from_row(
            {
                "id": 10,
                "library_id": 1,
                "folder_id": None,
                "path": "/music/a.mp3",
                "normalized_path": "a.mp3",
                "file_size": 100,
                "modified_time": 1000,
                "duration_seconds": None,
                "chromaprint": None,
                "needs_tagging": 1,
                "is_valid": 1,
                "tagged": 1,
                "calibration_hash": None,
                "write_claimed_by": None,
                "last_tagged_at": None,
                "scanned_at": 1000,
                "created_at": 1000,
                "matched_tag": "artist",
                "distance": 0.0,
            }
        )
        assert isinstance(match, SongTagMatch)
        assert isinstance(match.song, Song)
        assert match.matched_tag == "artist"
        assert match.distance == 0.0


@pytest.mark.unit
class TestTagUsageFromRow:
    def test_maps_identity_and_count(self) -> None:
        usage = tag_usage_from_row({"id": 5, "name": "artist", "value": "X", "namespace": "", "song_count": 3})
        assert isinstance(usage, TagUsage)
        assert usage.identity == TagRef(name="artist", value="X", namespace="")
        assert usage.song_count == 3

    def test_storage_id_not_projected(self) -> None:
        usage = tag_usage_from_row({"id": 5, "name": "artist", "value": "X", "namespace": "", "song_count": 3})
        assert not isinstance(usage, dict)
        assert not hasattr(usage, "id")
