# mypy: disable-error-code=func-returns-value
"""Unit tests for ``LibraryDb`` delegation to the four sub-facades.

These tests cover the sealed domain contracts (per ADR-032/041/043):

- Library-facing methods accept/return ``Library`` / ``LibraryUpdate`` /
  ``LibraryPipelineState`` / ``LibraryFolder`` / ``LibraryScan`` domain values;
  storage ``id``/``library_id``/row shapes never cross the facade.
- Tag-facing methods accept/return ``TagRef`` / ``SongTagAssignment`` /
  ``TagUsage`` / ``RelinkResult`` / ``TagCleanupResult``; song identity is the
  natural ``SongIdentity`` (never a PostgreSQL ``song_id``).
- Library identity conversion remains a persistence-internal library-handle
  operation; song identity crosses the facade only as ``SongIdentity``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, sentinel

import pytest

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.library_domain_dataclasses import (
    LibraryFolder,
    LibraryPipelineState,
    LibraryScan,
    LibraryUpdate,
)
from nomarr.helpers.dataclasses.song_command_dataclass import (
    ChromaprintValue,
    FieldWriteResult,
    LibraryIdentity,
    SongIdentity,
    SongPathUpdate,
    SongRemoval,
    SongScanUpdate,
    SongUpsertInput,
)
from nomarr.helpers.dataclasses.song_dataclass import Song, SongTagMatch
from nomarr.helpers.dataclasses.song_state_candidate_dataclass import SongStateCandidate
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
    "library_uuid": "de131b32-af5c-5a84-8874-58e3dc0e2dcd",
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


def test_scalar_locator_intents_validate_and_delegate_typed_results() -> None:
    db, _library_repo, song_repo, *_ = _make_library_db()
    identity = SongIdentity(LibraryIdentity("de131b32-af5c-5a84-8874-58e3dc0e2dcd"), "a.mp3")
    song_repo.set_modified_time_by_locator.return_value = "UPDATED"
    song_repo.set_last_tagged_by_locator.return_value = "UNCHANGED"
    song_repo.set_chromaprint_by_locator.return_value = "STALE_VALUE"

    modified = db.set_modified_time(identity, 1000)
    tagged = db.set_last_tagged(identity, 1000)
    chromaprint = db.set_chromaprint(identity, ChromaprintValue("AQID", "decoder-v1"))

    assert modified == FieldWriteResult("UPDATED")
    assert tagged == FieldWriteResult("UNCHANGED")
    assert chromaprint == FieldWriteResult("STALE_VALUE")
    assert db.set_modified_time(identity, -1) == FieldWriteResult("INVALID_VALUE")
    assert db.set_last_tagged(identity, True) == FieldWriteResult("INVALID_VALUE")
    song_repo.set_modified_time_by_locator.assert_called_once_with(1, "a.mp3", 1000)
    song_repo.set_last_tagged_by_locator.assert_called_once_with(1, "a.mp3", 1000)
    song_repo.set_chromaprint_by_locator.assert_called_once_with(
        1, "a.mp3", "AQID", expected_value=None, expected_absent=True
    )


def test_scalar_locator_intents_missing_locator_do_not_write() -> None:
    db, library_repo, song_repo, *_ = _make_library_db()
    library_repo.get_library_by_uuid.return_value = None
    identity = SongIdentity(LibraryIdentity("missing"), "a.mp3")

    assert db.set_modified_time(identity, 1) == FieldWriteResult("MISSING_LOCATOR")
    assert db.set_last_tagged(identity, 1) == FieldWriteResult("MISSING_LOCATOR")
    assert db.set_chromaprint(identity, ChromaprintValue("AQID", "decoder-v1")) == FieldWriteResult("MISSING_LOCATOR")
    song_repo.set_modified_time_by_locator.assert_not_called()
    song_repo.set_last_tagged_by_locator.assert_not_called()
    song_repo.set_chromaprint_by_locator.assert_not_called()


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
    library_repo.get_library_by_uuid.return_value = {"id": 1, "library_uuid": "de131b32-af5c-5a84-8874-58e3dc0e2dcd"}
    library_repo.get_library_ids_by_uuids.return_value = {"de131b32-af5c-5a84-8874-58e3dc0e2dcd": 1}
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
        library_reset_repo=MagicMock(),
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


_TEST_LIBRARY = LibraryIdentity(library_uuid="de131b32-af5c-5a84-8874-58e3dc0e2dcd", name="TestLib", root_path="/music")
_LIB = Library(library_uuid="de131b32-af5c-5a84-8874-58e3dc0e2dcd", name="TestLib", root_path="/music")


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
    # are removed per the song-tag hard-cut, and the id-disclosing
    # list_orphaned_song_ids is removed in favor of the count-only
    # prune_orphaned_songs intent (no generated IDs above persistence).
    assert hasattr(db, "prune_orphaned_songs")
    assert not hasattr(db, "list_orphaned_song_ids")
    assert hasattr(db, "admin_cleanup_orphaned_tags")
    assert not hasattr(db, "delete_tags_by_ids")
    assert not hasattr(db, "list_orphaned_tag_ids")
    assert not hasattr(db, "list_song_tag_edges")
    assert not hasattr(db, "list_song_ids_for_tag_id")
    assert hasattr(db, "truncate_songs")
    assert hasattr(db, "truncate_song_links")
    assert hasattr(db, "truncate_folder_links")
    assert hasattr(db, "truncate_folders")
    assert hasattr(db, "admin_truncate_tags")
    assert hasattr(db, "admin_truncate_song_tag_assignments")
    assert hasattr(db, "truncate_scan_records")

    # Forwarders route to the correct sub-facade repo; the count-only prune
    # intent privately consumes the repo's orphan handles and never exposes them.
    song_repo.list_orphaned_song_ids = MagicMock(return_value=[])
    db.prune_orphaned_songs()
    song_repo.list_orphaned_song_ids.assert_called_once_with()

    tag_repo.get_orphaned_tag_ids = MagicMock(return_value=[])
    db.admin_cleanup_orphaned_tags()
    tag_repo.get_orphaned_tag_ids.assert_called_once_with()

    db.truncate_songs()
    song_repo.truncate_songs.assert_called_once_with()

    db.truncate_song_links()
    song_repo.truncate_song_links.assert_called_once_with()

    db.truncate_folder_links()
    folder_repo.truncate_folder_links.assert_called_once_with()

    db.truncate_folders()
    folder_repo.truncate_folders.assert_called_once_with()

    db.admin_truncate_tags()
    tag_repo.truncate_tags.assert_called_once_with()

    db.admin_truncate_song_tag_assignments()
    song_tag_repo.truncate_song_tag_assignments.assert_called_once_with()

    # The destructive whole-library reset lives on the nested
    # ``db.library.maintenance`` surface, not as a LibraryDb top-level method.
    assert hasattr(db.maintenance, "reset_library_data")
    assert not hasattr(db, "reset_library_data")
    # LibraryMaintenanceDb is a public nested sub-facade in the module.
    import nomarr.persistence.api.library as library_module

    assert hasattr(library_module, "LibraryMaintenanceDb")
    assert isinstance(db.maintenance, library_module.LibraryMaintenanceDb)
    # No facade transaction context / begin-transaction helper leaks (AR-SDR-4).
    assert not hasattr(db.maintenance, "transaction")
    assert not hasattr(db.maintenance, "_require_transaction")
    assert not hasattr(db.maintenance, "begin")


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
def test_get_song_by_locator_delegates() -> None:
    db, library_repo, song_repo, *_ = _make_library_db()
    song_repo.get_song_by_normalized_path = MagicMock(return_value=_song_row())

    result = db.get_song(_song())

    assert isinstance(result, Song)
    assert not hasattr(result, "song_id")  # generated songs.id stays persistence-private
    assert result.path == "/music/a.mp3"
    library_repo.get_library_by_uuid.assert_called_once_with("de131b32-af5c-5a84-8874-58e3dc0e2dcd")
    song_repo.get_song_by_normalized_path.assert_called_once_with(1, "a.mp3")


@pytest.mark.unit
def test_get_song_by_locator_missing_library_is_none() -> None:
    # A locator whose owning library cannot be resolved is a deterministic
    # ``None`` miss (ADR-048), not an error and not an integer fallback.
    db, library_repo, song_repo, *_ = _make_library_db()
    library_repo.get_library_by_uuid = MagicMock(return_value=None)
    song_repo.get_song_by_normalized_path = MagicMock()

    assert db.get_song(_song()) is None
    song_repo.get_song_by_normalized_path.assert_not_called()


@pytest.mark.unit
def test_get_song_by_locator_unknown_uuid_is_none() -> None:
    # A locator whose UUID is not registered is a deterministic ``None`` miss;
    # root_path is mutable metadata and no longer gates resolution.
    db, library_repo, song_repo, *_ = _make_library_db()
    library_repo.get_library_by_uuid = MagicMock(return_value=None)
    song_repo.get_song_by_normalized_path = MagicMock()
    identity = SongIdentity(
        library=LibraryIdentity(library_uuid="08042357-9a97-5066-a9bf-bcab3b77ec8b", name="TestLib", root_path=None),
        normalized_path="a.mp3",
    )

    assert db.get_song(identity) is None
    library_repo.get_library_by_uuid.assert_called_once_with("08042357-9a97-5066-a9bf-bcab3b77ec8b")
    song_repo.get_song_by_normalized_path.assert_not_called()


@pytest.mark.unit
def test_get_song_by_locator_missing_song_is_none() -> None:
    db, _, song_repo, *_ = _make_library_db()
    song_repo.get_song_by_normalized_path = MagicMock(return_value=None)

    assert db.get_song(_song()) is None


@pytest.mark.unit
def test_get_song_by_path_delegates_with_library_scope() -> None:
    db, library_repo, song_repo, *_ = _make_library_db()
    song_repo.get_song_by_path = MagicMock(return_value=_song_row())

    result = db.get_song_by_path("/music/song.mp3", _LIB)

    assert isinstance(result, Song)
    assert not hasattr(result, "song_id")  # generated songs.id stays persistence-private
    library_repo.get_library_by_uuid.assert_called_once_with("de131b32-af5c-5a84-8874-58e3dc0e2dcd")
    song_repo.get_song_by_path.assert_called_once_with("/music/song.mp3", 1)


@pytest.mark.unit
def test_get_song_by_normalized_path_locator_delegates() -> None:
    db, library_repo, song_repo, *_ = _make_library_db()
    song_repo.get_song_by_normalized_path = MagicMock(return_value=_song_row())

    result = db.get_song_by_normalized_path(_TEST_LIBRARY, "a.mp3")

    assert isinstance(result, Song)
    assert not hasattr(result, "song_id")
    library_repo.get_library_by_uuid.assert_called_once_with("de131b32-af5c-5a84-8874-58e3dc0e2dcd")
    song_repo.get_song_by_normalized_path.assert_called_once_with(1, "a.mp3")


@pytest.mark.unit
def test_get_song_by_normalized_path_missing_library_is_none() -> None:
    db, library_repo, song_repo, *_ = _make_library_db()
    library_repo.get_library_by_uuid = MagicMock(return_value=None)
    song_repo.get_song_by_normalized_path = MagicMock()

    assert db.get_song_by_normalized_path(_TEST_LIBRARY, "a.mp3") is None
    song_repo.get_song_by_normalized_path.assert_not_called()


@pytest.mark.unit
def test_find_song_by_path_any_library_delegates() -> None:
    db, _, song_repo, *_ = _make_library_db()
    song_repo.get_song_by_path_unscoped = MagicMock(return_value=_song_row())

    result = db.find_song_by_path_any_library("/music/song.mp3")

    assert isinstance(result, Song)
    assert not hasattr(result, "song_id")  # generated songs.id stays persistence-private
    song_repo.get_song_by_path_unscoped.assert_called_once_with("/music/song.mp3")


@pytest.mark.unit
def test_list_songs_by_identity_delegates_order_preserving() -> None:
    db, library_repo, song_repo, *_ = _make_library_db()
    song_repo.get_song_ids_by_normalized_paths = MagicMock(return_value={(1, "a.mp3"): 10, (1, "b.mp3"): 11})
    row_a, row_b = _song_row(), _song_row()
    row_b["id"], row_b["path"], row_b["normalized_path"] = 11, "/music/b.mp3", "b.mp3"
    song_repo.get_songs_by_ids = MagicMock(return_value=[row_a, row_b])

    result = db.list_songs_by_identity([_song("a.mp3"), _song("b.mp3")])

    assert [r.path for r in result] == ["/music/a.mp3", "/music/b.mp3"]
    for r in result:
        assert isinstance(r, Song)
        assert not hasattr(r, "song_id")  # generated songs.id stays persistence-private
        assert not hasattr(r, "library_id")
    library_repo.get_library_ids_by_uuids.assert_called_once_with(["de131b32-af5c-5a84-8874-58e3dc0e2dcd"])
    song_repo.get_song_ids_by_normalized_paths.assert_called_once_with([(1, "a.mp3"), (1, "b.mp3")])
    song_repo.get_songs_by_ids.assert_called_once_with([10, 11])


@pytest.mark.unit
def test_list_songs_by_identity_empty_is_empty() -> None:
    db, library_repo, song_repo, *_ = _make_library_db()

    assert db.list_songs_by_identity([]) == []
    library_repo.get_library_ids_by_uuids.assert_not_called()
    song_repo.get_song_ids_by_normalized_paths.assert_not_called()
    song_repo.get_songs_by_ids.assert_not_called()


@pytest.mark.unit
def test_list_songs_by_identity_omits_missing_library_and_song() -> None:
    db, library_repo, song_repo, *_ = _make_library_db()
    # Library natural keys resolve only for TestLib; the "ghost" library is
    # unresolvable and omitted. Only a.mp3 exists as a song row.
    library_repo.get_library_ids_by_uuids = MagicMock(return_value={"de131b32-af5c-5a84-8874-58e3dc0e2dcd": 1})
    song_repo.get_song_ids_by_normalized_paths = MagicMock(return_value={(1, "a.mp3"): 10})
    row_a = _song_row()
    song_repo.get_songs_by_ids = MagicMock(return_value=[row_a])
    ghost = SongIdentity(
        library=LibraryIdentity(library_uuid="7c44ca4f-53b3-5fbc-8297-59907f30eede", name="Ghost", root_path="/ghost"),
        normalized_path="c.mp3",
    )

    result = db.list_songs_by_identity([_song("a.mp3"), ghost, _song("missing.mp3")])

    assert [r.path for r in result] == ["/music/a.mp3"]
    # Both TestLib locators are resolved as targets (missing.mp3 just has no
    # row); the unresolvable Ghost library is never queried.
    song_repo.get_song_ids_by_normalized_paths.assert_called_once_with([(1, "a.mp3"), (1, "missing.mp3")])


@pytest.mark.unit
def test_list_songs_delegates_with_library_scope() -> None:
    db, library_repo, song_repo, *_ = _make_library_db()
    song_repo.list_songs = MagicMock(return_value=[_song_row()])

    result = db.list_songs(_TEST_LIBRARY)

    assert len(result) == 1
    assert isinstance(result[0], Song)
    assert not hasattr(result[0], "song_id")
    library_repo.get_library_by_uuid.assert_called_once_with("de131b32-af5c-5a84-8874-58e3dc0e2dcd")
    song_repo.list_songs.assert_called_once_with(1, limit=None)


@pytest.mark.unit
def test_list_songs_unknown_library_raises() -> None:
    db, library_repo, song_repo, *_ = _make_library_db()
    library_repo.get_library_by_uuid = MagicMock(return_value=None)
    song_repo.list_songs = MagicMock()

    with pytest.raises(LookupError):
        db.list_songs(_TEST_LIBRARY)
    song_repo.list_songs.assert_not_called()


@pytest.mark.unit
def test_count_songs_delegates_with_library_scope() -> None:
    db, _library_repo, song_repo, *_ = _make_library_db()
    song_repo.count_songs = MagicMock(return_value=7)

    result = db.count_songs(_LIB)

    assert result == 7
    song_repo.count_songs.assert_called_once_with(1)


@pytest.mark.unit
def test_private_song_repository_get_library_ids_preserves_mapping() -> None:
    _db, _, song_repo, *_ = _make_library_db()
    song_repo.get_library_ids_for_songs = MagicMock(return_value=sentinel.mapping)

    result = song_repo.get_library_ids_for_songs([10, 20])

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
def test_private_song_repository_lists_library_song_ids_with_scope() -> None:
    _db, _library_repo, song_repo, *_ = _make_library_db()
    song_repo.list_library_song_ids = MagicMock(return_value=[1, 2, 3])

    result = song_repo.list_library_song_ids(1, limit=None)

    assert result == [1, 2, 3]
    song_repo.list_library_song_ids.assert_called_once_with(1, limit=None)


# ── Identity boundary ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_library_identity_is_supplied_semantically() -> None:
    assert _TEST_LIBRARY.library_uuid
    assert _TEST_LIBRARY.name == "TestLib"
    assert _TEST_LIBRARY.root_path == "/music"


# ── Song mutations ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_add_song_to_library_delegates_typed_command() -> None:
    db, library_repo, song_repo, *_ = _make_library_db()
    song_repo.list_existing_song_paths = MagicMock(return_value=[])
    song_repo.upsert_songs_for_library = MagicMock(return_value=[42])
    song_repo.get_song_ids_by_paths = MagicMock(return_value={"/music/a.mp3": 42})
    scan = SongScanUpdate(
        normalized_path="a.mp3",
        file_size=100,
        modified_time=1000,
        duration_seconds=120.5,
        scanned_at=1000,
    )
    command = SongUpsertInput(
        library=_TEST_LIBRARY,
        path="/music/a.mp3",
        scan=scan,
        last_tagged_at=2000,
    )

    result = db.add_song_to_library(command)

    # The facade returns the natural SongIdentity, never the generated song id.
    assert isinstance(result, SongIdentity)
    assert result == SongIdentity(library=_TEST_LIBRARY, normalized_path="a.mp3")
    assert not isinstance(result, int)
    library_repo.get_library_by_uuid.assert_called_once_with("de131b32-af5c-5a84-8874-58e3dc0e2dcd")
    song_repo.upsert_songs_for_library.assert_called_once_with(
        1,
        [
            {
                "path": "/music/a.mp3",
                "normalized_path": "a.mp3",
                "file_size": 100,
                "modified_time": 1000,
                "duration_seconds": 120.5,
                "scanned_at": 1000,
                "chromaprint": None,
                "last_tagged_at": 2000,
            }
        ],
        commit=False,
    )


@pytest.mark.unit
def test_add_song_to_library_initializes_states_with_private_id() -> None:
    db, _, song_repo, _, _, _, _, song_state_repo, _ = _make_library_db()
    song_repo.list_existing_song_paths = MagicMock(return_value=[])
    song_repo.upsert_songs_for_library = MagicMock(return_value=[42])
    song_repo.get_song_ids_by_paths = MagicMock(return_value={"/music/a.mp3": 42})
    scan = SongScanUpdate(
        normalized_path="a.mp3",
        file_size=100,
        modified_time=1000,
    )
    command = SongUpsertInput(library=_TEST_LIBRARY, path="/music/a.mp3", scan=scan)

    result = db.add_song_to_library(command)

    assert result == SongIdentity(library=_TEST_LIBRARY, normalized_path="a.mp3")
    # State init is driven by the path-resolved private song id and stays internal.
    song_state_repo.initialize_song_states.assert_called_once_with([42], commit=False)


@pytest.mark.unit
def test_add_song_to_library_defaults_scanned_at_when_scan_omits_it() -> None:
    db, _, song_repo, *_ = _make_library_db()
    song_repo.list_existing_song_paths = MagicMock(return_value=[])
    song_repo.upsert_songs_for_library = MagicMock(return_value=[42])
    song_repo.get_song_ids_by_paths = MagicMock(return_value={"/music/a.mp3": 42})
    scan = SongScanUpdate(
        normalized_path="a.mp3",
        file_size=100,
        modified_time=1000,
        scanned_at=None,
    )
    command = SongUpsertInput(library=_TEST_LIBRARY, path="/music/a.mp3", scan=scan)
    from nomarr.helpers.time_helper import now_ms

    before = now_ms().value

    db.add_song_to_library(command)
    after = now_ms().value

    payload = song_repo.upsert_songs_for_library.call_args.args[1][0]
    assert payload["scanned_at"] is not None
    assert before <= int(payload["scanned_at"]) <= after


@pytest.mark.unit
def test_add_song_to_library_missing_library_raises_lookup_error() -> None:
    db, library_repo, song_repo, *_ = _make_library_db()
    library_repo.get_library_by_uuid = MagicMock(return_value=None)
    command = SongUpsertInput(library=_TEST_LIBRARY, path="/music/a.mp3")

    with pytest.raises(LookupError, match="does not exist"):
        db.add_song_to_library(command)
    song_repo.upsert_songs_for_library.assert_not_called()


@pytest.mark.unit
def test_add_song_to_library_unknown_uuid_is_unresolvable() -> None:
    db, library_repo, song_repo, *_ = _make_library_db()
    library_repo.get_library_by_uuid = MagicMock(return_value=None)
    command = SongUpsertInput(
        library=LibraryIdentity(library_uuid="08042357-9a97-5066-a9bf-bcab3b77ec8b", name="TestLib"),
        path="/music/a.mp3",
    )

    with pytest.raises(LookupError, match="does not exist"):
        db.add_song_to_library(command)
    library_repo.get_library_by_uuid.assert_called_once_with("08042357-9a97-5066-a9bf-bcab3b77ec8b")
    song_repo.upsert_songs_for_library.assert_not_called()


@pytest.mark.unit
def test_add_song_to_library_empty_repo_result_raises_runtime_error() -> None:
    db, _, song_repo, _, _, _, _, song_state_repo, _ = _make_library_db()
    song_repo.list_existing_song_paths = MagicMock(return_value=[])
    song_repo.upsert_songs_for_library = MagicMock(return_value=[])
    scan = SongScanUpdate(normalized_path="a.mp3", file_size=100, modified_time=1000)
    command = SongUpsertInput(library=_TEST_LIBRARY, path="/music/a.mp3", scan=scan)

    with pytest.raises(RuntimeError, match="unexpected row count"):
        db.add_song_to_library(command)
    song_state_repo.initialize_song_states.assert_not_called()


@pytest.mark.unit
def test_add_song_to_library_state_init_exception_propagates_without_exposing_id() -> None:
    """A state-initialization failure propagates through the facade without
    exposing the generated id as a successful semantic result."""
    db, _, song_repo, _, _, _, _, song_state_repo, _ = _make_library_db()
    song_repo.list_existing_song_paths = MagicMock(return_value=[])
    song_repo.upsert_songs_for_library = MagicMock(return_value=[42])
    song_repo.get_song_ids_by_paths = MagicMock(return_value={"/music/a.mp3": 42})
    song_state_repo.initialize_song_states = MagicMock(side_effect=RuntimeError("state init failed"))
    scan = SongScanUpdate(normalized_path="a.mp3", file_size=100, modified_time=1000)
    command = SongUpsertInput(library=_TEST_LIBRARY, path="/music/a.mp3", scan=scan)

    with pytest.raises(RuntimeError, match="state init failed"):
        db.add_song_to_library(command)

    # The generated id (42) reaches only the private state initializer; it is
    # never returned as a semantic SongIdentity because the exception fires
    # before the facade can return.
    song_repo.upsert_songs_for_library.assert_called_once()
    song_state_repo.initialize_song_states.assert_called_once_with([42], commit=False)


@pytest.mark.unit
def test_add_song_to_library_rejects_raw_dict_payload() -> None:
    """The old raw SQL-column dict / generated-int contract is rejected.

    Passing a raw storage dict no longer satisfies the typed facade; it is
    treated as an invalid command shape rather than a repository payload.
    """
    db, *_ = _make_library_db()
    with pytest.raises(AttributeError):
        db.add_song_to_library({"path": "/music/a.mp3", "file_size": 1})  # type: ignore[arg-type]


# ── insert / update / recovery / negative (P4 invariants) ──────────────────


@pytest.mark.unit
def test_add_song_to_library_same_natural_path_inserts_then_updates() -> None:
    """Re-upserting the same natural path + library updates the one row in place.

    The facade forwards a stable unique ``(library_id, path)`` key (identical
    ``path``/``normalized_path`` on both calls) so the repository's unique
    ``uq_songs_library_path`` conflict upsert updates rather than duplicates, and
    it refreshes the scan metadata on the update. A stateful repository double
    emulates that unique-on-path behaviour to prove the facade presents the same
    key and refreshable scan columns across insert and update. The repository
    remains the owner of the actual one-row/no-duplicate DB guarantee (pinned by
    ``test_song_repo.py::test_upsert_song_insert`` / ``test_upsert_song_update``).
    """
    db, _, song_repo, _, _, _, _, song_state_repo, _ = _make_library_db()

    # In-memory rows keyed by the natural physical path; an id is assigned on
    # first insert and kept on a same-path update (mirrors on_conflict semantics).
    rows: dict[str, dict[str, object]] = {}

    def _upsert_tracking(library_id: int, payloads: list[dict[str, object]], *, commit: bool = True) -> list[int]:
        ids: list[int] = []
        for payload in payloads:
            path = str(payload["path"])
            if path in rows:
                rows[path].update({k: v for k, v in payload.items() if k != "path"})
            else:
                rows[path] = {**payload, "id": len(rows) + 1}
            ids.append(int(rows[path]["id"]))  # type: ignore[arg-type]
        return ids

    song_repo.upsert_songs_for_library = MagicMock(side_effect=_upsert_tracking)
    song_repo.list_existing_song_paths = MagicMock(
        side_effect=lambda _library_id, paths: [p for p in paths if p in rows]
    )
    song_repo.get_song_ids_by_paths = MagicMock(
        side_effect=lambda _library_id, paths: {p: int(rows[p]["id"]) for p in paths}  # type: ignore[arg-type]
    )

    def _command(file_size: int, modified_time: int) -> SongUpsertInput:
        scan = SongScanUpdate(
            normalized_path="a.mp3",
            file_size=file_size,
            modified_time=modified_time,
            duration_seconds=120.5,
        )
        return SongUpsertInput(library=_TEST_LIBRARY, path="/music/a.mp3", scan=scan)

    first = db.add_song_to_library(_command(file_size=100, modified_time=1000))
    assert first == SongIdentity(library=_TEST_LIBRARY, normalized_path="a.mp3")
    assert isinstance(first, SongIdentity)
    assert not isinstance(first, int)

    second = db.add_song_to_library(_command(file_size=200, modified_time=2000))

    assert len(rows) == 1  # no duplicate row under the stable natural key
    stored = rows["/music/a.mp3"]
    assert stored["file_size"] == 200
    assert stored["modified_time"] == 2000
    assert second == first  # same natural identity, same underlying storage row

    calls = song_repo.upsert_songs_for_library.call_args_list
    assert len(calls) == 2
    assert calls[0].args[1][0]["path"] == calls[1].args[1][0]["path"]
    assert calls[0].args[1][0]["normalized_path"] == calls[1].args[1][0]["normalized_path"]
    # Create-only initialization: the first upsert inserts and initializes,
    # the same-path re-upsert preserves the existing states (no re-init).
    assert song_state_repo.initialize_song_states.call_count == 1


@pytest.mark.unit
def test_add_song_to_library_rejects_scanless_command() -> None:
    """A scan-less ``SongUpsertInput`` cannot satisfy the songs row contract.

    ``file_size``/``modified_time`` are non-null columns sourced only from scan
    (no DB default, no other source), so the private mapper rejects a command
    with ``scan=None`` before any half-built payload reaches the repository.
    Scan-less commands were never a supported legacy upsert path, so no prior
    error behaviour is displaced.
    """
    db, _, song_repo, *_ = _make_library_db()
    command = SongUpsertInput(library=_TEST_LIBRARY, path="/music/a.mp3")

    with pytest.raises(ValueError, match="requires scan metadata"):
        db.add_song_to_library(command)
    song_repo.upsert_songs_for_library.assert_not_called()


@pytest.mark.unit
def test_add_song_to_library_rejects_int_command() -> None:
    """A direct integer no longer satisfies the corrected facade contract.

    Only a ``SongUpsertInput`` is accepted; an int is treated as an invalid
    command shape (accessing ``.library`` on it fails) rather than a storage id
    the facade could ever return or accept.
    """
    db, *_ = _make_library_db()
    with pytest.raises(AttributeError):
        db.add_song_to_library(42)  # type: ignore[arg-type]


@pytest.mark.unit
def test_add_song_to_library_rejects_blank_identity_and_path_at_command_boundary() -> None:
    """Invalid path/identity values are rejected by the frozen value objects
    before any facade work runs (facade-level negative coverage)."""
    # Blank physical path is rejected by the frozen SongUpsertInput.
    with pytest.raises(ValueError):
        SongUpsertInput(library=_TEST_LIBRARY, path="   ")
    # Blank/invalid library identity values are rejected by LibraryIdentity.
    with pytest.raises(ValueError):
        LibraryIdentity(library_uuid="0e5c96e9-bd42-5132-82a4-2d4673000713", name="   ")
    with pytest.raises(ValueError):
        LibraryIdentity(library_uuid="ed81e8bd-4e83-5d31-b3a4-6fed62da4eeb", name="TestLib", root_path="   ")


@pytest.mark.unit
def test_add_song_to_library_retry_after_state_init_failure_succeeds() -> None:
    """Recovery is the existing caller retry: re-invoking the idempotent intent
    after a state-init failure succeeds.

    The repository upsert and the state initializer share one facade-owned
    transaction (``commit=False``), so a state-init failure rolls the row back
    and the caller's supported recovery is a retry that re-runs both; the row
    is still treated as new on the retry. No restart protocol is invented here.
    """
    db, _, song_repo, _, _, _, _, song_state_repo, _ = _make_library_db()
    song_repo.list_existing_song_paths = MagicMock(return_value=[])
    song_repo.upsert_songs_for_library = MagicMock(return_value=[42])
    song_repo.get_song_ids_by_paths = MagicMock(return_value={"/music/a.mp3": 42})
    song_state_repo.initialize_song_states = MagicMock(side_effect=[RuntimeError("state init failed"), None])
    scan = SongScanUpdate(normalized_path="a.mp3", file_size=100, modified_time=1000)
    command = SongUpsertInput(library=_TEST_LIBRARY, path="/music/a.mp3", scan=scan)

    with pytest.raises(RuntimeError, match="state init failed"):
        db.add_song_to_library(command)

    result = db.add_song_to_library(command)
    assert result == SongIdentity(library=_TEST_LIBRARY, normalized_path="a.mp3")
    assert song_repo.upsert_songs_for_library.call_count == 2
    assert song_state_repo.initialize_song_states.call_count == 2


@pytest.mark.unit
def test_remove_song_by_command_deletes_privately() -> None:
    db, library_repo, song_repo, *_ = _make_library_db()
    song_repo.get_song_by_normalized_path = MagicMock(return_value=_song_row())
    song_repo.delete_song = MagicMock()

    removed = db.remove_song(SongRemoval(song_identity=_song()))

    assert removed is True
    library_repo.get_library_by_uuid.assert_called_once_with("de131b32-af5c-5a84-8874-58e3dc0e2dcd")
    song_repo.get_song_by_normalized_path.assert_called_once_with(1, "a.mp3")
    song_repo.delete_song.assert_called_once_with(10)


@pytest.mark.unit
def test_remove_song_missing_is_false() -> None:
    # A removal whose locator no longer resolves returns a deterministic
    # ``False`` (ADR-048) — not an error, not an integer fallback.
    db, _, song_repo, *_ = _make_library_db()
    song_repo.get_song_by_normalized_path = MagicMock(return_value=None)
    song_repo.delete_song = MagicMock()

    assert db.remove_song(SongRemoval(song_identity=_song())) is False
    song_repo.delete_song.assert_not_called()


@pytest.mark.unit
def test_remove_song_missing_library_is_false() -> None:
    db, library_repo, song_repo, *_ = _make_library_db()
    library_repo.get_library_by_uuid = MagicMock(return_value=None)
    song_repo.delete_song = MagicMock()

    assert db.remove_song(SongRemoval(song_identity=_song())) is False
    song_repo.delete_song.assert_not_called()


@pytest.mark.unit
def test_remove_song_by_path_returns_silently_when_not_found() -> None:
    db, _, song_repo, *_ = _make_library_db()
    song_repo.get_song_by_path = MagicMock(return_value=None)
    song_repo.delete_song = MagicMock()

    db.remove_song_by_path("/nonexistent.mp3", _LIB)

    song_repo.delete_song.assert_not_called()


@pytest.mark.unit
def test_remove_song_by_path_resolves_row_and_deletes_privately() -> None:
    # The facade locates the song by (library, path) and consumes the generated
    # row id only inside the private delete (ADR-048); no storage id surfaces.
    db, _, song_repo, *_ = _make_library_db()
    song_repo.get_song_by_path = MagicMock(return_value=_song_row())
    song_repo.delete_song = MagicMock()

    db.remove_song_by_path("/music/a.mp3", _LIB)

    song_repo.get_song_by_path.assert_called_once_with("/music/a.mp3", 1)
    song_repo.delete_song.assert_called_once_with(10)


# ── Tag operations (domain contract) ──────────────────────────────────────


@pytest.mark.unit
def test_get_tag_accepts_tag_identity() -> None:
    db, _, _, _, _, tag_repo, *_ = _make_library_db()
    tag_repo.get_tag_ids_by_identities = MagicMock(return_value={("default", "artist", "X"): 5})
    tag_repo.get_tags_by_ids = MagicMock(return_value=[{"name": "artist", "value": "X", "namespace": ""}])

    result = db.get_tag(_tag())

    assert result == _tag()
    tag_repo.get_tag_ids_by_identities.assert_called_once()


@pytest.mark.unit
def test_ensure_tag_returns_tag_identity() -> None:
    db, _, _, _, _, tag_repo, *_ = _make_library_db()
    tag_repo.get_or_create_tag = MagicMock(return_value=1)
    identity = _tag(namespace="nom")

    result = db.ensure_tag(identity)

    assert result == identity
    tag_repo.get_or_create_tag.assert_called_once_with("artist", "X", "nom")


@pytest.mark.unit
def test_get_tag_preserves_nom_namespace() -> None:
    db, _, _, _, _, tag_repo, *_ = _make_library_db()
    tag_repo.get_tag_ids_by_identities = MagicMock(return_value={("nom", "artist", "X"): 5})
    tag_repo.get_tags_by_ids = MagicMock(return_value=[{"name": "artist", "value": "X", "namespace": "nom"}])

    result = db.get_tag(_tag("artist", "X", namespace="nom"))

    assert result == _tag("artist", "X", namespace="nom")
    assert result.namespace == "nom"
    tag_repo.get_tag_ids_by_identities.assert_called_once_with([{"namespace": "nom", "name": "artist", "value": "X"}])


@pytest.mark.unit
def test_domain_tag_identities_hide_storage_ids() -> None:
    """TagRef/TagUsage returned by the facade carry no storage primary keys (ADR-032/041)."""
    db, _, _, _, _, tag_repo, *_ = _make_library_db()
    tag_repo.list_tags = MagicMock(return_value=[{"id": 7, "name": "artist", "value": "X", "namespace": ""}])

    result = db.list_tags()

    assert isinstance(result[0], TagRef)
    assert not hasattr(result[0], "id")
    assert not hasattr(result[0], "tag_id")
    assert result[0].namespace == "default"


@pytest.mark.unit
def test_find_songs_with_tag_returns_domain_songs() -> None:
    db, _, _, _, _, _, song_tag_repo, *_ = _make_library_db()
    song_tag_repo.search_songs_by_tag = MagicMock(return_value=[_song_row()])

    result = db.find_songs_with_tag(_tag("genre", "Rock"), limit=10)

    assert len(result) == 1
    assert isinstance(result[0], Song)
    assert not hasattr(result[0], "song_id")  # generated songs.id stays persistence-private
    song_tag_repo.search_songs_by_tag.assert_called_once_with("genre", "Rock", namespace="default", limit=10, offset=0)


@pytest.mark.unit
def test_find_songs_with_tag_contains_returns_domain_songs() -> None:
    db, _, _, _, _, _, song_tag_repo, *_ = _make_library_db()
    song_tag_repo.search_songs_by_tag_contains = MagicMock(return_value=[_song_row()])

    result = db.find_songs_with_tag_contains(_tag("nom:mood-strict", "happy"), limit=5)

    assert len(result) == 1
    assert isinstance(result[0], Song)
    song_tag_repo.search_songs_by_tag_contains.assert_called_once_with(
        "nom:mood-strict", "happy", namespace="default", limit=5
    )


@pytest.mark.unit
def test_find_songs_with_tag_pattern_returns_domain_songs() -> None:
    db, _, _, _, _, _, song_tag_repo, *_ = _make_library_db()
    song_tag_repo.search_songs_by_tag_pattern = MagicMock(return_value=[_song_row()])

    result = db.find_songs_with_tag_pattern("artist", "%Beatles%", limit=5)

    assert len(result) == 1
    assert isinstance(result[0], Song)
    song_tag_repo.search_songs_by_tag_pattern.assert_called_once_with(
        "artist", "%Beatles%", namespace="default", limit=5
    )


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
    song_tag_repo.search_songs_by_numeric_tag.assert_called_once_with(
        "nom:bpm", "120", namespace="default", limit=5, offset=20
    )


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
    song_tag_repo.count_songs_by_tag.assert_called_once_with("genre", "Rock", namespace="default")


@pytest.mark.unit
def test_count_songs_by_numeric_tag_delegates() -> None:
    db, _, _, _, _, _, song_tag_repo, *_ = _make_library_db()
    song_tag_repo.count_songs_by_numeric_tag = MagicMock(return_value=7)

    assert db.count_songs_by_numeric_tag("nom:bpm", 120.0) == 7
    song_tag_repo.count_songs_by_numeric_tag.assert_called_once_with("nom:bpm", 120.0, namespace="default")


@pytest.mark.unit
def test_replace_song_tags_resolves_set_based() -> None:
    db, _, song_repo, _, _, tag_repo, song_tag_repo, *_ = _make_library_db()
    song_repo.get_song_by_normalized_path = MagicMock(return_value={"id": 7})
    tag_repo.get_or_create_tags_batch = MagicMock(return_value={("default", "artist", "X"): 5})
    song_tag_repo.replace_song_tags = MagicMock()

    db.replace_song_tags(_song(), [_assignment()])

    tag_repo.get_or_create_tags_batch.assert_called_once_with(
        [{"namespace": "default", "name": "artist", "value": "X"}]
    )
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
    tag_repo.get_tag_ids_by_identities = MagicMock(return_value={("default", "artist", "X"): 5})
    tag_repo.get_or_create_tags_batch = MagicMock(return_value={("default", "artist", "Y"): 6})
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
    tag_repo.get_tag_ids_by_identities = MagicMock(return_value={("default", "artist", "X"): 5})
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

    result = db.admin_cleanup_orphaned_tags()

    assert result == TagCleanupResult(deleted=3, orphaned=3)
    tag_repo.get_orphaned_tag_ids.assert_called_once_with()
    tag_repo.delete_tags_by_ids.assert_called_once_with([1, 2, 3])


@pytest.mark.unit
def test_list_tag_value_frequencies_calls_batch() -> None:
    db, _, _, _, _, tag_repo, *_ = _make_library_db()
    tag_repo.get_tag_value_frequencies_batch = MagicMock(
        return_value={
            "genre": [("default", "Rock", 10), ("default", "Pop", 5)],
        }
    )

    result = db.list_tag_value_frequencies(["genre"], limit=100)

    # The facade reduces the namespace-bearing repo result to (value, count).
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

    db.hydrate_song(sentinel.locator, sentinel.input)

    hydration_repo.hydrate_song.assert_called_once_with(sentinel.locator, sentinel.input)


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
def test_maintenance_prune_orphaned_songs_returns_count_only() -> None:
    """``prune_orphaned_songs`` is locator-free and returns only an int count.

    Persistence resolves the orphan row handles privately and never exposes a
    generated ``songs.id``, row, or handle to the caller.
    """
    db, song_repo, _ = _make_songs_db()
    song_repo.list_orphaned_song_ids = MagicMock(return_value=[7, 9])

    result = db.prune_orphaned_songs()

    assert result == 2
    assert isinstance(result, int)
    assert not hasattr(result, "song")
    song_repo.list_orphaned_song_ids.assert_called_once_with()
    assert song_repo.delete_song.call_args_list == [call(7), call(9)]


@pytest.mark.unit
def test_maintenance_prune_orphaned_songs_empty_returns_zero() -> None:
    db, song_repo, _ = _make_songs_db()
    song_repo.list_orphaned_song_ids = MagicMock(return_value=[])

    result = db.prune_orphaned_songs()

    assert result == 0
    song_repo.delete_song.assert_not_called()


@pytest.mark.unit
def test_maintenance_cleanup_orphaned_tags() -> None:
    db, tag_repo, _ = _make_tags_db()
    tag_repo.get_orphaned_tag_ids = MagicMock(return_value=[1])
    tag_repo.delete_tags_by_ids = MagicMock(return_value=1)

    result = db.admin_cleanup_orphaned_tags()

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

    db.admin_truncate_tags()

    tag_repo.truncate_tags.assert_called_once_with()


@pytest.mark.unit
def test_maintenance_truncate_song_tag_assignments() -> None:
    db, _, song_tag_repo = _make_tags_db()
    song_tag_repo.truncate_song_tag_assignments = MagicMock()

    db.admin_truncate_song_tag_assignments()

    song_tag_repo.truncate_song_tag_assignments.assert_called_once_with()


@pytest.mark.unit
def test_maintenance_truncate_scan_records() -> None:
    scan_repo = MagicMock()
    db = LibraryScansDb(session=MagicMock(), scan_repo=scan_repo, library_repo=MagicMock())

    db.truncate_scan_records()

    scan_repo.truncate_scans.assert_called_once_with()


@pytest.mark.unit
def test_maintenance_reset_library_data_delegates_exactly_once() -> None:
    """``db.library.maintenance.reset_library_data`` delegates to LibraryResetRepo
    exactly once and returns ``None`` (no storage rows/ids/counts/handles)."""
    db, *_ = _make_library_db()
    reset_repo = db.maintenance._library_reset_repo
    assert isinstance(reset_repo, MagicMock)

    result = db.maintenance.reset_library_data()

    assert result is None
    reset_repo.reset_library_data.assert_called_once_with()


@pytest.mark.unit
def test_library_maintenance_exposes_no_transaction_surface() -> None:
    """The library maintenance surface exposes no transaction()/begin helper
    (AR-SDR-4 / CONTRACTS.md). The reset delegate owns its own transaction."""
    db, *_ = _make_library_db()

    for name in ("transaction", "_require_transaction", "begin", "begin_nested", "commit"):
        assert not hasattr(db.maintenance, name), f"db.library.maintenance must not expose '{name}' (AR-SDR-4)."

    # Only the reset intent is exposed on the destructive reset surface.
    assert {n for n in dir(db.maintenance) if not n.startswith("_")} == {"reset_library_data"}


@pytest.mark.unit
class TestMoveLibrarySong:
    """Atomic Song-move intent delegation and contract (ADR-048).

    ``db.move_library_song(command)`` (LibraryDb) forwards one typed
    ``SongPathUpdate`` to the LibrarySongsDb intent, which resolves the source
    locator's natural library privately and maps it onto exactly one
    ``SongRepository.move_song(library_id, source_normalized_path, payload)``
    call — the transaction owner. The facade neither opens a transaction, nor
    inserts/deletes/recreates a row, so associations stay attached. A stale/
    missing source locator is a ``None`` miss (superseding the historical
    ``LookupError``); the destination ``SongIdentity`` is returned on success.
    """

    @staticmethod
    def _source(normalized_path: str = "a.mp3") -> SongIdentity:
        return SongIdentity(library=_TEST_LIBRARY, normalized_path=normalized_path)

    @staticmethod
    def _command(source_identity: SongIdentity | None = None, **scan_overrides: object) -> SongPathUpdate:
        scan_defaults: dict = {
            "normalized_path": "sub/b.mp3",
            "file_size": 4321,
            "modified_time": 8765,
            "duration_seconds": 223.5,
            "is_valid": True,
            "scanned_at": 5555,
        }
        scan_defaults.update(scan_overrides)
        return SongPathUpdate(
            song_identity=source_identity if source_identity is not None else TestMoveLibrarySong._source("a.mp3"),
            new_path="/music/b.mp3",
            scan=SongScanUpdate(**scan_defaults),  # type: ignore[arg-type]
        )

    def test_songs_intent_resolves_source_privately_and_maps_to_single_repo_call(self) -> None:
        db, library_repo, song_repo, *_ = _make_library_db()
        song_repo.move_song.return_value = True
        command = self._command()

        result = db._songs.move_library_song(command)

        # The source locator's UUID is resolved privately to id 1; neither it
        # nor any generated song id crosses the facade.
        library_repo.get_library_by_uuid.assert_called_once_with("de131b32-af5c-5a84-8874-58e3dc0e2dcd")
        song_repo.move_song.assert_called_once_with(
            1,
            "a.mp3",  # source normalized path (source-locator predicate)
            {
                "path": "/music/b.mp3",
                "normalized_path": "sub/b.mp3",
                "file_size": 4321,
                "modified_time": 8765,
                "duration_seconds": 223.5,
                "is_valid": 1,
                "scanned_at": 5555,
            },
        )
        # The intent returns the destination SongIdentity locator on success.
        assert result == SongIdentity(library=_TEST_LIBRARY, normalized_path="sub/b.mp3")

    def test_is_valid_maps_bool_to_int_flag(self) -> None:
        db, _, song_repo, *_ = _make_library_db()
        song_repo.move_song.return_value = True

        db._songs.move_library_song(self._command(is_valid=False))

        payload = song_repo.move_song.call_args.args[2]
        assert payload["is_valid"] == 0

    def test_none_scanned_at_uses_persistence_now_ms_default(self) -> None:
        from nomarr.helpers.time_helper import now_ms

        db, _, song_repo, *_ = _make_library_db()
        song_repo.move_song.return_value = True
        before = now_ms().value

        db._songs.move_library_song(self._command(scanned_at=None))

        after = now_ms().value
        payload = song_repo.move_song.call_args.args[2]
        assert before <= payload["scanned_at"] <= after

    def test_stale_source_returns_none_without_replacement(self) -> None:
        """A missing/stale source row is a None miss (ADR-048) — not a
        LookupError, and never an integer fallback or fabricated replacement."""
        db, _, song_repo, *_ = _make_library_db()
        song_repo.move_song.return_value = False

        result = db._songs.move_library_song(self._command())

        assert result is None
        song_repo.move_song.assert_called_once()
        # No replacement row is created by a stale-source miss.
        song_repo.add_song.assert_not_called()

    def test_missing_owning_library_is_a_none_miss(self) -> None:
        """A source locator whose library cannot be resolved is a stale source ->
        None miss; no repo write occurs and nothing is fabricated."""
        db, library_repo, song_repo, *_ = _make_library_db()
        library_repo.get_library_by_uuid.return_value = None

        result = db._songs.move_library_song(self._command())

        assert result is None
        song_repo.move_song.assert_not_called()

    def test_unknown_uuid_source_is_a_none_miss_without_repo_call(self) -> None:
        """A source locator whose UUID is not registered is a stale source ->
        None miss; the uuid is looked up once and no repo write occurs."""
        db, library_repo, song_repo, *_ = _make_library_db()
        library_repo.get_library_by_uuid.return_value = None
        command = self._command(
            source_identity=SongIdentity(
                library=LibraryIdentity(
                    library_uuid="f517e48b-30ab-5e01-8094-623b0fb245b7", name="main", root_path=None
                ),
                normalized_path="a.mp3",
            ),
        )

        result = db._songs.move_library_song(command)

        assert result is None
        library_repo.get_library_by_uuid.assert_called_once_with("f517e48b-30ab-5e01-8094-623b0fb245b7")
        song_repo.move_song.assert_not_called()

    def test_none_normalized_path_rejected_before_any_write(self) -> None:
        db, _, song_repo, *_ = _make_library_db()

        with pytest.raises(ValueError, match="normalized_path"):
            db._songs.move_library_song(self._command(normalized_path=None))

        song_repo.move_song.assert_not_called()

    def test_repository_failure_propagates_and_intent_issues_single_call(self) -> None:
        """A repository uniqueness/rollback failure propagates unchanged; the
        facade issues exactly one repo call (no retry, no second partial write,
        no delete/recreate fallback) — atomicity is the repo's guarantee."""
        from nomarr.helpers.exceptions import DuplicateEntityError

        db, _, song_repo, *_ = _make_library_db()
        song_repo.move_song.side_effect = DuplicateEntityError("dup (library_id,path)")

        with pytest.raises(DuplicateEntityError):
            db._songs.move_library_song(self._command())

        song_repo.move_song.assert_called_once()

    def test_library_db_forwarder_delegates_one_typed_command(self) -> None:
        db, *_ = _make_library_db()
        db._songs.move_library_song = MagicMock()  # isolate the LibraryDb forwarder
        command = self._command()

        db.move_library_song(command)

        db._songs.move_library_song.assert_called_once_with(command)

    def test_no_two_call_surface_and_no_session_mechanics_exposed(self) -> None:
        """The retired path + scan-metadata two-call choreography is gone and the
        facade exposes no transaction/begin/commit surface (AR-SDR-4)."""
        db, *_ = _make_library_db()
        for facade in (db, db._songs):
            assert not hasattr(facade, "update_library_song_path")
            assert not hasattr(facade, "update_library_song_scan_metadata")
            for name in ("transaction", "begin", "begin_nested", "commit"):
                assert not hasattr(facade, name), f"move surface must not expose '{name}'"
        assert hasattr(db, "move_library_song")
        assert hasattr(db._songs, "move_library_song")

    def test_move_intent_issues_only_the_single_update_call(self) -> None:
        """The move intent performs a single UPDATE — it never issues a delete,
        insert, replace-songs, or second metadata write, so associations
        (tags/state/streams) stay attached to the stable row."""
        db, _, song_repo, *_ = _make_library_db()
        song_repo.move_song.return_value = True

        db._songs.move_library_song(self._command())

        # The repo's only recorded interaction is the single move_song update.
        assert len(song_repo.method_calls) == 1
        assert song_repo.method_calls[0][0] == "move_song"
        song_repo.move_song.assert_called_once()
        song_repo.delete_song.assert_not_called()
        song_repo.add_song.assert_not_called()


