# mypy: disable-error-code=func-returns-value
"""Unit tests for ``LibraryDb`` and ``LibraryMaintenanceDb`` delegation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, sentinel

import pytest

from nomarr.persistence.api.library import LibraryDb, LibraryMaintenanceDb

# ── helpers ───────────────────────────────────────────────────────────────


def _make_library_db() -> tuple[LibraryDb, MagicMock, MagicMock, MagicMock, MagicMock, MagicMock, MagicMock]:
    library_repo = MagicMock()
    file_repo = MagicMock()
    folder_repo = MagicMock()
    scan_repo = MagicMock()
    tag_repo = MagicMock()
    file_state_repo = MagicMock()
    db = LibraryDb(
        library_repo=library_repo,
        file_repo=file_repo,
        folder_repo=folder_repo,
        scan_repo=scan_repo,
        tag_repo=tag_repo,
        file_state_repo=file_state_repo,
    )
    return db, library_repo, file_repo, folder_repo, scan_repo, tag_repo, file_state_repo


def _make_library_maintenance_db() -> tuple[LibraryMaintenanceDb, MagicMock, MagicMock, MagicMock]:
    file_repo = MagicMock()
    tag_repo = MagicMock()
    folder_repo = MagicMock()
    db = LibraryMaintenanceDb(
        file_repo=file_repo,
        tag_repo=tag_repo,
        folder_repo=folder_repo,
    )
    return db, file_repo, tag_repo, folder_repo


# ── surface / contract ────────────────────────────────────────────────────


@pytest.mark.unit
def test_exposes_library_maintenance_surface() -> None:
    db, *_ = _make_library_db()

    assert isinstance(db.maintenance, LibraryMaintenanceDb)
    assert hasattr(db.maintenance, "truncate_files")
    assert hasattr(db.maintenance, "truncate_tags")
    assert hasattr(db.maintenance, "truncate_folders")
    assert hasattr(db.maintenance, "truncate_song_tag_edges")
    assert hasattr(db.maintenance, "truncate_file_links")
    assert hasattr(db.maintenance, "truncate_folder_links")
    assert hasattr(db.maintenance, "list_orphaned_file_ids")
    assert hasattr(db.maintenance, "list_orphaned_tag_ids")
    assert hasattr(db.maintenance, "delete_tags_by_ids")
    assert not hasattr(db, "truncate_files")
    assert not hasattr(db, "truncate_tags")


# ── Library CRUD ──────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_library_delegates() -> None:
    db, library_repo, *_ = _make_library_db()
    library_repo.add_library = AsyncMock(return_value=sentinel.lib_id)

    result = await db.add_library(sentinel.payload)

    assert result is sentinel.lib_id
    library_repo.add_library.assert_awaited_once_with(sentinel.payload)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_library_delegates() -> None:
    db, library_repo, *_ = _make_library_db()
    library_repo.get_library = AsyncMock(return_value=sentinel.row)

    result = await db.get_library(42)

    assert result is sentinel.row
    library_repo.get_library.assert_awaited_once_with(42)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_library_returns_none_when_missing() -> None:
    db, library_repo, *_ = _make_library_db()
    library_repo.get_library = AsyncMock(return_value=None)

    result = await db.get_library(999)

    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_library_by_name_delegates() -> None:
    db, library_repo, *_ = _make_library_db()
    library_repo.get_library_by_name = AsyncMock(return_value=sentinel.row)

    result = await db.get_library_by_name("main")

    assert result is sentinel.row
    library_repo.get_library_by_name.assert_awaited_once_with("main")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_libraries_delegates() -> None:
    db, library_repo, *_ = _make_library_db()
    library_repo.list_libraries = AsyncMock(return_value=sentinel.libs)

    result = await db.list_libraries()

    assert result is sentinel.libs
    library_repo.list_libraries.assert_awaited_once_with(enabled_only=False)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_library_keys_delegates() -> None:
    db, library_repo, *_ = _make_library_db()
    library_repo.list_library_keys = AsyncMock(return_value=sentinel.keys)

    result = await db.list_library_keys()

    assert result is sentinel.keys
    library_repo.list_library_keys.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_library_delegates() -> None:
    db, library_repo, *_ = _make_library_db()
    library_repo.update_library = AsyncMock()

    await db.update_library(1, sentinel.fields)

    library_repo.update_library.assert_awaited_once_with(1, sentinel.fields)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_remove_library_returns_false_when_not_found() -> None:
    db, library_repo, *_ = _make_library_db()
    library_repo.get_library = AsyncMock(return_value=None)

    result = await db.remove_library(999)

    assert result is False
    library_repo.remove_library.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_remove_library_returns_true_when_found() -> None:
    db, library_repo, *_ = _make_library_db()
    library_repo.get_library = AsyncMock(return_value={"id": 42})
    library_repo.remove_library = AsyncMock()

    result = await db.remove_library(42)

    assert result is True
    library_repo.remove_library.assert_awaited_once_with(42)


# ── Pipeline state ────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_pipeline_state_delegates() -> None:
    db, library_repo, *_ = _make_library_db()
    library_repo.get_pipeline_state = AsyncMock(return_value=sentinel.state)

    result = await db.get_pipeline_state(1)

    assert result is sentinel.state
    library_repo.get_pipeline_state.assert_awaited_once_with(1)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_libraries_in_axis_state_delegates() -> None:
    db, library_repo, *_ = _make_library_db()
    library_repo.get_libraries_in_axis_state = AsyncMock(return_value=sentinel.ids)

    result = await db.get_libraries_in_axis_state("scan_state", "done")

    assert result is sentinel.ids
    library_repo.get_libraries_in_axis_state.assert_awaited_once_with("scan_state", "done")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_pipeline_axis_delegates() -> None:
    db, library_repo, *_ = _make_library_db()
    library_repo.update_pipeline_axis = AsyncMock()

    await db.update_pipeline_axis(1, "scan_state", "done")

    library_repo.update_pipeline_axis.assert_awaited_once_with(1, "scan_state", "done")


# ── File read operations ─────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_file_delegates() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.get_file = AsyncMock(return_value=sentinel.file_row)

    result = await db.get_file(10)

    assert result is sentinel.file_row
    file_repo.get_file.assert_awaited_once_with(10)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_file_by_path_delegates() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.get_file_by_path = AsyncMock(return_value=sentinel.file_row)

    result = await db.get_file_by_path("/music/song.mp3", library_id=1)

    assert result is sentinel.file_row
    file_repo.get_file_by_path.assert_awaited_once_with("/music/song.mp3", 1)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_find_file_by_path_any_library_delegates() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.get_file_by_path_unscoped = AsyncMock(return_value=sentinel.file_row)

    result = await db.find_file_by_path_any_library("/music/song.mp3")

    assert result is sentinel.file_row
    file_repo.get_file_by_path_unscoped.assert_awaited_once_with("/music/song.mp3")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_files_by_ids_delegates() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.get_files_by_ids = AsyncMock(return_value=sentinel.files)

    result = await db.list_files_by_ids([1, 2, 3])

    assert result is sentinel.files
    file_repo.get_files_by_ids.assert_awaited_once_with([1, 2, 3])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_files_delegates() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.list_files = AsyncMock(return_value=sentinel.files)

    result = await db.list_files()

    assert result is sentinel.files
    file_repo.list_files.assert_awaited_once_with(filters=None, limit=None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_count_files_delegates() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.count_files = AsyncMock(return_value=42)

    result = await db.count_files()

    assert result == 42
    file_repo.count_files.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_library_ids_for_files_delegates() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.get_library_ids_for_files = AsyncMock(return_value=sentinel.mapping)

    result = await db.get_library_ids_for_files([10, 20])

    assert result is sentinel.mapping
    file_repo.get_library_ids_for_files.assert_awaited_once_with([10, 20])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_count_recently_tagged_delegates() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.count_recently_tagged = AsyncMock(return_value=7)

    result = await db.count_recently_tagged(1000)

    assert result == 7
    file_repo.count_recently_tagged.assert_awaited_once_with(1000)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_library_file_ids_delegates() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.list_library_file_ids = AsyncMock(return_value=sentinel.ids)

    result = await db.list_library_file_ids(1)

    assert result is sentinel.ids
    file_repo.list_library_file_ids.assert_awaited_once_with(1, limit=None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_library_files_delegates() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.list_library_files = AsyncMock(return_value=sentinel.files)

    result = await db.list_library_files(1)

    assert result is sentinel.files
    file_repo.list_library_files.assert_awaited_once_with(1, limit=None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_find_library_file_by_chromaprint_delegates() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.find_by_chromaprint = AsyncMock(return_value=sentinel.file_row)

    result = await db.find_library_file_by_chromaprint(1, "abc123")

    assert result is sentinel.file_row
    file_repo.find_by_chromaprint.assert_awaited_once_with(1, "abc123")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_tracks_for_matching_delegates() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.list_tracks_for_matching = AsyncMock(return_value=sentinel.tracks)

    result = await db.list_tracks_for_matching(1, limit=50)

    assert result is sentinel.tracks
    file_repo.list_tracks_for_matching.assert_awaited_once_with(1, limit=50)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_library_files_for_folder_delegates() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.list_files_for_folder = AsyncMock(return_value=sentinel.files)

    result = await db.list_library_files_for_folder(1, "Rock/ACDC")

    assert result is sentinel.files
    file_repo.list_files_for_folder.assert_awaited_once_with(1, "Rock/ACDC")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_existing_file_paths_delegates() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.list_existing_file_paths = AsyncMock(return_value=["/a.mp3"])

    result = await db.list_existing_file_paths(["/a.mp3", "/b.mp3"])

    assert result == ["/a.mp3"]
    file_repo.list_existing_file_paths.assert_awaited_once_with(["/a.mp3", "/b.mp3"])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_count_library_file_links_delegates() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.count_library_files = AsyncMock(return_value=100)

    result = await db.count_library_file_links(1)

    assert result == 100
    file_repo.count_library_files.assert_awaited_once_with(1)


# ── File mutations ────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_file_to_library_returns_first_id() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.upsert_files_for_library = AsyncMock(return_value=[42])

    result = await db.add_file_to_library(1, {"path": "/a.mp3"})

    assert result == 42
    file_repo.upsert_files_for_library.assert_awaited_once_with(1, [{"path": "/a.mp3"}])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_file_to_library_raises_on_empty_result() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.upsert_files_for_library = AsyncMock(return_value=[])

    with pytest.raises(RuntimeError, match="expected one file id"):
        await db.add_file_to_library(1, {"path": "/a.mp3"})


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_files_to_library_ensures_state_for_new_files() -> None:
    db, _, file_repo, _, _, _, file_state_repo = _make_library_db()
    file_repo.list_existing_file_paths = AsyncMock(return_value=["/existing.mp3"])
    file_repo.upsert_files_for_library = AsyncMock(return_value=[10, 20, 30])
    file_state_repo.ensure_file_state = AsyncMock()

    payloads = [
        {"path": "/existing.mp3"},
        {"path": "/new1.mp3"},
        {"path": "/new2.mp3"},
    ]
    result = await db.add_files_to_library(1, payloads, initial_state="pending")

    assert result == [10, 20, 30]
    file_repo.upsert_files_for_library.assert_awaited_once_with(1, payloads)
    # Only new files (path not in existing_paths) get ensure_file_state
    assert file_state_repo.ensure_file_state.await_count == 2
    file_state_repo.ensure_file_state.assert_any_await(20, "pending")
    file_state_repo.ensure_file_state.assert_any_await(30, "pending")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_files_to_library_skips_state_for_existing_paths() -> None:
    db, _, file_repo, _, _, _, file_state_repo = _make_library_db()
    file_repo.list_existing_file_paths = AsyncMock(return_value=["/a.mp3", "/b.mp3"])
    file_repo.upsert_files_for_library = AsyncMock(return_value=[1, 2])
    file_state_repo.ensure_file_state = AsyncMock()

    payloads = [{"path": "/a.mp3"}, {"path": "/b.mp3"}]
    await db.add_files_to_library(1, payloads, initial_state="pending")

    file_state_repo.ensure_file_state.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_library_files_reconciles_added_updated_removed() -> None:
    db, _, file_repo, _, _, _, file_state_repo = _make_library_db()
    file_repo.list_existing_file_paths = AsyncMock(return_value=[])
    file_repo.upsert_files_for_library = AsyncMock(return_value=[1, 2, 3])
    file_state_repo.ensure_file_state = AsyncMock()
    file_repo.list_library_file_ids = AsyncMock(return_value=[1, 2, 3, 4, 5])
    file_repo.remove_files = AsyncMock()

    payloads = [{"path": "/a.mp3"}, {"path": "/b.mp3"}, {"path": "/c.mp3"}]
    result = await db.update_library_files(1, payloads, remove_missing=True)

    assert result["added"] == 3
    assert result["updated"] == 0
    assert result["removed"] == 2
    file_repo.remove_files.assert_awaited_once_with([4, 5])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_library_files_no_remove_when_flag_false() -> None:
    db, _, file_repo, _, _, _, file_state_repo = _make_library_db()
    file_repo.list_existing_file_paths = AsyncMock(return_value=[])
    file_repo.upsert_files_for_library = AsyncMock(return_value=[1, 2, 3])
    file_state_repo.ensure_file_state = AsyncMock()
    file_repo.list_library_file_ids = AsyncMock(return_value=[1, 2, 3, 4, 5])
    file_repo.remove_files = AsyncMock()

    payloads = [{"path": "/a.mp3"}, {"path": "/b.mp3"}, {"path": "/c.mp3"}]
    await db.update_library_files(1, payloads, remove_missing=False)

    file_repo.remove_files.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_library_file_path_delegates() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.update_file = AsyncMock()

    await db.update_library_file_path(10, "/new/path.mp3")

    file_repo.update_file.assert_awaited_once_with(10, {"path": "/new/path.mp3"})


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_library_file_scan_metadata_includes_now() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.update_file = AsyncMock()

    await db.update_library_file_scan_metadata(10, file_size=999, modified_time=1234567890, duration_seconds=120.5)

    call_args = file_repo.update_file.call_args
    assert call_args[0][0] == 10
    fields = call_args[0][1]
    assert fields["file_size"] == 999
    assert fields["modified_time"] == 1234567890
    assert fields["duration_seconds"] == 120.5
    assert fields["is_valid"] == 1
    assert "scanned_at" in fields
    assert isinstance(fields["scanned_at"], int)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_library_file_modified_time_delegates() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.update_file = AsyncMock()

    await db.update_library_file_modified_time(10, 1234567890)

    file_repo.update_file.assert_awaited_once_with(10, {"modified_time": 1234567890})


@pytest.mark.unit
@pytest.mark.asyncio
async def test_set_library_file_chromaprint_delegates() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.update_file = AsyncMock()

    await db.set_library_file_chromaprint(10, "abc123")

    file_repo.update_file.assert_awaited_once_with(10, {"chromaprint": "abc123"})


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_library_file_last_tagged_at_delegates() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.update_file = AsyncMock()

    await db.update_library_file_last_tagged_at(10, 5555)

    file_repo.update_file.assert_awaited_once_with(10, {"last_tagged_at": 5555})


@pytest.mark.unit
@pytest.mark.asyncio
async def test_remove_file_delegates() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.delete_file = AsyncMock()

    await db.remove_file(10)

    file_repo.delete_file.assert_awaited_once_with(10)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_remove_file_by_path_scoped() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.get_file_by_path = AsyncMock(return_value={"id": 42})
    file_repo.delete_file = AsyncMock()

    await db.remove_file_by_path("/music/song.mp3", library_id=1)

    file_repo.get_file_by_path.assert_awaited_once_with("/music/song.mp3", 1)
    file_repo.delete_file.assert_awaited_once_with(42)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_remove_file_by_path_unscoped_fallback() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.get_file_by_path = AsyncMock(return_value=None)
    file_repo.get_file_by_path_unscoped = AsyncMock(return_value={"id": 77})
    file_repo.delete_file = AsyncMock()

    await db.remove_file_by_path("/music/song.mp3")

    file_repo.get_file_by_path_unscoped.assert_awaited_once_with("/music/song.mp3")
    file_repo.delete_file.assert_awaited_once_with(77)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_remove_file_by_path_returns_silently_when_not_found() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.get_file_by_path = AsyncMock(return_value=None)
    file_repo.get_file_by_path_unscoped = AsyncMock(return_value=None)
    file_repo.delete_file = AsyncMock()

    await db.remove_file_by_path("/nonexistent.mp3")

    file_repo.delete_file.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_file_delegates() -> None:
    db, _, file_repo, *_ = _make_library_db()
    file_repo.update_file = AsyncMock()

    await db.update_file(10, {"path": "/new.mp3", "file_size": 999})

    file_repo.update_file.assert_awaited_once_with(10, {"path": "/new.mp3", "file_size": 999})


# ── Tag operations ────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_files_by_tag_delegates() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.search_files_by_tag = AsyncMock(return_value=sentinel.files)

    result = await db.search_files_by_tag("genre", "Rock", limit=10)

    assert result is sentinel.files
    tag_repo.search_files_by_tag.assert_awaited_once_with("genre", "Rock", limit=10)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_files_by_tag_contains_delegates() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.search_files_by_tag_contains = AsyncMock(return_value=sentinel.files)

    result = await db.search_files_by_tag_contains("nom:mood-strict", "happy", limit=5)

    assert result is sentinel.files
    tag_repo.search_files_by_tag_contains.assert_awaited_once_with("nom:mood-strict", "happy", limit=5)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_file_ids_for_tag_id_delegates() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.list_file_ids_for_tag = AsyncMock(return_value=sentinel.ids)

    result = await db.list_file_ids_for_tag_id(5, limit=100, offset=0)

    assert result is sentinel.ids
    tag_repo.list_file_ids_for_tag.assert_awaited_once_with(5, limit=100, offset=0)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_tag_delegates() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.get_tag = AsyncMock(return_value=sentinel.tag)

    result = await db.get_tag(5)

    assert result is sentinel.tag
    tag_repo.get_tag.assert_awaited_once_with(5)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_tags_for_file_delegates() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.get_tags_for_file = AsyncMock(return_value=sentinel.tags)

    result = await db.list_tags_for_file(10)

    assert result is sentinel.tags
    tag_repo.get_tags_for_file.assert_awaited_once_with(10)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_all_tag_names_delegates() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.list_all_tag_names = AsyncMock(return_value=sentinel.names)

    result = await db.list_all_tag_names(limit=50)

    assert result is sentinel.names
    tag_repo.list_all_tag_names.assert_awaited_once_with(limit=50)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_tags_delegates() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.list_tags = AsyncMock(return_value=sentinel.tags)

    result = await db.list_tags()

    assert result is sentinel.tags
    tag_repo.list_tags.assert_awaited_once_with(name=None, value=None, limit=None, offset=0)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_tags_by_name_delegates_with_name_and_limit() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.list_tags = AsyncMock(return_value=sentinel.tags)

    result = await db.list_tags_by_name("genre", limit=10)

    assert result is sentinel.tags
    tag_repo.list_tags.assert_awaited_once_with(name="genre", limit=10)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_count_tags_delegates() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.count_tags = AsyncMock(return_value=42)

    result = await db.count_tags()

    assert result == 42
    tag_repo.count_tags.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_count_tags_filtered_delegates() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.count_tags_filtered = AsyncMock(return_value=10)

    result = await db.count_tags_filtered(name="genre")

    assert result == 10
    tag_repo.count_tags_filtered.assert_awaited_once_with(name="genre", search=None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_tags_with_song_count_delegates() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.list_tags_with_song_count = AsyncMock(return_value=sentinel.tags)

    result = await db.list_tags_with_song_count()

    assert result is sentinel.tags
    tag_repo.list_tags_with_song_count.assert_awaited_once_with(name=None, search=None, limit=100, offset=0)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_genre_tags_for_files_delegates() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.get_genre_tags_for_files = AsyncMock(return_value=sentinel.tags)

    result = await db.list_genre_tags_for_files([1, 2, 3])

    assert result is sentinel.tags
    tag_repo.get_genre_tags_for_files.assert_awaited_once_with([1, 2, 3])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_file_tags_for_files_groups_by_file_id() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.get_tags_for_files_batch = AsyncMock(
        return_value=[
            {"file_id": 1, "tag_id": 100, "tag_name": "genre", "tag_value": "Rock", "source": "ml", "confidence": 0.9},
            {"file_id": 1, "tag_id": 101, "tag_name": "mood", "tag_value": "Happy", "source": "ml", "confidence": 0.8},
            {"file_id": 2, "tag_id": 100, "tag_name": "genre", "tag_value": "Rock", "source": "ml", "confidence": 0.9},
        ]
    )

    result = await db.list_file_tags_for_files([1, 2])

    assert set(result.keys()) == {1, 2}
    assert len(result[1]) == 2
    assert len(result[2]) == 1
    # Verify TagRow construction from batch rows
    assert result[1][0]["id"] == 100
    assert result[1][0]["name"] == "genre"
    assert result[1][0]["value"] == "Rock"
    tag_repo.get_tags_for_files_batch.assert_awaited_once_with([1, 2], name_starts_with=None, include_edge=False)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_file_tags_for_files_empty_result() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.get_tags_for_files_batch = AsyncMock(return_value=[])

    result = await db.list_file_tags_for_files([1, 2])

    # Empty batch → all file_ids present with empty lists
    assert result == {1: [], 2: []}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_file_tags_for_files_with_name_starts_with() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.get_tags_for_files_batch = AsyncMock(return_value=[])

    await db.list_file_tags_for_files([1], name_starts_with="genre")

    tag_repo.get_tags_for_files_batch.assert_awaited_once_with([1], name_starts_with="genre", include_edge=False)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_count_files_by_tag_delegates() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.count_files_by_tag = AsyncMock(return_value=15)

    result = await db.count_files_by_tag("genre", "Rock")

    assert result == 15
    tag_repo.count_files_by_tag.assert_awaited_once_with("genre", "Rock")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_search_files_by_tag_pattern_delegates() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.search_files_by_tag_pattern = AsyncMock(return_value=sentinel.files)

    result = await db.search_files_by_tag_pattern("genre", "R*", limit=10)

    assert result is sentinel.files
    tag_repo.search_files_by_tag_pattern.assert_awaited_once_with("genre", "R*", limit=10)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_find_or_create_tag_delegates() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.get_or_create_tag = AsyncMock(return_value=42)

    result = await db.find_or_create_tag("genre", "Rock")

    assert result == 42
    tag_repo.get_or_create_tag.assert_awaited_once_with("genre", "Rock", "")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_song_tag_edges_for_tags_delegates() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.get_file_tag_edges_for_tags = AsyncMock(return_value=sentinel.edges)

    result = await db.get_song_tag_edges_for_tags([1, 2], limit=50)

    assert result is sentinel.edges
    tag_repo.get_file_tag_edges_for_tags.assert_awaited_once_with([1, 2], limit=50)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_count_songs_for_tag_delegates() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.count_songs_for_tag = AsyncMock(return_value=25)

    result = await db.count_songs_for_tag(5)

    assert result == 25
    tag_repo.count_songs_for_tag.assert_awaited_once_with(5)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_replace_file_tags_delegates() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.replace_file_tags = AsyncMock()

    await db.replace_file_tags(10, [{"tag_id": 1, "confidence": 0.9}])

    tag_repo.replace_file_tags.assert_awaited_once_with(10, [{"tag_id": 1, "confidence": 0.9}])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_replace_tag_references_delegates() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.replace_tag_references = AsyncMock()

    await db.replace_tag_references(5, 10)

    tag_repo.replace_tag_references.assert_awaited_once_with(5, 10)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_replace_selected_tag_references_passes_file_ids() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.replace_tag_references = AsyncMock()

    await db.replace_selected_tag_references([1, 2, 3], 5, 10)

    tag_repo.replace_tag_references.assert_awaited_once_with(5, 10, file_ids=[1, 2, 3])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_remove_file_tags_all_tags() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.cleanup_orphaned_tags = AsyncMock()

    await db.remove_file_tags(10)

    tag_repo.cleanup_orphaned_tags.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_remove_file_tags_specific_tags() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.remove_tag_from_file = AsyncMock()
    tag_repo.cleanup_orphaned_tags = AsyncMock()

    await db.remove_file_tags(10, tag_keys=[1, 2, 3])

    assert tag_repo.remove_tag_from_file.await_count == 3
    tag_repo.remove_tag_from_file.assert_any_await(10, 1)
    tag_repo.remove_tag_from_file.assert_any_await(10, 2)
    tag_repo.remove_tag_from_file.assert_any_await(10, 3)
    tag_repo.cleanup_orphaned_tags.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_tag_value_frequencies_calls_batch() -> None:
    db, _, _, _, _, tag_repo, _ = _make_library_db()
    tag_repo.get_tag_value_frequencies_batch = AsyncMock(
        return_value={
            "genre": [("Rock", 10), ("Pop", 5)],
            "mood": [("Happy", 3), ("Sad", 1)],
        }
    )

    result = await db.list_tag_value_frequencies(["genre", "mood"], limit=100)

    assert result == {"genre": [("Rock", 10), ("Pop", 5)], "mood": [("Happy", 3), ("Sad", 1)]}
    tag_repo.get_tag_value_frequencies_batch.assert_awaited_once_with(["genre", "mood"], limit=100)


# ── Folder operations ─────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_folder_delegates() -> None:
    db, _, _, folder_repo, *_ = _make_library_db()
    folder_repo.get_folder = AsyncMock(return_value=sentinel.folder)

    result = await db.get_folder(5)

    assert result is sentinel.folder
    folder_repo.get_folder.assert_awaited_once_with(5)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_folders_for_library_delegates() -> None:
    db, _, _, folder_repo, *_ = _make_library_db()
    folder_repo.list_folders_for_library = AsyncMock(return_value=sentinel.folders)

    result = await db.list_folders_for_library(1)

    assert result is sentinel.folders
    folder_repo.list_folders_for_library.assert_awaited_once_with(1)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_library_folder_delegates() -> None:
    db, _, _, folder_repo, *_ = _make_library_db()
    folder_repo.add_library_folder = AsyncMock(return_value=42)

    result = await db.add_library_folder(1, {"path": "/Rock"})

    assert result == 42
    folder_repo.add_library_folder.assert_awaited_once_with(1, {"path": "/Rock"})


@pytest.mark.unit
@pytest.mark.asyncio
async def test_remove_library_folder_delegates() -> None:
    db, _, _, folder_repo, *_ = _make_library_db()
    folder_repo.remove_library_folder = AsyncMock()

    await db.remove_library_folder(1, 5)

    folder_repo.remove_library_folder.assert_awaited_once_with(1, 5)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_replace_library_folders_delegates() -> None:
    db, _, _, folder_repo, *_ = _make_library_db()
    folder_repo.replace_library_folders = AsyncMock()

    await db.replace_library_folders(1, [{"path": "/Rock"}, {"path": "/Pop"}])

    folder_repo.replace_library_folders.assert_awaited_once_with(1, [{"path": "/Rock"}, {"path": "/Pop"}])


# ── Scan operations ───────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_scan_delegates() -> None:
    db, _, _, _, scan_repo, *_ = _make_library_db()
    scan_repo.get_scan_record = AsyncMock(return_value=sentinel.scan)

    result = await db.get_scan(1)

    assert result is sentinel.scan
    scan_repo.get_scan_record.assert_awaited_once_with(1)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_scan_merges_library_id() -> None:
    db, _, _, _, scan_repo, *_ = _make_library_db()
    scan_repo.create_scan = AsyncMock(return_value=42)

    result = await db.add_scan(1, {"status": "running"})

    assert result == 42
    scan_repo.create_scan.assert_awaited_once_with({"status": "running", "library_id": 1})


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_scan_when_exists() -> None:
    db, _, _, _, scan_repo, *_ = _make_library_db()
    scan_repo.get_scan_record = AsyncMock(return_value={"id": 42})
    scan_repo.update_scan = AsyncMock()

    await db.update_scan(1, {"status": "done"})

    scan_repo.get_scan_record.assert_awaited_once_with(1)
    scan_repo.update_scan.assert_awaited_once_with(42, {"status": "done"})
    scan_repo.create_scan.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_scan_creates_when_not_exists() -> None:
    db, _, _, _, scan_repo, *_ = _make_library_db()
    scan_repo.get_scan_record = AsyncMock(return_value=None)
    scan_repo.create_scan = AsyncMock(return_value=99)

    await db.update_scan(1, {"status": "done"})

    scan_repo.get_scan_record.assert_awaited_once_with(1)
    scan_repo.create_scan.assert_awaited_once_with({"status": "done", "library_id": 1})
    scan_repo.update_scan.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_remove_scan_when_exists() -> None:
    db, _, _, _, scan_repo, *_ = _make_library_db()
    scan_repo.get_scan_record = AsyncMock(return_value={"id": 42})
    scan_repo.delete_scan_record = AsyncMock()

    await db.remove_scan(1)

    scan_repo.get_scan_record.assert_awaited_once_with(1)
    scan_repo.delete_scan_record.assert_awaited_once_with(42)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_remove_scan_noop_when_not_exists() -> None:
    db, _, _, _, scan_repo, *_ = _make_library_db()
    scan_repo.get_scan_record = AsyncMock(return_value=None)
    scan_repo.delete_scan_record = AsyncMock()

    await db.remove_scan(1)

    scan_repo.get_scan_record.assert_awaited_once_with(1)
    scan_repo.delete_scan_record.assert_not_called()


# ── File state ────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_count_file_states_delegates() -> None:
    db, _, _, _, _, _, file_state_repo = _make_library_db()
    file_state_repo.count_for_file_and_state = AsyncMock(return_value=3)

    result = await db.count_file_states(10, 5)

    assert result == 3
    file_state_repo.count_for_file_and_state.assert_awaited_once_with(10, 5)


# ── Clear methods ─────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clear_song_tags_delegates_to_maintenance() -> None:
    db, *_ = _make_library_db()
    db.maintenance.truncate_song_tag_edges = AsyncMock()

    await db.clear_song_tags()

    db.maintenance.truncate_song_tag_edges.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clear_file_links_delegates_to_maintenance() -> None:
    db, *_ = _make_library_db()
    db.maintenance.truncate_file_links = AsyncMock()

    await db.clear_file_links()

    db.maintenance.truncate_file_links.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clear_folder_links_delegates_to_maintenance() -> None:
    db, *_ = _make_library_db()
    db.maintenance.truncate_folder_links = AsyncMock()

    await db.clear_folder_links()

    db.maintenance.truncate_folder_links.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clear_tags_delegates_to_maintenance() -> None:
    db, *_ = _make_library_db()
    db.maintenance.truncate_tags = AsyncMock()

    await db.clear_tags()

    db.maintenance.truncate_tags.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clear_files_delegates_to_maintenance() -> None:
    db, *_ = _make_library_db()
    db.maintenance.truncate_files = AsyncMock()

    await db.clear_files()

    db.maintenance.truncate_files.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_clear_folders_delegates_to_maintenance() -> None:
    db, *_ = _make_library_db()
    db.maintenance.truncate_folders = AsyncMock()

    await db.clear_folders()

    db.maintenance.truncate_folders.assert_awaited_once_with()


# ── LibraryMaintenanceDb ──────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_maintenance_list_orphaned_file_ids() -> None:
    db, file_repo, _, _ = _make_library_maintenance_db()
    file_repo.list_orphaned_file_ids = AsyncMock(return_value=sentinel.ids)

    result = await db.list_orphaned_file_ids()

    assert result is sentinel.ids
    file_repo.list_orphaned_file_ids.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_maintenance_list_orphaned_tag_ids() -> None:
    db, _, tag_repo, _ = _make_library_maintenance_db()
    tag_repo.get_orphaned_tag_ids = AsyncMock(return_value=sentinel.ids)

    result = await db.list_orphaned_tag_ids()

    assert result is sentinel.ids
    tag_repo.get_orphaned_tag_ids.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_maintenance_delete_tags_by_ids() -> None:
    db, _, tag_repo, _ = _make_library_maintenance_db()
    tag_repo.delete_tags_by_ids = AsyncMock()

    await db.delete_tags_by_ids([1, 2, 3])

    tag_repo.delete_tags_by_ids.assert_awaited_once_with([1, 2, 3])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_maintenance_truncate_files() -> None:
    db, file_repo, _, _ = _make_library_maintenance_db()
    file_repo.truncate_files = AsyncMock()

    await db.truncate_files()

    file_repo.truncate_files.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_maintenance_truncate_file_links() -> None:
    db, file_repo, _, _ = _make_library_maintenance_db()
    file_repo.truncate_file_links = AsyncMock()

    await db.truncate_file_links()

    file_repo.truncate_file_links.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_maintenance_truncate_folder_links() -> None:
    db, _, _, folder_repo = _make_library_maintenance_db()
    folder_repo.truncate_folder_links = AsyncMock()

    await db.truncate_folder_links()

    folder_repo.truncate_folder_links.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_maintenance_truncate_folders() -> None:
    db, _, _, folder_repo = _make_library_maintenance_db()
    folder_repo.truncate_folders = AsyncMock()

    await db.truncate_folders()

    folder_repo.truncate_folders.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_maintenance_truncate_tags() -> None:
    db, _, tag_repo, _ = _make_library_maintenance_db()
    tag_repo.truncate_tags = AsyncMock()

    await db.truncate_tags()

    tag_repo.truncate_tags.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_maintenance_truncate_song_tag_edges() -> None:
    db, _, tag_repo, _ = _make_library_maintenance_db()
    tag_repo.truncate_file_tag_assignments = AsyncMock()

    await db.truncate_song_tag_edges()

    tag_repo.truncate_file_tag_assignments.assert_awaited_once_with()
