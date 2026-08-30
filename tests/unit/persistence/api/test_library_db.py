# mypy: disable-error-code=func-returns-value
"""Unit tests for ``LibraryDb`` delegation to the four sub-facades.

Rewritten in Phase 6 of ``TASK-song-intent-facade-correction-A`` to the sealed
domain contracts (per ADR-032/041/043 and the song-domain-repair ledger):

- Library-facing methods accept/return ``Library`` / ``LibraryUpdate`` /
  ``LibraryPipelineState`` / ``LibraryFolder`` / ``LibraryScan`` domain values;
  storage ``id``/``library_id``/row shapes never cross the facade.
- Tag-facing methods accept/return ``TagRef`` / ``SongTagAssignment`` /
  ``TagUsage`` / ``RelinkResult`` / ``TagCleanupResult``; song identity is the
  natural ``SongIdentity`` (never a PostgreSQL ``song_id``).
- The identity bridge (``resolve_song_identity``/``resolve_library_identity``)
  is the documented int→natural-identity conversion point.
"""

from __future__ import annotations

from unittest.mock import MagicMock, sentinel

import pytest

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.library_domain_dataclasses import (
    LibraryFolder,
    LibraryPipelineState,
    LibraryScan,
    LibraryUpdate,
)
from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
)
from nomarr.helpers.dataclasses.song_dataclass import Song, SongTagMatch
from nomarr.helpers.dataclasses.song_tag_dataclass import (
    RelinkResult,
    SongTagAssignment,
    TagCleanupResult,
    TagRef,
    TagUsage,
)
from nomarr.persistence.api.library import LibraryDb
from nomarr.persistence.api.library_regions import LibraryRegionsDb
from nomarr.persistence.api.library_scans import LibraryScansDb
from nomarr.persistence.api.library_songs import LibrarySongsDb
from nomarr.persistence.api.library_tags import LibraryTagsDb

# ── helpers ───────────────────────────────────────────────────────────────