# ── list_songs_with_state (typed state-read owner, Plan C P2) ────────────


def _row(song_id: int = 10, normalized_path: str = "a.mp3", *, scanned_at: int = 1000) -> dict:
    row = dict(_SONG_ROW)
    row.update(id=song_id, normalized_path=normalized_path, scanned_at=scanned_at)
    return row


@pytest.mark.unit
def test_list_songs_with_state_returns_typed_candidates() -> None:
    db, library_repo, song_repo, _, _, _, _, song_state_repo, _ = _make_library_db()
    song_state_repo.list_songs_in_state = MagicMock(return_value=[10, 11])
    song_repo.get_songs_by_ids = MagicMock(return_value=[_row(), _row(11, "b.mp3", scanned_at=2000)])
    song_state_repo.get_song_states_for_songs = MagicMock(
        return_value={10: {"processed", "hydrated"}, 11: {"processed"}}
    )
    library_repo.get_libraries_by_ids = MagicMock(return_value=[dict(_LIBRARY_ROW)])

    result = db.list_songs_with_state("processed")

    assert len(result) == 2
    # Default ordering: (library name, root_path, normalized_path).
    assert [c.identity.normalized_path for c in result] == ["a.mp3", "b.mp3"]
    a, _b = result
    assert isinstance(a, SongStateCandidate)
    assert a.identity == SongIdentity(library=_TEST_LIBRARY, normalized_path="a.mp3")
    assert a.identity.library == _TEST_LIBRARY
    assert isinstance(a.song, Song)
    assert a.song.normalized_path == "a.mp3"
    assert a.song.path == "/music/a.mp3"
    assert a.states == ("hydrated", "processed")  # sorted state names, never ids
    # No generated key / storage identity crosses the boundary.
    assert not hasattr(a.song, "song_id")
    assert not hasattr(a.song, "library_id")
    assert not hasattr(a.identity, "song_id")
    song_state_repo.list_songs_in_state.assert_called_once_with("processed")
    song_repo.get_songs_by_ids.assert_called_once_with([10, 11])
    song_state_repo.get_song_states_for_songs.assert_called_once_with([10, 11])


