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

_LIBRARY = LibraryIdentity(library_uuid="de131b32-af5c-5a84-8874-58e3dc0e2dcd", name="TestLib", root_path="/music")
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

    def test_missing_namespace_defaults_to_literal_default(self) -> None:
        assert tag_identity_from_row({"name": "artist", "value": "X"}).namespace == "default"

    def test_blank_namespace_normalizes_to_default_nom_preserved(self) -> None:
        assert tag_identity_from_row({"name": "artist", "value": "X", "namespace": ""}).namespace == "default"
        assert tag_identity_from_row({"name": "artist", "value": "X", "namespace": None}).namespace == "default"
        assert tag_identity_from_row({"name": "artist", "value": "X", "namespace": "nom"}).namespace == "nom"

    def test_never_leaks_tag_row_id(self) -> None:
        identity = tag_identity_from_row({"id": 5, "name": "artist", "value": "X", "namespace": "default"})
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

    def test_missing_and_blank_namespace_normalize_to_default(self) -> None:
        assert song_tag_assignment_from_row({"name": "artist", "value": "X"}, song=_SONG).namespace == "default"
        assert (
            song_tag_assignment_from_row({"name": "artist", "value": "X", "namespace": ""}, song=_SONG).namespace
            == "default"
        )
        assert (
            song_tag_assignment_from_row({"name": "artist", "value": "X", "namespace": "nom"}, song=_SONG).namespace
            == "nom"
        )

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

    def test_zero_confidence_is_preserved_not_defaulted(self) -> None:
        # A stored confidence of exactly 0.0 is a genuine value, not a falsy
        # sentinel: the batch mapper must preserve it rather than substituting 1.0.
        assignment = song_tag_assignment_from_batch_row(
            {
                "song_id": 7,
                "tag_id": 1,
                "tag_name": "artist",
                "tag_value": "X",
                "namespace": "nom",
                "source": "ml",
                "confidence": 0.0,
            },
            _SONG,
        )
        assert assignment.confidence == 0.0

    def test_blank_batch_namespace_normalizes_to_default(self) -> None:
        assignment = song_tag_assignment_from_batch_row(
            {"song_id": 7, "tag_id": 1, "tag_name": "artist", "tag_value": "X", "namespace": ""},
            _SONG,
        )
        assert assignment.namespace == "default"


@pytest.mark.unit
class TestSongFromRow:
    def test_maps_semantic_fields_and_drops_generated_ids(self) -> None:
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
        assert not isinstance(song, dict)
        # Generated row ids / FK ints are persistence-private and never cross.
        assert not hasattr(song, "song_id")
        assert not hasattr(song, "library_id")
        assert not hasattr(song, "folder_id")
        assert not hasattr(song, "id")
        # Semantic fields are preserved (integer booleans coerced to bool).
        assert song.normalized_path == "a.mp3"
        assert song.path == "/music/a.mp3"
        assert song.needs_tagging is True
        assert song.duration_seconds == 120.5

    def test_no_storage_serializer_on_value(self) -> None:
        song = song_from_row(
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
                "needs_tagging": 0,
                "is_valid": 1,
                "tagged": 0,
                "calibration_hash": None,
                "write_claimed_by": None,
                "last_tagged_at": None,
                "scanned_at": 1000,
                "created_at": 1000,
            }
        )
        assert isinstance(song, Song)
        assert not hasattr(song, "from_row")
        assert not hasattr(song, "to_dict")


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
        assert usage.identity == TagRef(name="artist", value="X", namespace="default")
        assert usage.song_count == 3

    def test_nom_namespace_preserved(self) -> None:
        usage = tag_usage_from_row({"id": 5, "name": "artist", "value": "X", "namespace": "nom", "song_count": 3})
        assert usage.identity == TagRef(name="artist", value="X", namespace="nom")

    def test_storage_id_not_projected(self) -> None:
        usage = tag_usage_from_row({"id": 5, "name": "artist", "value": "X", "namespace": "default", "song_count": 3})
        assert not isinstance(usage, dict)
        assert not hasattr(usage, "id")


# ---------------------------------------------------------------------------
# Phase 2 (P2-S2): association hydration isolation
#
# Prove that hydrating a song-tag association attaches the semantic owning
# SongLocator (never a storage song_id / FK) and that an association absent from
# the row is explicit (None), not fabricated from a bare row's integer song_id.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAssociationHydrationIsolation:
    def test_batch_assignment_hydrates_owning_locator_not_storage_id(self) -> None:
        # The batch row carries only a storage song_id; the mapper hydrates the
        # owning SongLocator onto the domain assignment and never lets song_id
        # (or tag_id / FK) cross.
        assignment = song_tag_assignment_from_batch_row(
            {"song_id": 7, "tag_id": 3, "tag_name": "artist", "tag_value": "X", "namespace": "nom"},
            _SONG,
        )
        assert assignment.song == _SONG
        assert isinstance(assignment.song, SongIdentity)
        assert not hasattr(assignment, "song_id")
        assert not hasattr(assignment.song, "song_id")

    def test_association_locator_is_stable_across_reload(self) -> None:
        # Re-hydrating the same owning locator from an identical song yields an
        # equal association: the semantic song association survives reload.
        first = song_tag_assignment_from_batch_row(
            {"song_id": 7, "tag_id": 3, "tag_name": "artist", "tag_value": "X", "namespace": "nom"},
            _SONG,
        )
        again = song_tag_assignment_from_batch_row(
            {"song_id": 7, "tag_id": 3, "tag_name": "artist", "tag_value": "X", "namespace": "nom"},
            _SONG,
        )
        assert again.song == first.song
        assert again.song == SongIdentity(library=_LIBRARY, normalized_path="a.mp3")

    def test_flat_assignment_without_song_is_explicit_not_fabricated(self) -> None:
        # A flat per-tag read does not know the owning song; the mapper leaves the
        # association unset rather than fabricating a locator from a bare row's
        # integer song_id. The storage song_id never becomes identity.
        assignment = song_tag_assignment_from_row({"song_id": 7, "name": "artist", "value": "X", "namespace": "nom"})
        assert assignment.song is None
        assert not hasattr(assignment, "song_id")

    def test_bare_row_storage_id_never_becomes_locator(self) -> None:
        # Even when a row carries integer FK columns, the mappers require the
        # semantic owning locator to be supplied by the caller; they never derive
        # identity from song_id/library_id.
        assignment = song_tag_assignment_from_batch_row(
            {
                "song_id": 7,
                "tag_id": 3,
                "library_id": 1,
                "tag_name": "artist",
                "tag_value": "X",
                "namespace": "nom",
            },
            _SONG,
        )
        assert assignment.song == _SONG
        assert assignment.song.library == _LIBRARY
        assert assignment.song.normalized_path == "a.mp3"
        # No row key leaks onto the value or its locator.
        assert not hasattr(assignment, "song_id")
        assert not hasattr(assignment.song, "song_id")
        assert not hasattr(assignment.song, "library_id")