_SONG_ROW: dict = {
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

_LIBRARY_ROW: dict = {
    "id": 1,
    "name": "TestLib",
    "path": "/music",
    "library_type": "music",
    "watch_mode": "off",
    "file_write_mode": "full",
    "auto_tag": 0,
    "auto_curate": 0,
    "created_at": 1,
    "updated_at": 1,
}


def _song_row() -> dict:
    return dict(_SONG_ROW)


def _library_row() -> dict:
    return dict(_LIBRARY_ROW)


def _make_library_db() -> tuple[
    LibraryDb,
    MagicMock,
    MagicMock,
    MagicMock,
    MagicMock,
    MagicMock,
    MagicMock,
    MagicMock,
    MagicMock,
]:
    library_repo = MagicMock()
    song_repo = MagicMock()
    folder_repo = MagicMock()
    scan_repo = MagicMock()
    tag_repo = MagicMock()
    song_tag_repo = MagicMock()
    song_state_repo = MagicMock()
    pipeline_repo = MagicMock()
    # Default natural-key resolution for the canonical _LIB: library -> id 1.
    library_repo.get_library_by_natural_key.return_value = {"id": 1}
    library_repo.get_library_ids_by_natural_keys.return_value = {("TestLib", "/music"): 1}
    songs = LibrarySongsDb(
        session=MagicMock(),
        song_repo=song_repo,
        folder_repo=folder_repo,
        song_state_repo=song_state_repo,
        song_hydration_repo=MagicMock(),
        library_repo=library_repo,
    )
    tags = LibraryTagsDb(
        session=MagicMock(),
        tag_repo=tag_repo,
        song_tag_repo=song_tag_repo,
        song_repo=song_repo,
        library_repo=library_repo,
    )
    scans = LibraryScansDb(session=MagicMock(), scan_repo=scan_repo, library_repo=library_repo)
    regions = LibraryRegionsDb(
        session=MagicMock(),
        library_repo=library_repo,
        song_state_repo=song_state_repo,
        pipeline_repo=pipeline_repo,
    )
    db = LibraryDb(
        session=MagicMock(),
        songs=songs,
        tags=tags,
        scans=scans,
        regions=regions,
    )
    return (
        db,
        library_repo,
        song_repo,
        folder_repo,
        scan_repo,
        tag_repo,
        song_tag_repo,
        song_state_repo,
        pipeline_repo,
    )


_TEST_LIBRARY = LibraryIdentity(name="TestLib", root_path="/music")
_LIB = Library(name="TestLib", root_path="/music")


def _song(normalized_path: str = "a.mp3") -> SongIdentity:
    return SongIdentity(library=_TEST_LIBRARY, normalized_path=normalized_path)


def _tag(name: str = "artist", value: str = "X", namespace: str = "") -> TagRef:
    return TagRef(name=name, value=value, namespace=namespace)


def _assignment(**overrides: object) -> SongTagAssignment:
    base: dict = {
        "name": "artist",
        "value": "X",
        "namespace": "",
        "confidence": 1.0,
        "source": "nomarr",
        "song": None,
    }
    base.update(overrides)
    return SongTagAssignment(**base)  # type: ignore[arg-type]


# ── surface / contract ────────────────────────────────────────────────────


@pytest.mark.unit
def test_exposes_library_maintenance_surface() -> None:
    db, _, song_repo, folder_repo, _, tag_repo, song_tag_repo, _, _ = _make_library_db()

    # Four sub-facade namespaces are exposed with the right types
    assert isinstance(db.songs, LibrarySongsDb)
    assert isinstance(db.tags, LibraryTagsDb)
    assert isinstance(db.scans, LibraryScansDb)
    assert isinstance(db.regions, LibraryRegionsDb)

    # Maintenance surface is forwarded at the LibraryDb top level; legacy
    # storage-id maintenance methods (delete_tags_by_ids / list_orphaned_tag_ids)
    # are removed per the song-tag hard-cut.
    assert hasattr(db, "list_orphaned_song_ids")
    assert hasattr(db, "cleanup_orphaned_tags")
    assert not hasattr(db, "delete_tags_by_ids")
    assert not hasattr(db, "list_orphaned_tag_ids")
    assert not hasattr(db, "list_song_tag_edges")
    assert not hasattr(db, "list_song_ids_for_tag_id")
    assert hasattr(db, "truncate_songs")
    assert hasattr(db, "truncate_song_links")
    assert hasattr(db, "truncate_folder_links")
    assert hasattr(db, "truncate_folders")
    assert hasattr(db, "truncate_tags")
    assert hasattr(db, "truncate_song_tag_assignments")
    assert hasattr(db, "truncate_scan_records")

    # Forwarders route to the correct sub-facade repo
    db.list_orphaned_song_ids()
    song_repo.list_orphaned_song_ids.assert_called_once_with()

    tag_repo.get_orphaned_tag_ids = MagicMock(return_value=[])
    db.cleanup_orphaned_tags()
    tag_repo.get_orphaned_tag_ids.assert_called_once_with()

    db.truncate_songs()
    song_repo.truncate_songs.assert_called_once_with()

    db.truncate_song_links()
    song_repo.truncate_song_links.assert_called_once_with()

    db.truncate_folder_links()
    folder_repo.truncate_folder_links.assert_called_once_with()

    db.truncate_folders()
    folder_repo.truncate_folders.assert_called_once_with()

    db.truncate_tags()
    tag_repo.truncate_tags.assert_called_once_with()

    db.truncate_song_tag_assignments()
    song_tag_repo.truncate_song_tag_assignments.assert_called_once_with()

    # LibraryMaintenanceDb no longer exists
    import nomarr.persistence.api.library as library_module

    assert not hasattr(library_module, "LibraryMaintenanceDb")


# ── Library CRUD ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_create_library_delegates_and_returns_domain() -> None:
    db, library_repo, *_ = _make_library_db()
    library_repo.add_library = MagicMock(return_value=42)
    row = _library_row()
    row["name"] = "main"
    library_repo.get_library = MagicMock(return_value=row)

    result = db.create_library(Library(name="main", root_path="/music"))

    assert isinstance(result, Library)
    assert result.name == "main"
    assert result.root_path == "/music"
    library_repo.add_library.assert_called_once()
    payload = library_repo.add_library.call_args.args[0]
    assert payload["name"] == "main"
    assert payload["path"] == "/music"
    assert payload["library_type"] == "music"
    # Persistence supplies timestamps when absent (ADR-032).
    assert payload["created_at"] is not None
    assert payload["updated_at"] is not None


@pytest.mark.unit
def test_get_library_delegates() -> None:
    db, library_repo, *_ = _make_library_db()
    library_repo.get_library_by_natural_key = MagicMock(return_value={"id": 1})
    library_repo.get_library = MagicMock(return_value=_library_row())

    result = db.get_library(_LIB)

    assert isinstance(result, Library)
    assert result.name == "TestLib"
    assert result.root_path == "/music"
    library_repo.get_library_by_natural_key.assert_called_once_with("TestLib", "/music")
    library_repo.get_library.assert_called_once_with(1)


@pytest.mark.unit
def test_get_library_returns_none_when_missing() -> None:
    db, library_repo, *_ = _make_library_db()
    library_repo.get_library_by_natural_key = MagicMock(return_value=None)

    result = db.get_library(_LIB)

    assert result is None
    library_repo.get_library.assert_not_called()


@pytest.mark.unit
def test_get_library_by_name_delegates() -> None:
    db, library_repo, *_ = _make_library_db()
    library_repo.get_library_by_name = MagicMock(return_value=_library_row())

    result = db.get_library_by_name("TestLib")

    assert isinstance(result, Library)
    assert result.name == "TestLib"
    library_repo.get_library_by_name.assert_called_once_with("TestLib")


@pytest.mark.unit
def test_list_libraries_delegates() -> None:
    db, library_repo, *_ = _make_library_db()
    library_repo.list_libraries = MagicMock(return_value=[_library_row()])

    result = db.list_libraries()

    assert len(result) == 1
    assert isinstance(result[0], Library)
    library_repo.list_libraries.assert_called_once_with(enabled_only=False)


@pytest.mark.unit
def test_update_library_delegates() -> None:
    db, library_repo, *_ = _make_library_db()
    library_repo.get_library = MagicMock(return_value=_library_row())

    result = db.update_library(_LIB, LibraryUpdate(name="renamed"))

    assert isinstance(result, Library)
    library_repo.update_library.assert_called_once_with(1, {"name": "renamed"})


@pytest.mark.unit
def test_remove_library_returns_false_when_not_found() -> None:
    db, library_repo, *_ = _make_library_db()
    library_repo.get_library_by_natural_key = MagicMock(return_value=None)

    result = db.remove_library(_LIB)

    assert result is False
    library_repo.remove_library.assert_not_called()


@pytest.mark.unit
def test_remove_library_returns_true_when_found() -> None:
    db, library_repo, *_ = _make_library_db()

    result = db.remove_library(_LIB)

    assert result is True
    library_repo.remove_library.assert_called_once_with(1)


# ── Pipeline state ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_get_pipeline_state_returns_domain_value() -> None:
    db, library_repo, *_ = _make_library_db()
    library_repo.get_pipeline_state = MagicMock(
        return_value={
            "scan_state": "scanned",
            "ml_state": "ML_processed",
            "calibration_state": "calibrated",
            "tag_write_state": "written",
        }
    )

    result = db.get_pipeline_state(_LIB)

    assert isinstance(result, LibraryPipelineState)
    assert result.scan_state == "scanned"


@pytest.mark.unit
def test_get_pipeline_state_defaults_when_no_rows() -> None:
    db, library_repo, *_ = _make_library_db()
    library_repo.get_pipeline_state = MagicMock(return_value=None)

    result = db.get_pipeline_state(_LIB)

    assert isinstance(result, LibraryPipelineState)
    assert result == LibraryPipelineState.defaults()


@pytest.mark.unit
def test_get_libraries_in_axis_state_returns_domain() -> None:
    db, library_repo, _, _, _, _, _, _, pipeline_repo = _make_library_db()
    pipeline_repo.list_libraries_in_pipeline_state = MagicMock(return_value=[1])
    library_repo.get_library = MagicMock(return_value=_library_row())

    result = db.get_libraries_in_axis_state("scan_state", "done")

    assert len(result) == 1
    assert isinstance(result[0], Library)
    pipeline_repo.list_libraries_in_pipeline_state.assert_called_once_with("scan_state", "done")


# ── Song read operations ──────────────────────────────────────────────────


@pytest.mark.unit
def test_get_song_delegates() -> None:
    db, _, song_repo, *_ = _make_library_db()
    song_repo.get_song = MagicMock(return_value=_song_row())

    result = db.get_song(10)

    assert isinstance(result, Song)
    assert result.song_id == 10
    assert result.path == "/music/a.mp3"
    song_repo.get_song.assert_called_once_with(10)


@pytest.mark.unit
def test_get_song_by_path_delegates_with_library_scope() -> None:
    db, library_repo, song_repo, *_ = _make_library_db()
    song_repo.get_song_by_path = MagicMock(return_value=_song_row())

    result = db.get_song_by_path("/music/song.mp3", _LIB)

    assert isinstance(result, Song)
    assert result.song_id == 10
    library_repo.get_library_by_natural_key.assert_called_once_with("TestLib", "/music")
    song_repo.get_song_by_path.assert_called_once_with("/music/song.mp3", 1)


@pytest.mark.unit
def test_find_song_by_path_any_library_delegates() -> None:
    db, _, song_repo, *_ = _make_library_db()
    song_repo.get_song_by_path_unscoped = MagicMock(return_value=_song_row())

    result = db.find_song_by_path_any_library("/music/song.mp3")

    assert isinstance(result, Song)
    assert result.song_id == 10
    song_repo.get_song_by_path_unscoped.assert_called_once_with("/music/song.mp3")


@pytest.mark.unit
def test_list_songs_by_ids_delegates() -> None:
    db, _, song_repo, *_ = _make_library_db()
    song_repo.get_songs_by_ids = MagicMock(return_value=[_song_row()])

    result = db.list_songs_by_ids([1, 2, 3])

    assert len(result) == 1
    assert isinstance(result[0], Song)
    assert result[0].song_id == 10
    song_repo.get_songs_by_ids.assert_called_once_with([1, 2, 3])


@pytest.mark.unit
def test_list_songs_delegates_with_library_scope() -> None:
    db, library_repo, song_repo, *_ = _make_library_db()
    song_repo.list_songs = MagicMock(return_value=[_song_row()])

    result = db.list_songs(_LIB)

    assert len(result) == 1
    assert isinstance(result[0], Song)
    library_repo.get_library_by_natural_key.assert_called_once_with("TestLib", "/music")
    song_repo.list_songs.assert_called_once_with(1, limit=None)


@pytest.mark.unit
def test_count_songs_delegates_with_library_scope() -> None:
    db, _library_repo, song_repo, *_ = _make_library_db()
    song_repo.count_songs = MagicMock(return_value=7)

    result = db.count_songs(_LIB)

    assert result == 7
    song_repo.count_songs.assert_called_once_with(1)


@pytest.mark.unit
def test_get_library_ids_for_songs_delegates() -> None:
    db, _, song_repo, *_ = _make_library_db()
    song_repo.get_library_ids_for_songs = MagicMock(return_value=sentinel.mapping)

    result = db.get_library_ids_for_songs([10, 20])

    assert result is sentinel.mapping
    song_repo.get_library_ids_for_songs.assert_called_once_with([10, 20])


@pytest.mark.unit
def test_count_recently_tagged_delegates() -> None:
    db, _, song_repo, *_ = _make_library_db()
    song_repo.count_recently_tagged = MagicMock(return_value=7)

    result = db.count_recently_tagged(1000)

    assert result == 7
    song_repo.count_recently_tagged.assert_called_once_with(1000)


@pytest.mark.unit
def test_list_library_song_ids_delegates_with_library_scope() -> None:
    db, _library_repo, song_repo, *_ = _make_library_db()
    song_repo.list_library_song_ids = MagicMock(return_value=[1, 2, 3])

    result = db.list_library_song_ids(_LIB)

    assert result == [1, 2, 3]
    song_repo.list_library_song_ids.assert_called_once_with(1, limit=None)


# ── Identity bridge (song-tag correction, P3) ─────────────────────────────


@pytest.mark.unit
def test_resolve_song_identity_bridge() -> None:
    db, _, song_repo, *_ = _make_library_db()
    song_repo.get_songs_by_ids = MagicMock(return_value=[_song_row()])
    db._songs._library_repo.get_libraries_by_ids = MagicMock(return_value=[_library_row()])

    identity = db.resolve_song_identity(10)

    assert identity == _song()
    assert identity is not None
    assert isinstance(identity.library, LibraryIdentity)


@pytest.mark.unit
def test_resolve_library_identity_bridge() -> None:
    db, library_repo, *_ = _make_library_db()
    library_repo.get_libraries_by_ids = MagicMock(return_value=[_library_row()])

    identity = db.resolve_library_identity(1)

    assert identity == _TEST_LIBRARY


# ── Song mutations ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_add_song_to_library_delegates() -> None:
    db, library_repo, song_repo, *_ = _make_library_db()
    song_repo.upsert_songs_for_library = MagicMock(return_value=[42])

    result = db.add_song_to_library(_LIB, {"path": "/music/a.mp3"})

    assert result == 42
    library_repo.get_library_by_natural_key.assert_called_once_with("TestLib", "/music")
    song_repo.upsert_songs_for_library.assert_called_once_with(1, [{"path": "/music/a.mp3"}])


@pytest.mark.unit
def test_update_songs_delegates() -> None:
    db, _, song_repo, *_ = _make_library_db()
    song_repo.list_existing_song_paths = MagicMock(return_value=[])
    song_repo.upsert_songs_for_library = MagicMock(return_value=[1, 2])
    song_repo.list_library_song_ids = MagicMock(return_value=[1, 2])

    result = db.update_songs(
        _LIB,
        [{"path": "/music/a.mp3", "file_size": 1}, {"path": "/music/b.mp3", "file_size": 2}],
    )

    assert result == {"added": 2, "updated": 0, "removed": 0}


@pytest.mark.unit
def test_remove_song_delegates() -> None:
    db, _, song_repo, *_ = _make_library_db()
    song_repo.delete_song = MagicMock()

    db.remove_song(77)

    song_repo.delete_song.assert_called_once_with(77)


@pytest.mark.unit
def test_remove_song_by_path_returns_silently_when_not_found() -> None:
    db, _, song_repo, *_ = _make_library_db()
    song_repo.get_song_by_path = MagicMock(return_value=None)
    song_repo.delete_song = MagicMock()

    db.remove_song_by_path("/nonexistent.mp3", _LIB)

    song_repo.delete_song.assert_not_called()


# ── Tag operations (domain contract) ──────────────────────────────────────


@pytest.mark.unit
def test_get_tag_accepts_tag_identity() -> None:
    db, _, _, _, _, tag_repo, *_ = _make_library_db()
    tag_repo.get_tag_by_name = MagicMock(return_value={"name": "artist", "value": "X", "namespace": ""})

    result = db.get_tag(_tag())

    assert result == _tag()
    tag_repo.get_tag_by_name.assert_called_once_with("artist", "")


@pytest.mark.unit
def test_ensure_tag_returns_tag_identity() -> None:
    db, _, _, _, _, tag_repo, *_ = _make_library_db()
    tag_repo.get_or_create_tag = MagicMock(return_value=1)
    identity = _tag(namespace="nom")

    result = db.ensure_tag(identity)

    assert result == identity
    tag_repo.get_or_create_tag.assert_called_once_with("artist", "X", "nom")


@pytest.mark.unit
def test_find_songs_with_tag_returns_domain_songs() -> None:
    db, _, _, _, _, _, song_tag_repo, *_ = _make_library_db()
    song_tag_repo.search_songs_by_tag = MagicMock(return_value=[_song_row()])

    result = db.find_songs_with_tag(_tag("genre", "Rock"), limit=10)

    assert len(result) == 1
    assert isinstance(result[0], Song)
    assert result[0].song_id == 10
    song_tag_repo.search_songs_by_tag.assert_called_once_with("genre", "Rock", limit=10, offset=0)


@pytest.mark.unit
def test_find_songs_with_tag_contains_returns_domain_songs() -> None:
    db, _, _, _, _, _, song_tag_repo, *_ = _make_library_db()
    song_tag_repo.search_songs_by_tag_contains = MagicMock(return_value=[_song_row()])

    result = db.find_songs_with_tag_contains(_tag("nom:mood-strict", "happy"), limit=5)

    assert len(result) == 1
    assert isinstance(result[0], Song)
    song_tag_repo.search_songs_by_tag_contains.assert_called_once_with("nom:mood-strict", "happy", limit=5)


@pytest.mark.unit
def test_find_songs_with_tag_pattern_returns_domain_songs() -> None:
    db, _, _, _, _, _, song_tag_repo, *_ = _make_library_db()
    song_tag_repo.search_songs_by_tag_pattern = MagicMock(return_value=[_song_row()])

    result = db.find_songs_with_tag_pattern("artist", "%Beatles%", limit=5)

    assert len(result) == 1
    assert isinstance(result[0], Song)
    song_tag_repo.search_songs_by_tag_pattern.assert_called_once_with("artist", "%Beatles%", limit=5)


@pytest.mark.unit
def test_find_songs_with_numeric_tag_returns_domain_matches() -> None:
    db, _, _, _, _, _, song_tag_repo, *_ = _make_library_db()
    row = dict(_song_row())
    row["matched_tag"] = "118.0"
    row["distance"] = 2.0
    song_tag_repo.search_songs_by_numeric_tag = MagicMock(return_value=[row])

    result = db.find_songs_with_numeric_tag(_tag("nom:bpm", "120"), limit=5, offset=20)

    assert len(result) == 1
    assert isinstance(result[0], SongTagMatch)
    song_tag_repo.search_songs_by_numeric_tag.assert_called_once_with("nom:bpm", "120", limit=5, offset=20)


@pytest.mark.unit
def test_list_tags_returns_domain_tag_identities() -> None:
    db, _, _, _, _, tag_repo, *_ = _make_library_db()
    tag_repo.list_tags = MagicMock(return_value=[{"id": 1, "name": "artist", "value": "X", "namespace": ""}])

    result = db.list_tags(name="artist", limit=10)

    assert len(result) == 1
    assert isinstance(result[0], TagRef)
    assert result[0] == _tag()
    tag_repo.list_tags.assert_called_once_with(name="artist", search=None, limit=10, offset=0)


@pytest.mark.unit
def test_list_tags_with_song_count_returns_tag_usage() -> None:
    db, _, _, _, _, tag_repo, *_ = _make_library_db()
    tag_repo.list_tags_with_song_count = MagicMock(
        return_value=[{"id": 1, "name": "artist", "value": "X", "namespace": "", "song_count": 3}]
    )

    result = db.list_tags_with_song_count()

    assert len(result) == 1
    usage = result[0]
    assert isinstance(usage, TagUsage)
    assert usage.identity == _tag()
    assert usage.song_count == 3
    tag_repo.list_tags_with_song_count.assert_called_once_with(name=None, search=None, limit=100, offset=0)


@pytest.mark.unit
def test_count_tags_delegates() -> None:
    db, _, _, _, _, tag_repo, *_ = _make_library_db()
    tag_repo.count_tags = MagicMock(return_value=42)

    assert db.count_tags() == 42
    tag_repo.count_tags.assert_called_once_with()


@pytest.mark.unit
def test_list_tags_for_song_returns_domain_assignments() -> None:
    db, _, song_repo, _, _, _, song_tag_repo, *_ = _make_library_db()
    song_repo.get_song_by_normalized_path = MagicMock(return_value={"id": 7})
    song_tag_repo.get_tags_for_song = MagicMock(
        return_value=[{"name": "artist", "value": "X", "namespace": "", "confidence": 0.9, "source": "nomarr"}]
    )

    result = db.list_tags_for_song(_song())

    assert len(result) == 1
    assignment = result[0]
    assert isinstance(assignment, SongTagAssignment)
    assert assignment.song == _song()
    assert assignment.confidence == 0.9
    song_tag_repo.get_tags_for_song.assert_called_once_with(7)


@pytest.mark.unit
def test_list_genre_tags_for_songs_returns_domain_assignments() -> None:
    db, _, _, _, _, _, song_tag_repo, *_ = _make_library_db()
    song_repo_handle = db._songs._song_repo
    song_repo_handle.get_song_ids_by_normalized_paths = MagicMock(return_value={(1, "a.mp3"): 7})
    song_tag_repo.get_genre_tags_for_songs = MagicMock(
        return_value=[{"id": 1, "name": "genre", "value": "Jazz", "namespace": ""}]
    )

    result = db.list_genre_tags_for_songs([_song()])

    assert len(result) == 1
    assert isinstance(result[0], SongTagAssignment)
    song_tag_repo.get_genre_tags_for_songs.assert_called_once_with([7])


@pytest.mark.unit
def test_list_song_tags_for_songs_groups_by_domain_identity() -> None:
    db, _, _, _, _, _, song_tag_repo, *_ = _make_library_db()
    song_repo_handle = db._songs._song_repo
    song_repo_handle.get_song_ids_by_normalized_paths = MagicMock(return_value={(1, "a.mp3"): 1, (1, "b.mp3"): 2})
    song_tag_repo.get_tags_for_songs_batch = MagicMock(
        return_value=[
            {"song_id": 1, "tag_id": 100, "tag_name": "genre", "tag_value": "Rock", "source": "ml", "confidence": 0.9},
            {"song_id": 2, "tag_id": 100, "tag_name": "genre", "tag_value": "Rock", "source": "ml", "confidence": 0.9},
        ]
    )

    result = db.list_song_tags_for_songs([_song(), _song("b.mp3")])

    assert set(result.keys()) == {_song(), _song("b.mp3")}
    assert len(result[_song()]) == 1
    assignment = result[_song()][0]
    assert isinstance(assignment, SongTagAssignment)
    assert assignment.name == "genre"
    assert assignment.value == "Rock"
    song_tag_repo.get_tags_for_songs_batch.assert_called_once_with([1, 2], name_starts_with=None)


@pytest.mark.unit
def test_list_song_tags_for_songs_empty_batch_groups_all() -> None:
    db, _, _, _, _, _, song_tag_repo, *_ = _make_library_db()
    song_repo_handle = db._songs._song_repo
    song_repo_handle.get_song_ids_by_normalized_paths = MagicMock(return_value={(1, "a.mp3"): 1, (1, "b.mp3"): 2})
    song_tag_repo.get_tags_for_songs_batch = MagicMock(return_value=[])

    result = db.list_song_tags_for_songs([_song(), _song("b.mp3")])

    assert result == {_song(): (), _song("b.mp3"): ()}


@pytest.mark.unit
def test_count_songs_by_tag_delegates() -> None:
    db, _, _, _, _, _, song_tag_repo, *_ = _make_library_db()
    song_tag_repo.count_songs_by_tag = MagicMock(return_value=15)

    assert db.count_songs_by_tag("genre", "Rock") == 15
    song_tag_repo.count_songs_by_tag.assert_called_once_with("genre", "Rock")


@pytest.mark.unit
def test_count_songs_by_numeric_tag_delegates() -> None:
    db, _, _, _, _, _, song_tag_repo, *_ = _make_library_db()
    song_tag_repo.count_songs_by_numeric_tag = MagicMock(return_value=7)

    assert db.count_songs_by_numeric_tag("nom:bpm", 120.0) == 7
    song_tag_repo.count_songs_by_numeric_tag.assert_called_once_with("nom:bpm", 120.0)


@pytest.mark.unit
def test_replace_song_tags_resolves_set_based() -> None:
    db, _, song_repo, _, _, tag_repo, song_tag_repo, *_ = _make_library_db()
    song_repo.get_song_by_normalized_path = MagicMock(return_value={"id": 7})
    tag_repo.get_or_create_tags_batch = MagicMock(return_value={("artist", "X", ""): 5})
    song_tag_repo.replace_song_tags = MagicMock()

    db.replace_song_tags(_song(), [_assignment()])

    tag_repo.get_or_create_tags_batch.assert_called_once_with([{"name": "artist", "value": "X", "namespace": ""}])
    song_tag_repo.replace_song_tags.assert_called_once_with(
        7,
        [{"song_id": 7, "tag_id": 5, "confidence": 1.0, "source": "nomarr"}],
    )


@pytest.mark.unit
def test_replace_song_tags_noop_when_song_missing() -> None:
    db, _, song_repo, _, _, _, song_tag_repo, *_ = _make_library_db()
    song_repo.get_song_by_normalized_path = MagicMock(return_value=None)

    db.replace_song_tags(_song(), [_assignment()])

    song_tag_repo.replace_song_tags.assert_not_called()


@pytest.mark.unit
def test_relink_tags_returns_relink_result() -> None:
    db, _, _, _, _, tag_repo, song_tag_repo, *_ = _make_library_db()
    tag_repo.get_tag_ids_by_identities = MagicMock(return_value={("artist", "X", ""): 5})
    tag_repo.get_or_create_tags_batch = MagicMock(return_value={("artist", "Y", ""): 6})
    song_repo_handle = db._songs._song_repo
    song_repo_handle.get_song_ids_by_normalized_paths = MagicMock(return_value={(1, "a.mp3"): 7})
    song_tag_repo.relink_song_tags = MagicMock(return_value={"moved": 3, "skipped": 1, "source_orphaned": 1})

    result = db.relink_tags(_tag(), _tag("artist", "Y"), songs=[_song()])

    assert isinstance(result, RelinkResult)
    assert (result.moved, result.skipped, result.source_orphaned) == (3, 1, 1)
    song_tag_repo.relink_song_tags.assert_called_once_with(5, 6, song_ids=[7])


@pytest.mark.unit
def test_relink_tags_missing_source_returns_zero_result() -> None:
    db, _, _, _, _, tag_repo, *_ = _make_library_db()
    tag_repo.get_tag_ids_by_identities = MagicMock(return_value={})

    result = db.relink_tags(_tag(), _tag("artist", "Y"))

    assert result == RelinkResult(moved=0, skipped=0, source_orphaned=0)


@pytest.mark.unit
def test_remove_song_tags_all_tags() -> None:
    db, _, song_repo, _, _, tag_repo, song_tag_repo, *_ = _make_library_db()
    song_repo.get_song_by_normalized_path = MagicMock(return_value={"id": 7})
    song_tag_repo.replace_song_tags = MagicMock()
    tag_repo.cleanup_orphaned_tags = MagicMock()

    db.remove_song_tags(_song())

    song_tag_repo.replace_song_tags.assert_called_once_with(7, [])
    tag_repo.cleanup_orphaned_tags.assert_called_once_with()


@pytest.mark.unit
def test_remove_song_tags_specific_identities() -> None:
    db, _, song_repo, _, _, tag_repo, song_tag_repo, *_ = _make_library_db()
    song_repo.get_song_by_normalized_path = MagicMock(return_value={"id": 7})
    tag_repo.get_tag_ids_by_identities = MagicMock(return_value={("artist", "X", ""): 5})
    song_tag_repo.remove_tags_from_song = MagicMock()
    tag_repo.cleanup_orphaned_tags = MagicMock()

    db.remove_song_tags(_song(), identities=[_tag()])

    song_tag_repo.remove_tags_from_song.assert_called_once_with(7, [5])
    tag_repo.cleanup_orphaned_tags.assert_called_once_with()


@pytest.mark.unit
def test_cleanup_orphaned_tags_returns_typed_result() -> None:
    db, _, _, _, _, tag_repo, *_ = _make_library_db()
    tag_repo.get_orphaned_tag_ids = MagicMock(return_value=[1, 2, 3])
    tag_repo.delete_tags_by_ids = MagicMock(return_value=3)

    result = db.cleanup_orphaned_tags()

    assert result == TagCleanupResult(deleted=3, orphaned=3)
    tag_repo.get_orphaned_tag_ids.assert_called_once_with()
    tag_repo.delete_tags_by_ids.assert_called_once_with([1, 2, 3])


@pytest.mark.unit
def test_list_tag_value_frequencies_calls_batch() -> None:
    db, _, _, _, _, tag_repo, *_ = _make_library_db()
    tag_repo.get_tag_value_frequencies_batch = MagicMock(
        return_value={
            "genre": [("Rock", 10), ("Pop", 5)],
        }
    )

    result = db.list_tag_value_frequencies(["genre"], limit=100)

    assert result == {"genre": [("Rock", 10), ("Pop", 5)]}
    tag_repo.get_tag_value_frequencies_batch.assert_called_once_with(["genre"], limit=100)


# ── Folder operations (LibraryFolder domain) ──────────────────────────────


@pytest.mark.unit
def test_get_folder_delegates_by_library_and_path() -> None:
    db, _, _, folder_repo, *_ = _make_library_db()
    folder_repo.get_folder_by_path = MagicMock(return_value=LibraryFolder(path="/Rock"))

    result = db.get_folder(_LIB, "/Rock")

    assert result == LibraryFolder(path="/Rock")
    folder_repo.get_folder_by_path.assert_called_once_with(1, "/Rock")


@pytest.mark.unit
def test_list_folders_for_library_delegates() -> None:
    db, _, _, folder_repo, *_ = _make_library_db()
    folder_repo.list_folders_for_library = MagicMock(return_value=[LibraryFolder(path="/Rock")])

    result = db.list_folders_for_library(_LIB)

    assert len(result) == 1
    assert isinstance(result[0], LibraryFolder)
    assert result[0].path == "/Rock"
    folder_repo.list_folders_for_library.assert_called_once_with(1)


@pytest.mark.unit
def test_add_library_folder_delegates() -> None:
    db, _, _, folder_repo, *_ = _make_library_db()
    folder_repo.add_library_folder = MagicMock()
    folder_repo.get_folder_by_path = MagicMock(return_value=LibraryFolder(path="/Rock"))

    result = db.add_library_folder(_LIB, LibraryFolder(path="/Rock"))

    assert isinstance(result, LibraryFolder)
    assert result.path == "/Rock"
    folder_repo.add_library_folder.assert_called_once()
    payload = folder_repo.add_library_folder.call_args.args[1]
    assert payload["path"] == "/Rock"


@pytest.mark.unit
def test_remove_library_folder_delegates() -> None:
    db, _, _, folder_repo, *_ = _make_library_db()
    folder_repo.get_folder_id_by_path = MagicMock(return_value=5)
    folder_repo.remove_library_folder = MagicMock()

    db.remove_library_folder(_LIB, "/Rock")

    folder_repo.remove_library_folder.assert_called_once_with(1, 5)


@pytest.mark.unit
def test_replace_library_folders_delegates() -> None:
    db, _, _, folder_repo, *_ = _make_library_db()
    folder_repo.replace_library_folders = MagicMock()

    db.replace_library_folders(_LIB, [LibraryFolder(path="/Rock")])

    folder_repo.replace_library_folders.assert_called_once()
    payloads = folder_repo.replace_library_folders.call_args.args[1]
    assert payloads[0]["path"] == "/Rock"


# ── Scan operations (LibraryScan domain) ──────────────────────────────────


@pytest.mark.unit
def test_get_scan_delegates() -> None:
    db, library_repo, _, _, scan_repo, *_ = _make_library_db()
    scan_repo.get_scan_record = MagicMock(
        return_value={
            "id": 42,
            "library_id": 1,
            "scan_type": "quick",
            "status": "completed",
            "started_at": 1,
            "heartbeat_at": 2,
            "files_processed": 5,
            "files_found": 10,
            "error": None,
            "finished_at": 3,
        }
    )

    result = db.get_scan(_LIB)

    assert isinstance(result, LibraryScan)
    assert result.scan_type == "quick"
    assert result.status == "completed"
    library_repo.get_library_by_natural_key.assert_called_once_with("TestLib", "/music")
    scan_repo.get_scan_record.assert_called_once_with(1)


@pytest.mark.unit
def test_record_scan_progress_translates_progress_fields() -> None:
    db, _, _, _, scan_repo, *_ = _make_library_db()
    scan_repo.get_scan_record = MagicMock(
        return_value={
            "id": 42,
            "scan_type": "quick",
            "status": "in_progress",
            "started_at": 1,
            "heartbeat_at": 1,
            "files_processed": 0,
            "files_found": 0,
            "error": None,
            "finished_at": None,
        }
    )
    scan_repo.update_current_scan = MagicMock(return_value=True)

    db.record_scan_progress(_LIB, heartbeat_at=123, progress=5, total=12, scan_error="boom")

    scan_repo.update_current_scan.assert_called_once_with(
        1,
        42,
        {
            "heartbeat_at": 123,
            "files_processed": 5,
            "files_found": 12,
            "error": "boom",
        },
    )


@pytest.mark.unit
def test_record_scan_progress_raises_when_scan_is_no_longer_current() -> None:
    """A stale progress write must raise instead of silently no-op."""
    db, _, _, _, scan_repo, *_ = _make_library_db()
    scan_repo.get_scan_record = MagicMock(return_value={"id": 42, "scan_type": "quick"})
    scan_repo.update_current_scan = MagicMock(return_value=False)

    with pytest.raises(
        ValueError,
        match=r"no longer current|no longer the current scan",
    ):
        db.record_scan_progress(_LIB, heartbeat_at=123, progress=5)


@pytest.mark.unit
def test_complete_scan_raises_when_scan_is_no_longer_current() -> None:
    """A stale completion write must raise instead of silently no-op."""
    db, _, _, _, scan_repo, *_ = _make_library_db()
    scan_repo.get_scan_record = MagicMock(return_value={"id": 42, "scan_type": "quick"})
    scan_repo.update_current_scan = MagicMock(return_value=False)

    with pytest.raises(
        ValueError,
        match=r"no longer current|no longer the current scan",
    ):
        db.complete_scan(_LIB, finished_at=999)


@pytest.mark.unit
def test_remove_scan_when_exists() -> None:
    db, _, _, _, scan_repo, *_ = _make_library_db()
    scan_repo.get_scan_record = MagicMock(return_value={"id": 42})
    scan_repo.delete_scan_record = MagicMock()

    db.remove_scan(_LIB)

    scan_repo.get_scan_record.assert_called_once_with(1)
    scan_repo.delete_scan_record.assert_called_once_with(42)


@pytest.mark.unit
def test_remove_scan_noop_when_not_exists() -> None:
    db, _, _, _, scan_repo, *_ = _make_library_db()
    scan_repo.get_scan_record = MagicMock(return_value=None)
    scan_repo.delete_scan_record = MagicMock()

    db.remove_scan(_LIB)

    scan_repo.delete_scan_record.assert_not_called()


# ── Song hydration (transactional intent) ────────────────────────────────


@pytest.mark.unit
def test_hydrate_song_delegates_to_song_hydration_repo() -> None:
    db, hydration_repo = _make_songs_db_with_hydration()

    db.hydrate_song(sentinel.input)

    hydration_repo.hydrate_song.assert_called_once_with(sentinel.input)


@pytest.mark.unit
def test_hydrate_songs_batch_delegates_and_returns_count() -> None:
    db, hydration_repo = _make_songs_db_with_hydration()
    hydration_repo.hydrate_songs_batch = MagicMock(return_value=5)

    result = db.hydrate_songs_batch([sentinel.a, sentinel.b], chunk_size=3)

    assert result == 5
    hydration_repo.hydrate_songs_batch.assert_called_once_with([sentinel.a, sentinel.b], chunk_size=3)


# ── Sub-facade maintenance surfaces ───────────────────────────────────────


def _make_songs_db() -> tuple[LibrarySongsDb, MagicMock, MagicMock]:
    song_repo = MagicMock()
    folder_repo = MagicMock()
    song_state_repo = MagicMock()
    db = LibrarySongsDb(
        session=MagicMock(),
        song_repo=song_repo,
        folder_repo=folder_repo,
        song_state_repo=song_state_repo,
        song_hydration_repo=MagicMock(),
        library_repo=MagicMock(),
    )
    return db, song_repo, folder_repo


def _make_songs_db_with_hydration() -> tuple[LibrarySongsDb, MagicMock]:
    """Build a songs sub-facade with a controllable song_hydration_repo mock."""
    song_hydration_repo = MagicMock()
    db = LibrarySongsDb(
        session=MagicMock(),
        song_repo=MagicMock(),
        folder_repo=MagicMock(),
        song_state_repo=MagicMock(),
        song_hydration_repo=song_hydration_repo,
        library_repo=MagicMock(),
    )
    return db, song_hydration_repo


def _make_tags_db() -> tuple[LibraryTagsDb, MagicMock, MagicMock]:
    tag_repo = MagicMock()
    song_tag_repo = MagicMock()
    db = LibraryTagsDb(
        session=MagicMock(),
        tag_repo=tag_repo,
        song_tag_repo=song_tag_repo,
        song_repo=MagicMock(),
        library_repo=MagicMock(),
    )
    return db, tag_repo, song_tag_repo


@pytest.mark.unit
def test_maintenance_list_orphaned_song_ids() -> None:
    db, song_repo, _ = _make_songs_db()
    song_repo.list_orphaned_song_ids = MagicMock(return_value=sentinel.ids)

    result = db.list_orphaned_song_ids()

    assert result is sentinel.ids
    song_repo.list_orphaned_song_ids.assert_called_once_with()


@pytest.mark.unit
def test_maintenance_cleanup_orphaned_tags() -> None:
    db, tag_repo, _ = _make_tags_db()
    tag_repo.get_orphaned_tag_ids = MagicMock(return_value=[1])
    tag_repo.delete_tags_by_ids = MagicMock(return_value=1)

    result = db.cleanup_orphaned_tags()

    assert result == TagCleanupResult(deleted=1, orphaned=1)


@pytest.mark.unit
def test_maintenance_truncate_songs() -> None:
    db, song_repo, _ = _make_songs_db()
    song_repo.truncate_songs = MagicMock()

    db.truncate_songs()

    song_repo.truncate_songs.assert_called_once_with()


@pytest.mark.unit
def test_maintenance_truncate_song_links() -> None:
    db, song_repo, _ = _make_songs_db()
    song_repo.truncate_song_links = MagicMock()

    db.truncate_song_links()

    song_repo.truncate_song_links.assert_called_once_with()


@pytest.mark.unit
def test_maintenance_truncate_folder_links() -> None:
    db, _, folder_repo = _make_songs_db()
    folder_repo.truncate_folder_links = MagicMock()

    db.truncate_folder_links()

    folder_repo.truncate_folder_links.assert_called_once_with()


@pytest.mark.unit
def test_maintenance_truncate_folders() -> None:
    db, _, folder_repo = _make_songs_db()
    folder_repo.truncate_folders = MagicMock()

    db.truncate_folders()

    folder_repo.truncate_folders.assert_called_once_with()


@pytest.mark.unit
def test_maintenance_truncate_tags() -> None:
    db, tag_repo, _ = _make_tags_db()
    tag_repo.truncate_tags = MagicMock()

    db.truncate_tags()

    tag_repo.truncate_tags.assert_called_once_with()


@pytest.mark.unit
def test_maintenance_truncate_song_tag_assignments() -> None:
    db, _, song_tag_repo = _make_tags_db()
    song_tag_repo.truncate_song_tag_assignments = MagicMock()

    db.truncate_song_tag_assignments()

    song_tag_repo.truncate_song_tag_assignments.assert_called_once_with()


@pytest.mark.unit
def test_maintenance_truncate_scan_records() -> None:
    scan_repo = MagicMock()
    db = LibraryScansDb(session=MagicMock(), scan_repo=scan_repo, library_repo=MagicMock())

    db.truncate_scan_records()

    scan_repo.truncate_scans.assert_called_once_with()