@pytest.mark.unit
def test_list_songs_with_state_library_scoped_filters_owners() -> None:
    db, library_repo, song_repo, _, _, _, _, song_state_repo, _ = _make_library_db()
    song_state_repo.list_songs_in_state = MagicMock(return_value=[10, 11, 12])
    song_repo.get_library_ids_for_songs = MagicMock(return_value={10: 1, 11: 1, 12: 2})
    song_repo.get_songs_by_ids = MagicMock(return_value=[_row(), _row(11, "b.mp3")])
    song_state_repo.get_song_states_for_songs = MagicMock(return_value={10: {"processed"}, 11: {"processed"}})
    library_repo.get_libraries_by_ids = MagicMock(return_value=[dict(_LIBRARY_ROW)])

    result = db.list_songs_with_state("processed", library=_TEST_LIBRARY)

    assert [c.identity.normalized_path for c in result] == ["a.mp3", "b.mp3"]
    # The library-3 song (id 12) is filtered out by its owning storage library.
    song_repo.get_library_ids_for_songs.assert_called_once_with([10, 11, 12])
    song_repo.get_songs_by_ids.assert_called_once_with([10, 11])


@pytest.mark.unit
def test_list_songs_with_state_unknown_library_is_empty() -> None:
    db, library_repo, song_repo, _, _, _, _, song_state_repo, _ = _make_library_db()
    song_state_repo.list_songs_in_state = MagicMock(return_value=[10])
    library_repo.get_library_by_uuid = MagicMock(return_value=None)

    result = db.list_songs_with_state("processed", library=_TEST_LIBRARY)

    assert result == []
    song_repo.get_songs_by_ids.assert_not_called()


