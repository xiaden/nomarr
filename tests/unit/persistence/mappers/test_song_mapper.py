"""Contract tests for the persistence-private song row mappers.

``TASK-song-row-mirror-leaks-into-domain-B`` Phase 1 (P1-S2/P1-S3): prove that
``nomarr/persistence/mappers/song_mapper.py`` converts persistence ``SongRow``
mappings to a semantic application :class:`Song` and to the natural
:class:`SongIdentity` locator, and that generated row ids / foreign keys /
storage serialization never cross the persistence boundary. Row fixtures appear
only in persistence mapper tests (CONTRACTS §2).
"""

from __future__ import annotations

from typing import Any

import pytest

from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
)
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.persistence.mappers.song_mapper import (
    song_row_to_domain,
    song_row_to_identity,
)


def _song_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
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
    row.update(overrides)
    return row


@pytest.mark.unit
class TestSongRowToDomain:
    def test_maps_semantic_fields_and_drops_generated_ids(self) -> None:
        song = song_row_to_domain(_song_row())
        assert isinstance(song, Song)
        assert not isinstance(song, dict)
        # Generated row id / FK ints stay persistence-private.
        assert not hasattr(song, "song_id")
        assert not hasattr(song, "id")
        assert not hasattr(song, "library_id")
        assert not hasattr(song, "folder_id")
        # Physical path and library-relative locator path are both preserved.
        assert song.path == "/music/a.mp3"
        assert song.normalized_path == "a.mp3"
        # Integer booleans are coerced to bool.
        assert song.needs_tagging is True
        assert song.is_valid is True
        assert song.tagged is True

    def test_preserves_nullable_values_and_false_booleans(self) -> None:
        song = song_row_to_domain(
            _song_row(
                folder_id=5,
                duration_seconds=None,
                chromaprint="fingerprint",
                needs_tagging=0,
                is_valid=0,
                tagged=0,
                write_claimed_by="worker-1",
                last_tagged_at=2000,
            )
        )
        # folder FK is never surfaced (no folder_id attribute exists).
        assert not hasattr(song, "folder_id")
        assert song.duration_seconds is None
        assert song.chromaprint == "fingerprint"
        assert song.needs_tagging is False
        assert song.is_valid is False
        assert song.tagged is False
        assert song.write_claimed_by == "worker-1"
        assert song.last_tagged_at == 2000

    def test_preserves_integer_millisecond_timestamps(self) -> None:
        song = song_row_to_domain(_song_row())
        assert song.modified_time == 1000
        assert song.scanned_at == 1000
        assert song.created_at == 1000
        assert isinstance(song.modified_time, int)

    def test_value_has_no_storage_constructor_or_serializer(self) -> None:
        song = song_row_to_domain(_song_row())
        assert not hasattr(song, "from_row")
        assert not hasattr(song, "to_dict")


@pytest.mark.unit
class TestSongRowToIdentity:
    _LIBRARY = LibraryIdentity(library_uuid="de131b32-af5c-5a84-8874-58e3dc0e2dcd", name="TestLib", root_path="/music")

    def test_builds_locator_from_library_scoped_row(self) -> None:
        identity = song_row_to_identity(
            _song_row(library_uuid="de131b32-af5c-5a84-8874-58e3dc0e2dcd", library_name="TestLib", root_path="/music")
        )
        assert isinstance(identity, SongIdentity)
        assert identity.library == self._LIBRARY
        assert identity.normalized_path == "a.mp3"

    def test_root_path_optional(self) -> None:
        identity = song_row_to_identity(
            _song_row(library_uuid="08042357-9a97-5066-a9bf-bcab3b77ec8b", library_name="TestLib")
        )
        assert identity.library == LibraryIdentity(library_uuid="08042357-9a97-5066-a9bf-bcab3b77ec8b", name="TestLib")
        assert identity.normalized_path == "a.mp3"

    def test_bare_song_row_without_library_uuid_raises(self) -> None:
        # A raw SongRow carries only the private library_id; it cannot form a
        # SongIdentity. Failure is deterministic and leak-free.
        with pytest.raises(ValueError, match="library UUID"):
            song_row_to_identity(_song_row())

    def test_blank_normalized_path_raises(self) -> None:
        with pytest.raises(ValueError, match="normalized_path"):
            song_row_to_identity(_song_row(normalized_path="  ", library_uuid="de131b32-af5c-5a84-8874-58e3dc0e2dcd"))


