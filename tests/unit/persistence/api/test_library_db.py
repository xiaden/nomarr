# mypy: disable-error-code=func-returns-value
"""Unit tests for ``LibraryDb`` intent methods, shims, and maintenance wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, sentinel

import pytest

from nomarr.helpers.constants.file_states import ALL_STATE_VERTICES, STATE_TAGS_STALE
from nomarr.persistence.api.library import LibraryDb, LibraryMaintenanceDb

_NEGATIVE_FILE_STATES = [
    state for state in ALL_STATE_VERTICES if state.startswith("file_states/not_") or state == STATE_TAGS_STALE
]


def _make_library_db() -> tuple[
    LibraryDb,
    MagicMock,
    MagicMock,
    MagicMock,
    MagicMock,
    MagicMock,
    MagicMock,
]:
    libraries = MagicMock()
    files = MagicMock()
    tags = MagicMock()
    scan = MagicMock()
    file_states = MagicMock()
    vectors = MagicMock()
    db = LibraryDb(
        libraries=libraries,
        files=files,
        tags=tags,
        scan=scan,
        file_states=file_states,
        vectors=vectors,
    )
    return db, libraries, files, tags, scan, file_states, vectors


def _make_library_maintenance_db() -> tuple[LibraryMaintenanceDb, MagicMock, MagicMock]:
    files = MagicMock()
    tags = MagicMock()
    db = LibraryMaintenanceDb(files=files, tags=tags)
    return db, files, tags


@pytest.mark.unit
def test_add_library_delegates_to_libraries() -> None:
    db, libraries, _, _, _, _, _ = _make_library_db()
    payload = {"name": "Library"}
    libraries.add_library.return_value = sentinel.result

    result = db.add_library(payload)

    assert result is sentinel.result
    libraries.add_library.assert_called_once_with(payload)


@pytest.mark.unit
def test_add_file_to_library_delegates_to_canonical_tier2_helper() -> None:
    db, _, files, _, _, file_states, _ = _make_library_db()
    payload = {"path": "C:/music/new.flac"}
    files.upsert_files_for_library_with_state_init.return_value = {
        "file_ids": ["library_files/1"],
        "added": 1,
    }

    result = db.add_file_to_library("libraries/1", payload)

    assert result == "library_files/1"
    files.upsert_files_for_library_with_state_init.assert_called_once_with(
        "libraries/1",
        [payload],
        file_states=file_states,
    )


@pytest.mark.unit
def test_add_files_to_library_delegates_to_canonical_tier2_helper() -> None:
    db, _, files, _, _, file_states, _ = _make_library_db()
    payloads = [
        {"path": "C:/music/existing.flac"},
        {"path": "C:/music/new.flac"},
    ]
    files.upsert_files_for_library_with_state_init.return_value = {
        "file_ids": ["library_files/existing", "library_files/new"],
        "added": 1,
    }

    result = db.add_files_to_library("libraries/1", payloads)

    assert result == ["library_files/existing", "library_files/new"]
    files.upsert_files_for_library_with_state_init.assert_called_once_with(
        "libraries/1",
        payloads,
        file_states=file_states,
    )


@pytest.mark.unit
def test_update_library_files_delegates_to_canonical_tier2_helper() -> None:
    db, _, files, _, _, file_states, vectors = _make_library_db()
    db._streams = MagicMock()
    payloads = [
        {"path": "C:/music/existing.flac"},
        {"path": "C:/music/new.flac"},
    ]
    files.reconcile_library_files.return_value = {"added": 1, "updated": 1, "removed": 1}

    result = db.update_library_files("libraries/1", payloads, remove_missing=True)

    assert result == {"added": 1, "updated": 1, "removed": 1}
    files.reconcile_library_files.assert_called_once_with(
        "libraries/1",
        payloads,
        remove_missing=True,
        file_states=file_states,
        streams=db._streams,
        vectors=vectors,
    )


@pytest.mark.unit
def test_update_library_file_path_updates_only_path() -> None:
    db, _, files, _, _, _, _ = _make_library_db()

    db.update_library_file_path("library_files/1", "D:/moved/track.flac")

    files._update_file.assert_called_once_with("library_files/1", {"path": "D:/moved/track.flac"})


@pytest.mark.unit
def test_remove_file_cleans_output_streams_vectors_then_removes_file() -> None:
    db, _, files, _, _, _, vectors = _make_library_db()
    db._streams = MagicMock()

    db.remove_file("library_files/1")

    files.remove_files_with_derived_cleanup.assert_called_once_with(
        ["library_files/1"],
        streams=db._streams,
        vectors=vectors,
    )


@pytest.mark.unit
def test_remove_file_by_path_scoped_resolves_then_removes() -> None:
    db, _, files, _, _, _, _ = _make_library_db()
    files.get_file_by_path.return_value = {"_id": "library_files/1"}

    with patch.object(db, "remove_file") as remove_file:
        db.remove_file_by_path("C:/music/track.flac", "libraries/1")

    files.get_file_by_path.assert_called_once_with("C:/music/track.flac", "libraries/1")
    remove_file.assert_called_once_with("library_files/1")


@pytest.mark.unit
def test_remove_file_by_path_unscoped_uses_normalized_lookup() -> None:
    db, _, _, _, _, _, _ = _make_library_db()

    with (
        patch.object(db, "find_file_by_path_any_library", return_value={"_id": "library_files/9"}) as finder,
        patch.object(db, "remove_file") as remove_file,
    ):
        db.remove_file_by_path("C:/music/track.flac")

    finder.assert_called_once_with("C:/music/track.flac")
    remove_file.assert_called_once_with("library_files/9")


@pytest.mark.unit
def test_replace_file_tags_delegates_to_canonical_tier2_helper() -> None:
    db, _, _, tags, _, _, _ = _make_library_db()
    payload = [
        {"name": "genre", "value": "rock"},
        {"key": "mood", "value": "calm"},
    ]

    db.replace_file_tags("library_files/1", payload)

    tags.replace_file_tags.assert_called_once_with("library_files/1", payload)


@pytest.mark.unit
def test_replace_tag_references_delegates_to_canonical_tier2_helper() -> None:
    db, _, _, tags, _, _, _ = _make_library_db()

    db.replace_tag_references("tags/source", "tags/target")

    tags.replace_tag_references.assert_called_once_with("tags/source", "tags/target")


@pytest.mark.unit
def test_replace_selected_tag_references_delegates_to_canonical_tier2_helper() -> None:
    db, _, _, tags, _, _, _ = _make_library_db()

    db.replace_selected_tag_references(["library_files/1", "library_files/2"], "tags/source", "tags/target")

    tags.replace_tag_references.assert_called_once_with(
        "tags/source",
        "tags/target",
        file_ids=["library_files/1", "library_files/2"],
    )


@pytest.mark.unit
def test_remove_file_tags_all_names_delegates_to_canonical_tier2_helper() -> None:
    db, _, _, tags, _, _, _ = _make_library_db()

    db.remove_file_tags("library_files/1")

    tags.remove_file_tags.assert_called_once_with("library_files/1", None)


@pytest.mark.unit
def test_remove_file_tags_selected_names_delegates_to_canonical_tier2_helper() -> None:
    db, _, _, tags, _, _, _ = _make_library_db()

    db.remove_file_tags("library_files/1", ["genre"])

    tags.remove_file_tags.assert_called_once_with("library_files/1", ["genre"])


@pytest.mark.unit
def test_list_file_tags_for_files_groups_rows_by_file() -> None:
    db, _, _, tags, _, _, _ = _make_library_db()
    tags.get_tags_for_files_batch.return_value = [
        {"start_id": "library_files/1", "v": {"name": "genre", "value": "rock"}},
        {"start_id": "library_files/1", "v": {"name": "mood", "value": "calm"}},
    ]

    result = db.list_file_tags_for_files(["library_files/1", "library_files/2"], name_starts_with="g")

    assert result == {
        "library_files/1": [
            {"name": "genre", "value": "rock"},
            {"name": "mood", "value": "calm"},
        ],
        "library_files/2": [],
    }
    tags.get_tags_for_files_batch.assert_called_once_with(
        ["library_files/1", "library_files/2"],
        name_starts_with="g",
        include_edge=False,
    )


@pytest.mark.unit
def test_normalized_read_names_delegate_to_underlying_queries() -> None:
    db, _, files, tags, _, _, _ = _make_library_db()
    files.get_files_by_ids.return_value = sentinel.files
    tags.get_tags_for_file.return_value = sentinel.tags_for_file
    tags.get_tags_by_name.return_value = sentinel.tags_by_name
    tags.get_genre_tags_for_files.return_value = sentinel.genre_tags
    files.get_tracks_for_matching.return_value = sentinel.tracks
    tags.get_tag_value_frequencies.side_effect = [[("rock", 2)], [("1999", 1)]]

    assert db.list_files_by_ids(["library_files/1"]) is sentinel.files
    assert db.list_tags_for_file("library_files/1") is sentinel.tags_for_file
    assert db.list_tags_by_name("genre", 25) is sentinel.tags_by_name
    assert db.list_genre_tags_for_files(["library_files/1"]) is sentinel.genre_tags
    assert db.list_tracks_for_matching("libraries/1", limit=10) is sentinel.tracks
    assert db.list_tag_value_frequencies(["genre", "year"], 10) == {
        "genre": [("rock", 2)],
        "year": [("1999", 1)],
    }


@pytest.mark.unit
def test_add_library_folder_delegates_to_canonical_tier2_helper() -> None:
    db, _, files, _, _, _, _ = _make_library_db()
    payload = {"path": "Rock", "mtime": 123, "file_count": 2}
    files.add_library_folder.return_value = "library_folders/1"

    result = db.add_library_folder("libraries/1", payload)

    assert result == "library_folders/1"
    files.add_library_folder.assert_called_once_with("libraries/1", payload)


@pytest.mark.unit
def test_replace_library_folders_delegates_to_canonical_tier2_helper() -> None:
    db, _, files, _, _, _, _ = _make_library_db()
    payloads = [
        {"path": "Rock", "mtime": 1, "file_count": 10},
        {"path": "Jazz", "mtime": 2, "file_count": 8},
    ]

    db.replace_library_folders("libraries/1", payloads)

    files.replace_library_folders.assert_called_once_with("libraries/1", payloads)


@pytest.mark.unit
def test_maintenance_surface_is_nested_and_exposes_destructive_methods() -> None:
    db, _, _, _, _, _, _ = _make_library_db()

    assert isinstance(db.maintenance, LibraryMaintenanceDb)
    assert hasattr(db.maintenance, "truncate_files")
    assert not hasattr(db, "truncate_files")
    assert not hasattr(db, "delete_files_for_library")
    assert not hasattr(db, "delete_all_file_links_for_library")
    assert not hasattr(db, "add_tag")
    assert not hasattr(db, "upsert_tag")
    assert not hasattr(db, "delete_tag")
    assert not hasattr(db, "delete_all_tags_for_file")
    assert not hasattr(db, "upsert_file_links_batch")
    assert not hasattr(db, "delete_folders_for_library")
    assert not hasattr(db, "delete_all_folder_links_for_library")

    with patch.object(db.maintenance, "truncate_files") as truncate_files:
        db.maintenance.truncate_files()

    truncate_files.assert_called_once_with()


@pytest.mark.unit
def test_library_maintenance_db_delegates_to_underlying_aql_objects() -> None:
    db, files, tags = _make_library_maintenance_db()
    files.list_orphaned_file_ids.return_value = sentinel.orphaned_files
    tags.get_orphaned_tag_ids.return_value = sentinel.orphaned_tags
    tags.delete_tags_by_ids.return_value = sentinel.deleted_count

    assert db.list_orphaned_file_ids() is sentinel.orphaned_files
    assert db.list_orphaned_tag_ids() is sentinel.orphaned_tags
    assert db.delete_tags_by_ids(["tags/1"]) is sentinel.deleted_count

    files.list_orphaned_file_ids.assert_called_once_with()
    tags.get_orphaned_tag_ids.assert_called_once_with()
    tags.delete_tags_by_ids.assert_called_once_with(["tags/1"])


@pytest.mark.unit
def test_remove_file_delegates_to_canonical_tier2_cleanup_helper() -> None:
    db, _, files, _, _, _, vectors = _make_library_db()
    db._streams = MagicMock()

    db.remove_file("library_files/1")

    files.remove_files_with_derived_cleanup.assert_called_once_with(
        ["library_files/1"],
        streams=db._streams,
        vectors=vectors,
    )


@pytest.mark.unit
def test_remove_library_returns_false_when_library_is_missing() -> None:
    db, libraries, _, _, _, _, _ = _make_library_db()
    libraries.get_library.return_value = None

    result = db.remove_library("libraries/missing")

    assert result is False
    libraries.get_library.assert_called_once_with("libraries/missing")
    libraries.remove_library.assert_not_called()


@pytest.mark.unit
def test_remove_library_returns_true_and_deletes_existing_library() -> None:
    db, libraries, _, _, _, _, _ = _make_library_db()
    libraries.get_library.return_value = {"_id": "libraries/1"}

    result = db.remove_library("libraries/1")

    assert result is True
    libraries.get_library.assert_called_once_with("libraries/1")
    libraries.remove_library.assert_called_once_with("libraries/1")


@pytest.mark.unit
def test_remove_library_folder_delegates_to_canonical_tier2_helper() -> None:
    db, _, files, _, _, _, _ = _make_library_db()

    db.remove_library_folder("libraries/1", "library_folders/1")

    files.remove_library_folder.assert_called_once_with("libraries/1", "library_folders/1")