@pytest.mark.unit
def test_list_songs_with_state_empty_and_blank_are_deterministic() -> None:
    db, _, song_repo, _, _, _, _, song_state_repo, _ = _make_library_db()
    # A song that is in no state (or the state does not exist) is a [] miss.
    song_state_repo.list_songs_in_state = MagicMock(return_value=[])

    assert db.list_songs_with_state("") == []
    assert db.list_songs_with_state("no_such_state") == []
    song_state_repo.list_songs_in_state.assert_called_once_with("no_such_state")
    song_repo.get_songs_by_ids.assert_not_called()


@pytest.mark.unit
def test_list_songs_with_state_duplicate_handles_are_deterministic() -> None:
    db, library_repo, song_repo, _, _, _, _, song_state_repo, _ = _make_library_db()
    song_state_repo.list_songs_in_state = MagicMock(return_value=[11, 10, 11, 10])
    song_repo.get_songs_by_ids = MagicMock(return_value=[_row(), _row(11, "b.mp3")])
    song_state_repo.get_song_states_for_songs = MagicMock(return_value={10: {"processed"}, 11: {"processed"}})
    library_repo.get_libraries_by_ids = MagicMock(return_value=[dict(_LIBRARY_ROW)])

    result = db.list_songs_with_state("processed")

    assert [candidate.identity.normalized_path for candidate in result] == ["a.mp3", "b.mp3"]
    song_repo.get_songs_by_ids.assert_called_once_with([11, 10])