# ---------------------------------------------------------------------------
# Phase 2 (P2-S2): mapper isolation
#
# Prove the row->domain / row->locator mappers are isolated from storage shape
# changes and from storage identity: column changes never surface on the value,
# null/malformed rows behave deterministically, path normalization keeps the
# physical path distinct from the locator path, and a row lacking library
# hydration fails without disclosing a SQL table, column, or foreign key.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMapperIsolationColumnChanges:
    def test_extra_storage_column_never_surfaces_on_domain(self) -> None:
        # A songs-table column (e.g. a future audio_codec / mime_type) is a
        # row-level detail; the mapper reads only the known semantic keys and
        # never lets new storage columns leak onto the Song value.
        song = song_row_to_domain(_song_row(audio_codec="aac", mime_type="audio/mpeg"))
        assert isinstance(song, Song)
        assert not hasattr(song, "audio_codec")
        assert not hasattr(song, "mime_type")
        assert not hasattr(song, "id")
        assert not hasattr(song, "song_id")
        assert song.path == "/music/a.mp3"

    def test_removed_required_column_fails_deterministically(self) -> None:
        # A renamed/removed required column is a real defect and must never be
        # silently defaulted: the mapper raises a plain KeyError naming the key.
        row = _song_row()
        del row["normalized_path"]
        with pytest.raises(KeyError):
            song_row_to_domain(row)

    def test_int_vs_bool_column_representation_is_normalized(self) -> None:
        # Integer booleans (1/0) and native bools both normalize to bool, so a
        # storage representation change cannot change the semantic contract.
        from_int = song_row_to_domain(_song_row(needs_tagging=1, is_valid=1, tagged=1))
        from_bool = song_row_to_domain(_song_row(needs_tagging=True, is_valid=True, tagged=True))
        assert from_int.needs_tagging is True
        assert from_int.is_valid is True
        assert from_int.tagged is True
        assert from_int.needs_tagging == from_bool.needs_tagging


@pytest.mark.unit
class TestMapperIsolationNullAndMalformed:
    def test_nullable_values_preserved_as_none(self) -> None:
        song = song_row_to_domain(
            _song_row(
                duration_seconds=None,
                chromaprint=None,
                calibration_hash=None,
                write_claimed_by=None,
                last_tagged_at=None,
                scanned_at=None,
            )
        )
        assert song.duration_seconds is None
        assert song.chromaprint is None
        assert song.calibration_hash is None
        assert song.write_claimed_by is None
        assert song.last_tagged_at is None
        assert song.scanned_at is None

    def test_malformed_row_missing_required_key_raises(self) -> None:
        # A malformed row (missing a required non-nullable column) is surfaced as
        # a deterministic KeyError, never coerced to a fabricated default.
        row = _song_row()
        del row["path"]
        with pytest.raises(KeyError):
            song_row_to_domain(row)

    def test_blank_identity_path_is_rejected_not_defaulted(self) -> None:
        # An identity cannot be hydrated from a blank normalized_path; the mapper
        # fails loudly rather than inventing a fallback path.
        with pytest.raises(ValueError, match="normalized_path"):
            song_row_to_identity(_song_row(normalized_path="", library_uuid="de131b32-af5c-5a84-8874-58e3dc0e2dcd"))


@pytest.mark.unit
class TestMapperIsolationPathNormalization:
    def test_physical_path_and_locator_path_stay_distinct(self) -> None:
        # absolute physical path and library-relative normalized_path are two
        # different maintained details; neither is collapsed into the other.
        song = song_row_to_domain(_song_row(path="/music/sub/dir/a.mp3", normalized_path="dir/a.mp3"))
        assert song.path == "/music/sub/dir/a.mp3"
        assert song.normalized_path == "dir/a.mp3"

    def test_locator_uses_normalized_path_not_physical_path(self) -> None:
        # Two songs at the same physical path but different library roots (hence
        # different normalized paths) are different locators: the physical path
        # is not global Song identity (ADR-048).
        loc_a = song_row_to_identity(
            _song_row(path="/m/a.mp3", normalized_path="a.mp3", library_uuid="de131b32-af5c-5a84-8874-58e3dc0e2dcd")
        )
        loc_b = song_row_to_identity(
            _song_row(path="/m/a.mp3", normalized_path="other.mp3", library_uuid="de131b32-af5c-5a84-8874-58e3dc0e2dcd")
        )
        assert loc_a.library == loc_b.library
        assert loc_a.normalized_path != loc_b.normalized_path

    def test_same_normalized_path_in_different_libraries_is_distinct(self) -> None:
        loc_a = song_row_to_identity(
            _song_row(normalized_path="a.mp3", library_uuid="de131b32-af5c-5a84-8874-58e3dc0e2dcd")
        )
        loc_b = song_row_to_identity(
            _song_row(normalized_path="a.mp3", library_uuid="b0da3722-b47b-50ca-abb5-21927059a411")
        )
        assert loc_a != loc_b
        assert loc_a.library.library_uuid != loc_b.library.library_uuid


