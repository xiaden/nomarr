# mypy: disable-error-code=func-returns-value
"""Facade identity-boundary contract tests.

Phase 3 (``TASK-song-intent-facade-correction-A``) added a typed
numeric-handle → natural-identity bridge on the song side that unblocks caller
migration onto the sealed domain tag surface:

- ``LibrarySongsDb`` / ``LibraryDb`` ``resolve_song_identity`` /
  ``resolve_song_identities`` / ``resolve_library_identity`` /
  ``resolve_library_identities`` — the song-side adapter. Resolves song/library
  storage handles to ``SongIdentity`` / ``LibraryIdentity`` natural references.
  No row, ``Song``, ``Library``, or storage id is exposed.

The root ``Database`` tag boundary resolver (``resolve_tag_identity`` /
``resolve_tag_identities``) was retired after the repo-wide caller migration
(CONTRACTS.md, "Bridge-retirement contract"): the zero-caller audit proved
safe deletion, the methods are gone, and no integer tag primary key may enter
the public tag contract. This module asserts their permanent absence and that
the natural ``library_tags`` surface alone carries the full tag intent surface,
taking only ``TagRef``/``SongIdentity`` and never an integer tag PK.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
)
from nomarr.persistence.api.library import LibraryDb
from nomarr.persistence.api.library_songs import LibrarySongsDb
from nomarr.persistence.api.library_tags import LibraryTagsDb
from nomarr.persistence.db import Database

_TEST_LIBRARY = LibraryIdentity(name="TestLib", root_path="/music")


def _make_songs_db() -> tuple[LibrarySongsDb, MagicMock, MagicMock]:
    song_repo = MagicMock()
    library_repo = MagicMock()
    songs = LibrarySongsDb(
        session=MagicMock(),
        song_repo=song_repo,
        folder_repo=MagicMock(),
        song_state_repo=MagicMock(),
        song_hydration_repo=MagicMock(),
        library_repo=library_repo,
    )
    return songs, song_repo, library_repo


def _song_row(song_id: int, library_id: int, normalized_path: str) -> dict:
    return {"id": song_id, "library_id": library_id, "normalized_path": normalized_path}


def _library_row(library_id: int, name: str, root_path: str) -> dict:
    return {"id": library_id, "name": name, "path": root_path}


@pytest.mark.unit
class TestSongIdentityBridge:
    """LibrarySongsDb song-handle → SongIdentity bridge."""

    def test_resolve_song_identity_maps_natural_key(self) -> None:
        songs, song_repo, library_repo = _make_songs_db()
        song_repo.get_songs_by_ids.return_value = [_song_row(5, 2, "a.mp3")]
        library_repo.get_libraries_by_ids.return_value = [_library_row(2, "TestLib", "/music")]
        result = songs.resolve_song_identity(5)
        assert result == SongIdentity(library=_TEST_LIBRARY, normalized_path="a.mp3")
        assert isinstance(result.library, LibraryIdentity)
        song_repo.get_songs_by_ids.assert_called_once_with([5])
        library_repo.get_libraries_by_ids.assert_called_once_with([2])

    def test_resolve_song_identities_set_based_call_counts(self) -> None:
        songs, song_repo, library_repo = _make_songs_db()
        song_repo.get_songs_by_ids.return_value = [
            _song_row(5, 2, "a.mp3"),
            _song_row(6, 2, "b.mp3"),
            _song_row(7, 3, "c.mp3"),
        ]
        library_repo.get_libraries_by_ids.return_value = [
            _library_row(2, "TestLib", "/music"),
            _library_row(3, "Other", "/other"),
        ]
        result = songs.resolve_song_identities([5, 6, 7])
        assert result[5] == SongIdentity(library=_TEST_LIBRARY, normalized_path="a.mp3")
        assert result[6] == SongIdentity(library=_TEST_LIBRARY, normalized_path="b.mp3")
        assert result[7] == SongIdentity(library=LibraryIdentity("Other", "/other"), normalized_path="c.mp3")
        # One song query + one distinct-library query for the whole batch.
        song_repo.get_songs_by_ids.assert_called_once_with([5, 6, 7])
        library_repo.get_libraries_by_ids.assert_called_once_with([2, 3])

    def test_resolve_song_identity_missing_song_returns_none(self) -> None:
        songs, song_repo, library_repo = _make_songs_db()
        song_repo.get_songs_by_ids.return_value = []
        assert songs.resolve_song_identity(999) is None
        library_repo.get_libraries_by_ids.assert_not_called()

    def test_resolve_song_identity_missing_owning_library_returns_none(self) -> None:
        songs, song_repo, library_repo = _make_songs_db()
        song_repo.get_songs_by_ids.return_value = [_song_row(5, 2, "a.mp3")]
        library_repo.get_libraries_by_ids.return_value = []
        assert songs.resolve_song_identity(5) is None

    def test_resolve_song_identities_unresolved_omitted(self) -> None:
        songs, song_repo, library_repo = _make_songs_db()
        song_repo.get_songs_by_ids.return_value = [
            _song_row(5, 2, "a.mp3"),
            _song_row(6, 999, "b.mp3"),  # owning library missing
        ]
        library_repo.get_libraries_by_ids.return_value = [_library_row(2, "TestLib", "/music")]
        result = songs.resolve_song_identities([5, 6])
        assert set(result) == {5}

    def test_resolve_song_identities_empty_batch_returns_empty(self) -> None:
        songs, song_repo, library_repo = _make_songs_db()
        assert songs.resolve_song_identities([]) == {}
        song_repo.get_songs_by_ids.assert_not_called()
        library_repo.get_libraries_by_ids.assert_not_called()

    def test_resolve_song_identity_exposes_no_storage_ids(self) -> None:
        songs, song_repo, library_repo = _make_songs_db()
        song_repo.get_songs_by_ids.return_value = [_song_row(5, 2, "a.mp3")]
        library_repo.get_libraries_by_ids.return_value = [_library_row(2, "TestLib", "/music")]
        result = songs.resolve_song_identity(5)
        assert isinstance(result, SongIdentity)
        assert isinstance(result.library, LibraryIdentity)
        # No storage PK or row shape crosses the boundary.
        assert result.library.name == "TestLib"
        assert result.library.root_path == "/music"
        assert result.normalized_path == "a.mp3"


@pytest.mark.unit
class TestLibraryIdentityBridge:
    """LibrarySongsDb library-handle → LibraryIdentity bridge."""

    def test_resolve_library_identity_maps_natural_key(self) -> None:
        songs, _, library_repo = _make_songs_db()
        library_repo.get_libraries_by_ids.return_value = [_library_row(2, "TestLib", "/music")]
        result = songs.resolve_library_identity(2)
        assert result == _TEST_LIBRARY

    def test_resolve_library_identity_missing_returns_none(self) -> None:
        songs, _, library_repo = _make_songs_db()
        library_repo.get_libraries_by_ids.return_value = []
        assert songs.resolve_library_identity(2) is None

    def test_resolve_library_identities_set_based_unresolved_omitted(self) -> None:
        songs, _, library_repo = _make_songs_db()
        library_repo.get_libraries_by_ids.return_value = [
            _library_row(2, "TestLib", "/music"),
            _library_row(4, "Three", "/three"),
        ]
        result = songs.resolve_library_identities([2, 3, 4])
        assert result == {
            2: _TEST_LIBRARY,
            4: LibraryIdentity("Three", "/three"),
        }
        library_repo.get_libraries_by_ids.assert_called_once_with([2, 3, 4])

    def test_resolve_library_identities_empty_batch_returns_empty(self) -> None:
        songs, _, library_repo = _make_songs_db()
        assert songs.resolve_library_identities([]) == {}
        library_repo.get_libraries_by_ids.assert_not_called()


@pytest.mark.unit
class TestRootTagBridgeRetired:
    """The root Database tag-PK resolver is deleted and stays absent.

    CONTRACTS.md "Bridge-retirement contract": ``Database.resolve_tag_identity``
    / ``resolve_tag_identities`` were lookup-only root-database conversions that
    accepted opaque integer tag PKs. After every caller migrated onto the
    natural facade (``TagRef`` / ``db.library.get_tag``), the zero-caller audit
    proved safe deletion. They must never reappear on ``Database`` or the tag
    facades, and the natural facade must carry the full tag intent surface.
    """

    def test_root_database_exposes_no_tag_resolver(self) -> None:
        assert not hasattr(Database, "resolve_tag_identity")
        assert not hasattr(Database, "resolve_tag_identities")

    def test_tag_facades_expose_no_tag_resolver(self) -> None:
        # The tag boundary conversion was never a LibraryTagsDb/LibraryDb method
        # or forwarder, and the natural facade must not re-add an ID-taking
        # resolver either.
        for cls in (LibraryTagsDb, LibraryDb):
            assert not hasattr(cls, "resolve_tag_identity")
            assert not hasattr(cls, "resolve_tag_identities")

    def test_natural_facade_carries_full_intent_surface(self) -> None:
        # Tag identity entry points live on the sealed natural facade only.
        for cls in (LibraryTagsDb, LibraryDb):
            assert hasattr(cls, "get_tag")
            assert hasattr(cls, "ensure_tag")
            assert hasattr(cls, "relink_tags")


@pytest.mark.unit
class TestNoFacadeTransactionApi:
    """The bridge adds no facade transaction context (AR-SDR-4)."""

    def test_song_bridge_exposes_no_transaction_api(self) -> None:
        songs, _, _ = _make_songs_db()
        assert not hasattr(songs, "transaction")
        assert not hasattr(songs, "_require_transaction")

    def test_root_database_exposes_no_transaction_api(self) -> None:
        assert not hasattr(Database, "transaction")
        assert not hasattr(Database, "_require_transaction")


@pytest.mark.unit
class TestSealedTagSurfaceNoIntegerParams:
    """The sealed tag surface takes no integer song/tag primary keys."""

    _SEALED = (
        "get_tag",
        "ensure_tag",
        "list_tags_for_song",
        "replace_song_tags",
        "remove_song_tags",
        "relink_tags",
    )

    def test_library_tags_db_methods_take_no_song_id_or_tag_id(self) -> None:
        for name in self._SEALED:
            params = inspect.signature(getattr(LibraryTagsDb, name)).parameters
            assert "song_id" not in params, f"{name} must not take song_id"
            assert "tag_id" not in params, f"{name} must not take tag_id"

    def test_library_db_tag_forwarders_take_no_song_id_or_tag_id(self) -> None:
        for name in self._SEALED:
            params = inspect.signature(getattr(LibraryDb, name)).parameters
            assert "song_id" not in params, f"{name} must not take song_id"
            assert "tag_id" not in params, f"{name} must not take tag_id"

    def test_no_compatibility_alias_or_dual_identity_path(self) -> None:
        # ID-returning / raw-edge names removed by the migration matrix have no
        # alias or dual-identity wrapper on the tag surface.
        for name in (
            "find_or_create_tag",
            "list_song_ids_for_tag_id",
            "list_song_tag_edges",
            "list_tags_by_name",
            "replace_tag_references",
            "replace_selected_tag_references",
            "search_songs_by_tag",
        ):
            assert not hasattr(LibraryTagsDb, name), f"deleted name {name} must not reappear on LibraryTagsDb"
            assert not hasattr(LibraryDb, name), f"deleted name {name} must not reappear on LibraryDb"