@pytest.mark.unit
def test_list_songs_with_state_missing_owner_is_stale_locator_miss() -> None:
    db, library_repo, song_repo, _, _, _, _, song_state_repo, _ = _make_library_db()
    song_state_repo.list_songs_in_state = MagicMock(return_value=[10])
    song_repo.get_songs_by_ids = MagicMock(return_value=[_row()])
    song_state_repo.get_song_states_for_songs = MagicMock(return_value={10: {"processed"}})
    library_repo.get_libraries_by_ids = MagicMock(return_value=[])

    assert db.list_songs_with_state("processed") == []


@pytest.mark.unit
def test_list_songs_with_state_order_by_activity_and_limit() -> None:
    db, library_repo, song_repo, _, _, _, _, song_state_repo, _ = _make_library_db()
    song_state_repo.list_songs_in_state = MagicMock(return_value=[10, 11])
    # id 11 has the newest scan/tag activity.
    song_repo.get_songs_by_ids = MagicMock(return_value=[_row(), _row(11, "b.mp3", scanned_at=5000)])
    song_state_repo.get_song_states_for_songs = MagicMock(return_value={10: {"processed"}, 11: {"processed"}})
    library_repo.get_libraries_by_ids = MagicMock(return_value=[dict(_LIBRARY_ROW)])

    result = db.list_songs_with_state("processed", order_by_activity=True, limit=1)

    assert [c.identity.normalized_path for c in result] == ["b.mp3"]
    song_repo.get_songs_by_ids.assert_called_once_with([10, 11])