@pytest.mark.unit
class TestDeterministicFailureNoDisclosure:
    def test_bare_row_identity_error_discloses_no_sql_table_or_fk(self) -> None:
        # A bare SongRow (only the private library_id) cannot form a locator. The
        # failure is deterministic and leak-free: the message names the missing
        # enrichment key but never a table, generated column, or foreign key.
        with pytest.raises(ValueError) as excinfo:
            song_row_to_identity(_song_row())
        message = str(excinfo.value)
        assert "library_uuid" in message
        for disclosure in ("songs", "library_id", "folder_id", "song_id", " SELECT ", "foreign key", "FK "):
            assert disclosure.lower() not in message.lower()


# ---------------------------------------------------------------------------
# Phase 2 (P2-S3): semantic hydration
#
# Prove SongLocator/domain values survive a reload (deterministic re-derivation
# from an identical row) and that missing hydration is explicit — never a hidden
# locator-history, alias, tombstone, or integer-ID fallback (ADR-048 §2).
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSemanticHydrationSurvivesReload:
    def test_domain_values_and_locator_survive_reload(self) -> None:
        row = _song_row(library_uuid="de131b32-af5c-5a84-8874-58e3dc0e2dcd", library_name="TestLib", root_path="/music")
        first_domain = song_row_to_domain(row)
        first_locator = song_row_to_identity(row)
        # The domain Song and its locator agree on the library-relative path.
        assert first_domain.normalized_path == first_locator.normalized_path
        assert first_domain.path == "/music/a.mp3"
        # A reload of an identical row deterministically re-derives equal values
        # (no hidden state, no generated id, no mutation between reads).
        reload_domain = song_row_to_domain(
            _song_row(library_uuid="de131b32-af5c-5a84-8874-58e3dc0e2dcd", library_name="TestLib", root_path="/music")
        )
        reload_locator = song_row_to_identity(
            _song_row(library_uuid="de131b32-af5c-5a84-8874-58e3dc0e2dcd", library_name="TestLib", root_path="/music")
        )
        assert reload_domain == first_domain
        assert reload_locator == first_locator
        assert reload_domain.needs_tagging is True
        assert reload_locator.library == LibraryIdentity(
            library_uuid="de131b32-af5c-5a84-8874-58e3dc0e2dcd", name="TestLib", root_path="/music"
        )

    def test_domain_and_locator_pair_without_storage_id(self) -> None:
        # The semantic read value (Song) plus the locator together fully describe
        # a reloaded song; neither carries songs.id/library_id/folder_id.
        row = _song_row(library_uuid="de131b32-af5c-5a84-8874-58e3dc0e2dcd", library_name="TestLib")
        song = song_row_to_domain(row)
        locator = song_row_to_identity(row)
        assert (song.normalized_path, song.path) == (locator.normalized_path, "/music/a.mp3")
        for value in (song, locator):
            for leak in ("song_id", "id", "library_id", "folder_id"):
                assert not hasattr(value, leak)

    def test_missing_hydration_is_explicit_no_locator_fallback(self) -> None:
        # A semantic Song carries no library scope, so a locator cannot be derived
        # from it alone. Hydrating the locator requires the owning library UUID;
        # its absence is an explicit deterministic error — not a lookup, integer
        # fallback, or silently-unscoped default.
        song = song_row_to_domain(_song_row())
        assert not hasattr(song, "library_id")
        assert not hasattr(song, "root_path")
        assert not hasattr(song, "from_row")
        with pytest.raises(ValueError, match="library UUID"):
            song_row_to_identity(_song_row())  # bare row, no library enrichment

    def test_no_locator_history_alias_tombstone_or_stable_id(self) -> None:
        # ADR-048 §2: no alias, tombstone, locator history, or stable-id fallback
        # exists on the locator or on the domain value.
        locator = song_row_to_identity(
            _song_row(normalized_path="a.mp3", library_uuid="de131b32-af5c-5a84-8874-58e3dc0e2dcd")
        )
        song = song_row_to_domain(_song_row())
        for value in (song, locator):
            for forbidden in ("history", "alias", "tombstone", "stable_id", "previous", "song_id"):
                assert not hasattr(value, forbidden)