_MALFORMED_LIBRARY = LibraryIdentity(library_uuid="not-a-uuid", name="Malformed", root_path="/malformed")


@pytest.mark.unit
class TestUnknownAndMalformedLibraryUuidRejection:
    """ADR-049/CONTRACTS §7: unknown or malformed library UUIDs fail closed.

    There is no name or integer fallback: single-locator reads miss with
    ``None``, single-locator writes raise ``LookupError``, and set-based reads
    resolve to an empty result.
    """

    def test_get_song_unknown_uuid_is_none_and_queries_the_uuid(self) -> None:
        db, library_repo, song_repo, _, _, _, _, _, _ = _make_library_db()
        library_repo.get_library_by_uuid.return_value = None

        result = db.get_song(SongIdentity(library=_MALFORMED_LIBRARY, normalized_path="a.mp3"))

        assert result is None
        library_repo.get_library_by_uuid.assert_called_once_with("not-a-uuid")
        song_repo.get_song_by_normalized_path.assert_not_called()

    def test_list_songs_unknown_uuid_raises_without_integer_fallback(self) -> None:
        db, library_repo, song_repo, _, _, _, _, _, _ = _make_library_db()
        library_repo.get_library_by_uuid.return_value = None

        with pytest.raises(LookupError):
            db.list_songs(_MALFORMED_LIBRARY)

        library_repo.get_library_by_uuid.assert_called_once_with("not-a-uuid")
        library_repo.get_library_by_natural_key.assert_not_called()
        song_repo.get_songs_by_ids.assert_not_called()

    def test_list_songs_by_identity_unresolved_uuid_is_empty(self) -> None:
        db, library_repo, song_repo, _, _, _, _, _, _ = _make_library_db()
        library_repo.get_library_ids_by_uuids.return_value = {}
        locator = SongIdentity(library=_MALFORMED_LIBRARY, normalized_path="a.mp3")

        assert db.list_songs_by_identity([locator]) == []
        library_repo.get_library_ids_by_uuids.assert_called_once_with(["not-a-uuid"])
        song_repo.get_song_ids_by_normalized_paths.assert_not_called()


# ── Atomic batch upsert (Q3-A create-only / single transaction) ────────────


@pytest.mark.unit
def test_add_songs_to_library_batch_commits_once_and_preserves_order() -> None:
    """The batch intent seeds only new paths, commits once, returns input order."""
    db, _library_repo, song_repo, _, _, _, _, song_state_repo, _ = _make_library_db()
    song_repo.list_existing_song_paths = MagicMock(return_value=["/music/existing.mp3"])
    # The repository's RETURNING rows are intentionally in the wrong order; the
    # batch must resolve new ids by path, not positionally.
    song_repo.upsert_songs_for_library = MagicMock(return_value=[11, 10])
    song_repo.get_song_ids_by_paths = MagicMock(return_value={"/music/new.mp3": 10})
    commands = [
        SongUpsertInput(
            library=_TEST_LIBRARY,
            path="/music/new.mp3",
            scan=SongScanUpdate(normalized_path="new.mp3", file_size=1, modified_time=2),
        ),
        SongUpsertInput(
            library=_TEST_LIBRARY,
            path="/music/existing.mp3",
            scan=SongScanUpdate(normalized_path="existing.mp3", file_size=3, modified_time=4),
        ),
    ]

    result = db.add_songs_to_library_batch(commands)

    assert result == [
        SongIdentity(library=_TEST_LIBRARY, normalized_path="new.mp3"),
        SongIdentity(library=_TEST_LIBRARY, normalized_path="existing.mp3"),
    ]
    # One upsert for the whole batch, explicitly not committing (the facade owns
    # the single transaction).
    upsert_args, upsert_kwargs = song_repo.upsert_songs_for_library.call_args
    assert upsert_kwargs == {"commit": False}
    assert [payload["path"] for payload in upsert_args[1]] == ["/music/new.mp3", "/music/existing.mp3"]
    # New ids are resolved by path (never by RETURNING position); only the genuinely
    # new path (id 10) is initialized, not the existing one (id 11 in RETURNING).
    song_repo.get_song_ids_by_paths.assert_called_once_with(1, ["/music/new.mp3"])
    song_state_repo.initialize_song_states.assert_called_once_with([10], commit=False)
    # Exactly one commit; no rollback on the success path.
    db.songs._session.commit.assert_called_once_with()
    db.songs._session.rollback.assert_not_called()


@pytest.mark.unit
def test_add_songs_to_library_batch_rolls_back_on_state_init_failure() -> None:
    """An injected state-init failure rolls back the whole batch and propagates."""
    db, _, song_repo, _, _, _, _, song_state_repo, _ = _make_library_db()
    song_repo.list_existing_song_paths = MagicMock(return_value=[])
    song_repo.upsert_songs_for_library = MagicMock(return_value=[42])
    song_repo.get_song_ids_by_paths = MagicMock(return_value={"/music/a.mp3": 42})
    song_state_repo.initialize_song_states = MagicMock(side_effect=RuntimeError("state init failed"))
    command = SongUpsertInput(
        library=_TEST_LIBRARY,
        path="/music/a.mp3",
        scan=SongScanUpdate(normalized_path="a.mp3", file_size=1, modified_time=2),
    )

    with pytest.raises(RuntimeError, match="state init failed"):
        db.add_songs_to_library_batch([command])

    db.songs._session.rollback.assert_called_once_with()
    db.songs._session.commit.assert_not_called()


@pytest.mark.unit
def test_add_songs_to_library_batch_rejects_mixed_libraries() -> None:
    """A batch spanning more than one LibraryIdentity is rejected before any write."""
    db, _library_repo, song_repo, *_ = _make_library_db()
    other = LibraryIdentity(library_uuid="08042357-9a97-5066-a9bf-bcab3b77ec8b", name="Other")
    commands = [
        SongUpsertInput(
            library=_TEST_LIBRARY,
            path="/music/a.mp3",
            scan=SongScanUpdate(normalized_path="a.mp3", file_size=1, modified_time=2),
        ),
        SongUpsertInput(
            library=other,
            path="/music/b.mp3",
            scan=SongScanUpdate(normalized_path="b.mp3", file_size=1, modified_time=2),
        ),
    ]

    with pytest.raises(ValueError, match="song batch must target one library"):
        db.add_songs_to_library_batch(commands)

    song_repo.upsert_songs_for_library.assert_not_called()
    song_repo.list_existing_song_paths.assert_not_called()


@pytest.mark.unit
def test_add_songs_to_library_batch_empty_is_noop() -> None:
    """An empty batch returns ``[]`` and performs no repo or session work."""
    db, library_repo, song_repo, _, _, _, _, song_state_repo, _ = _make_library_db()

    assert db.add_songs_to_library_batch([]) == []

    # The empty short-circuit happens before any repository or transaction work.
    song_repo.upsert_songs_for_library.assert_not_called()
    song_repo.list_existing_song_paths.assert_not_called()
    song_state_repo.initialize_song_states.assert_not_called()
    library_repo.get_library_by_uuid.assert_not_called()
    db.songs._session.commit.assert_not_called()
    db.songs._session.rollback.assert_not_called()
