"""Tests for ``nomarr.components.library.library_file_query_comp``."""

from __future__ import annotations

from unittest.mock import AsyncMock, call, patch

import pytest

from nomarr.components.library.library_file_query_comp import (
    DEFAULT_LIMIT,
    _collect_file_ids_for_tag_ids,
    clear_library_data,
    count_files_by_tag,
    count_recently_tagged,
    detect_nd_path_prefix,
    find_move_candidate_by_chromaprint,
    get_all_library_paths,
    get_artist_album_frequencies,
    get_existing_file_paths,
    get_file_by_id,
    get_file_modified_times,
    get_files_by_chromaprint,
    get_files_by_ids_with_tags,
    get_files_by_paths_bulk,
    get_files_for_folder,
    get_files_for_folders,
    get_folder_rel_paths,
    get_library_counts,
    get_library_file,
    get_library_stats,
    get_recently_processed,
    get_sample_normalized_path,
    get_tagged_file_paths,
    get_tracks_by_file_ids,
    get_tracks_for_matching,
    list_all_file_ids,
    list_library_files,
    require_library_file_id,
    search_files_by_tag,
    search_library_files_with_tags,
)
from nomarr.helpers.constants.file_states import STATE_PROCESSED


def make_db() -> AsyncMock:

    db = AsyncMock()

    db.library = AsyncMock()
    db.library.maintenance = AsyncMock()
    db.library.file_tag_repo = AsyncMock()

    db.app = AsyncMock()

    db.ml = AsyncMock()

    return db


@pytest.mark.unit
async def test_get_file_by_id_uses_library_facade() -> None:

    db = make_db()

    db.library.get_file.return_value = {"id": 1}

    result = await get_file_by_id(db, 1)

    assert result == {"id": 1}

    db.library.get_file.assert_called_once_with(1)


@pytest.mark.unit
async def test_count_recently_tagged_uses_library_counter() -> None:

    db = make_db()

    db.library.count_recently_tagged.return_value = 2

    with patch("nomarr.components.library.library_file_query_comp.now_ms") as mock_now_ms:
        mock_now_ms.return_value.value = 10_000

        result = await count_recently_tagged(db, window_seconds=5)

    assert result == 2

    db.library.count_recently_tagged.assert_called_once_with(5_000)


@pytest.mark.unit
async def test_get_existing_file_paths_uses_library_batch_lookup() -> None:

    db = make_db()

    paths = ["D:/Music/song.flac", "D:/Music/other.flac"]

    db.library.list_existing_file_paths.return_value = ["D:/Music/song.flac", "D:/Music/song.flac"]

    result = await get_existing_file_paths(db, paths)

    assert result == {"D:/Music/song.flac"}

    db.library.list_existing_file_paths.assert_called_once_with(paths)


@pytest.mark.unit
async def test_get_files_by_ids_with_tags_hydrates_tags_and_library_ids() -> None:

    db = make_db()

    db.library.list_files_by_ids.return_value = [{"id": 1, "path": "D:/Music/song.flac", "library_key": "1"}]

    db.library.list_file_tags_for_files.return_value = {1: [{"name": "genre", "value": "rock"}]}
    db.library.get_library_ids_for_files.return_value = {1: 1}

    result = await get_files_by_ids_with_tags(db, [1])

    assert result == [
        {
            "id": 1,
            "path": "D:/Music/song.flac",
            "library_key": "1",
            "tags": [{"key": "genre", "value": "rock", "type": "string", "is_nomarr": False}],
            "library_id": 1,
        }
    ]

    db.library.list_files_by_ids.assert_called_once_with([1])

    db.library.list_file_tags_for_files.assert_called_once_with([1])


@pytest.mark.unit
async def test_get_files_by_ids_with_tags_returns_empty_list_when_ids_empty() -> None:

    db = make_db()

    result = await get_files_by_ids_with_tags(db, [])

    assert result == []

    db.library.list_files_by_ids.assert_not_called()


@pytest.mark.unit
async def test_get_library_file_scoped_filters_library_files() -> None:

    db = make_db()

    row = {
        "id": 1,
        "path": "D:/Music/song.flac",
        "normalized_path": "song.flac",
    }

    db.library.list_library_files.return_value = [row]

    result = await get_library_file(db, "song.flac", library_id=1)

    assert result == row

    db.library.list_library_files.assert_called_once_with(1, limit=None)


@pytest.mark.unit
async def test_get_library_file_unscoped_tries_normalized_then_unscoped_path() -> None:

    db = make_db()

    row = {"id": 1, "path": "D:/Music/song.flac"}

    db.library.list_files.return_value = []

    db.library.find_file_by_path_any_library.return_value = row

    result = await get_library_file(db, "D:/Music/song.flac")

    assert result == row

    db.library.list_files.assert_called_once_with(filters={"normalized_path": "D:/Music/song.flac"}, limit=1)

    db.library.find_file_by_path_any_library.assert_called_once_with("D:/Music/song.flac")


@pytest.mark.unit
async def test_get_files_by_paths_bulk_maps_only_found_paths() -> None:

    db = make_db()

    with patch(
        "nomarr.components.library.library_file_query_comp.get_library_file",
        side_effect=[None, {"id": 2, "path": "D:/Music/found.flac"}],
    ) as get_library_file_mock:
        result = await get_files_by_paths_bulk(db, ["missing.flac", "D:/Music/found.flac"])

    assert result == {"D:/Music/found.flac": {"id": 2, "path": "D:/Music/found.flac"}}

    get_library_file_mock.assert_has_calls([call(db, "missing.flac"), call(db, "D:/Music/found.flac")])


@pytest.mark.unit
async def test_get_files_by_paths_bulk_returns_empty_mapping_when_paths_empty() -> None:

    db = make_db()

    result = await get_files_by_paths_bulk(db, [])

    assert result == {}

    db.library.find_file_by_path_any_library.assert_not_called()


@pytest.mark.unit
async def test_detect_nd_path_prefix_uses_longest_matching_normalized_path() -> None:

    db = make_db()

    db.library.list_files.return_value = [
        {"normalized_path": "song.flac"},
        {"normalized_path": "artist/song.flac"},
    ]

    result = await detect_nd_path_prefix(db, "/music/artist/song.flac")

    assert result == "/music/"

    db.library.list_files.assert_called_once_with(limit=DEFAULT_LIMIT)


@pytest.mark.unit
async def test_detect_nd_path_prefix_returns_none_without_match() -> None:

    db = make_db()

    db.library.list_files.return_value = []

    assert await detect_nd_path_prefix(db, "/music/missing.flac") is None


@pytest.mark.unit
async def test_list_library_files_unscoped_sorts_and_paginates() -> None:

    db = make_db()

    db.library.list_files.return_value = [
        {"id": 2, "artist": "B", "album": "A", "title": "T2"},
        {"id": 1, "artist": "A", "album": "A", "title": "T1"},
    ]

    with patch(
        "nomarr.components.library.library_file_query_comp.hydrate_songs_with_metadata",
        side_effect=lambda _db, docs: docs,
    ):
        rows, total = await list_library_files(db, limit=1, offset=1)

    assert rows == [{"id": 2, "artist": "B", "album": "A", "title": "T2"}]

    assert total == 2

    db.library.list_files.assert_called_once_with(limit=DEFAULT_LIMIT)


@pytest.mark.unit
async def test_list_library_files_scoped_filters_in_python() -> None:

    db = make_db()

    matching_row = {
        "id": 9,
        "artist": "Artist",
        "album": "Album",
        "title": "Song",
    }

    db.library.list_library_files.return_value = [
        {"id": 8, "artist": "Other", "album": "Album", "title": "Song"},
        matching_row,
    ]

    with patch(
        "nomarr.components.library.library_file_query_comp.hydrate_songs_with_metadata",
        side_effect=lambda _db, docs: docs,
    ):
        rows, total = await list_library_files(db, artist="Artist", album="Album", library_id=1)

    assert rows == [matching_row]

    assert total == 1

    db.library.list_library_files.assert_called_once_with(1, limit=None)


@pytest.mark.unit
async def test_get_all_library_paths_uses_list_files() -> None:

    db = make_db()

    db.library.list_files.return_value = [{"path": "D:/Music/a.flac"}, {"path": "D:/Music/b.flac"}]

    result = await get_all_library_paths(db)

    assert result == ["D:/Music/a.flac", "D:/Music/b.flac"]

    db.library.list_files.assert_called_once_with(limit=DEFAULT_LIMIT)


@pytest.mark.unit
async def test_get_file_modified_times_builds_mapping_from_list_files() -> None:

    db = make_db()

    db.library.list_files.return_value = [
        {"path": "D:/Music/a.flac", "modified_time": 10},
        {"path": "D:/Music/b.flac", "modified_time": 20},
        {"path": "D:/Music/skip.flac", "modified_time": None},
    ]

    result = await get_file_modified_times(db)

    assert result == {"D:/Music/a.flac": 10, "D:/Music/b.flac": 20}

    db.library.list_files.assert_called_once_with(limit=DEFAULT_LIMIT)


@pytest.mark.unit
async def test_get_tagged_file_paths_reads_tagged_file_docs_from_app_facade() -> None:

    db = make_db()

    db.app.list_file_docs_in_state.return_value = [
        {"id": 1, "path": "D:/Music/a.flac"},
        {"id": 2, "path": "D:/Music/b.flac"},
    ]

    result = await get_tagged_file_paths(db)

    assert result == ["D:/Music/a.flac", "D:/Music/b.flac"]

    db.app.list_file_docs_in_state.assert_called_once_with(STATE_PROCESSED, limit=DEFAULT_LIMIT)


@pytest.mark.unit
async def test_get_folder_rel_paths_uses_library_folder_listing() -> None:

    db = make_db()

    db.library.list_folders_for_library.return_value = [{"path": "Artist"}, {"path": "Artist/Album"}]

    result = await get_folder_rel_paths(db, 1)

    assert result == {"Artist", "Artist/Album"}

    db.library.list_folders_for_library.assert_called_once_with(1)


@pytest.mark.unit
async def test_get_files_for_folder_marks_tagged_state_from_app_facade() -> None:

    db = make_db()

    matching_doc = {
        "id": 1,
        "path": "D:/Music/Artist/Album/song.flac",
        "normalized_path": "Artist/Album/song.flac",
        "has_tagged_state": True,
    }

    db.library.list_library_files_for_folder.return_value = [matching_doc]

    result = await get_files_for_folder(db, 1, "Artist/Album")

    assert result == {matching_doc["path"]: matching_doc}

    db.library.list_library_files_for_folder.assert_called_once_with(1, "Artist/Album")


@pytest.mark.unit
async def test_get_files_for_folders_matches_root_and_nested_paths() -> None:

    db = make_db()

    root_doc = {
        "id": 1,
        "path": "D:/Music/root.flac",
        "normalized_path": "root.flac",
    }

    nested_doc = {
        "id": 2,
        "path": "D:/Music/Artist/song.flac",
        "normalized_path": "Artist/song.flac",
    }

    db.library.list_library_files.return_value = [root_doc, nested_doc]

    db.app.list_files_in_state.return_value = [2]

    result = await get_files_for_folders(db, 1, ["", "Artist"])

    assert result == {
        root_doc["path"]: {**root_doc, "has_tagged_state": False},
        nested_doc["path"]: {**nested_doc, "has_tagged_state": True},
    }


@pytest.mark.unit
async def test_get_recently_processed_sorts_by_latest_activity() -> None:

    db = make_db()

    db.app.list_file_docs_in_state.return_value = [
        {
            "id": 1,
            "normalized_path": "Artist/older.flac",
            "title": "Older",
            "artist": "Artist",
            "album": "Album",
            "scanned_at": 10,
        },
        {
            "id": 2,
            "normalized_path": "Artist/newer.flac",
            "title": "Newer",
            "artist": "Artist",
            "album": "Album",
            "last_tagged_at": 20,
        },
    ]

    with patch(
        "nomarr.components.library.library_file_query_comp.hydrate_songs_with_metadata",
        side_effect=lambda _db, docs: docs,
    ):
        result = await get_recently_processed(db, limit=1)

    assert result == [
        {
            "file_id": 2,
            "path": "Artist/newer.flac",
            "title": "Newer",
            "artist": "Artist",
            "album": "Album",
            "activity_at": 20,
            "activity_event": "tagged",
        }
    ]

    db.app.list_file_docs_in_state.assert_called_once_with(STATE_PROCESSED, limit=DEFAULT_LIMIT)


@pytest.mark.unit
async def test_get_recently_processed_scopes_to_library_ids() -> None:

    db = make_db()

    db.app.list_file_docs_in_state.return_value = [
        {"id": 1, "normalized_path": "keep.flac", "scanned_at": 5},
        {"id": 2, "normalized_path": "skip.flac", "scanned_at": 6},
    ]

    db.library.list_library_file_ids.return_value = [1]

    with patch(
        "nomarr.components.library.library_file_query_comp.hydrate_songs_with_metadata",
        side_effect=lambda _db, docs: docs,
    ):
        result = await get_recently_processed(db, library_id=1)

    assert [row["file_id"] for row in result] == [1]

    db.library.list_library_file_ids.assert_called_once_with(1, limit=DEFAULT_LIMIT)


@pytest.mark.unit
async def test_get_files_by_chromaprint_scoped_filters_library_files() -> None:

    db = make_db()

    matching_doc = {"id": 1, "chromaprint": "abc"}

    db.library.list_library_files.return_value = [
        matching_doc,
        {"id": 2, "chromaprint": "def"},
    ]

    result = await get_files_by_chromaprint(db, "abc", library_id=1)

    assert result == [matching_doc]

    db.library.list_library_files.assert_called_once_with(1, limit=None)


@pytest.mark.unit
async def test_get_files_by_chromaprint_unscoped_uses_filtered_list_files() -> None:

    db = make_db()

    db.library.list_files.return_value = [{"id": 1, "chromaprint": "abc"}]

    result = await get_files_by_chromaprint(db, "abc")

    assert result == [{"id": 1, "chromaprint": "abc"}]

    db.library.list_files.assert_called_once_with(filters={"chromaprint": "abc"}, limit=None)


@pytest.mark.unit
async def test_get_tracks_by_file_ids_sorts_and_applies_defaults() -> None:

    db = make_db()

    db.library.list_files_by_ids.return_value = [
        {"path": "D:/Music/one.flac", "title": None, "artist": None, "album": None, "sort_rank": 1},
        {"path": "D:/Music/two.flac", "title": "Two", "artist": "Artist", "album": "Album", "sort_rank": 2},
    ]

    with patch(
        "nomarr.components.library.library_file_query_comp.hydrate_songs_with_metadata",
        side_effect=lambda _db, docs: docs,
    ):
        result = await get_tracks_by_file_ids(
            db,
            {1, 2},
            [("sort_rank", "desc")],
            limit=1,
        )

    assert result == [{"path": "D:/Music/two.flac", "title": "Two", "artist": "Artist", "album": "Album"}]

    db.library.list_files_by_ids.assert_called_once()


@pytest.mark.unit
async def test_get_library_stats_aggregates_global_file_docs() -> None:

    db = make_db()

    db.library.list_files.return_value = [
        {"duration_seconds": 10.5, "file_size": 100},
        {"duration_seconds": 9.5, "file_size": 200},
    ]

    db.library.count_files.return_value = 2

    db.library.count_tags.return_value = 10

    db.library.list_tags_by_name.side_effect = [
        [{"value": "Artist A"}, {"value": "Artist B"}],
        [{"value": "Album A"}],
    ]

    with patch("nomarr.components.library.library_file_query_comp.count_untagged_files", return_value=4):
        result = await get_library_stats(db)

    assert result == {
        "total_files": 2,
        "total_artists": 2,
        "total_albums": 1,
        "total_duration": 20.0,
        "total_size": 300,
        "needs_tagging_count": 4,
    }

    db.library.list_files.assert_called_once_with(limit=None)

    db.library.count_files.assert_called_once_with()

    assert db.library.count_tags.call_count == 2

    assert db.library.list_tags_by_name.call_args_list == [
        call("artist", limit=10),
        call("album", limit=10),
    ]


@pytest.mark.unit
async def test_get_library_counts_groups_parent_folders_by_library() -> None:

    db = make_db()

    db.library.list_library_keys.return_value = [1]

    db.library.list_library_files.return_value = [
        {"path": "D:/Music/Artist A/song.flac"},
        {"path": "D:/Music/Artist B/other.flac"},
    ]

    result = await get_library_counts(db)

    assert result == {1: {"file_count": 2, "folder_count": 2}}

    db.library.list_library_files.assert_called_once_with(1, limit=None)


@pytest.mark.unit
async def test_get_artist_album_frequencies_delegates_to_library_facade() -> None:

    db = make_db()

    db.library.list_tag_value_frequencies.return_value = {
        "artist": [("Artist A", 3)],
        "album": [("Album A", 2)],
    }

    result = await get_artist_album_frequencies(db, limit=5)

    assert result == {"artist_rows": [("Artist A", 3)], "album_rows": [("Album A", 2)]}

    db.library.list_tag_value_frequencies.assert_called_once_with(["artist", "album"], 5)


@pytest.mark.unit
async def test_get_tracks_for_matching_filters_valid_files_and_projects_isrc() -> None:

    db = make_db()

    db.library.list_files.return_value = [
        {
            "id": 1,
            "path": "D:/Music/song.flac",
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
        }
    ]

    db.library.list_file_tags_for_files.return_value = {1: [{"name": "isrc", "value": "ABC123"}]}

    with patch(
        "nomarr.components.library.library_file_query_comp.hydrate_songs_with_metadata",
        side_effect=lambda _db, docs: docs,
    ):
        result = await get_tracks_for_matching(db)

    assert result == [
        {
            "id": 1,
            "path": "D:/Music/song.flac",
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
            "isrc": "ABC123",
        }
    ]

    db.library.list_files.assert_called_once_with(filters={"is_valid": True}, limit=DEFAULT_LIMIT)

    db.library.list_file_tags_for_files.assert_called_once_with([1])


@pytest.mark.unit
async def test_get_tracks_for_matching_scopes_to_library_and_projects_isrc() -> None:

    db = make_db()

    db.library.list_tracks_for_matching.return_value = [
        {
            "id": 1,
            "is_valid": True,
            "path": "D:/Music/song.flac",
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
        }
    ]

    db.library.list_file_tags_for_files.return_value = {1: [{"name": "isrc", "value": "XYZ789"}]}

    with patch(
        "nomarr.components.library.library_file_query_comp.hydrate_songs_with_metadata",
        side_effect=lambda _db, docs: docs,
    ):
        result = await get_tracks_for_matching(db, library_id=1)

    assert result == [
        {
            "id": 1,
            "path": "D:/Music/song.flac",
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
            "isrc": "XYZ789",
        }
    ]

    db.library.list_tracks_for_matching.assert_called_once_with(1, limit=DEFAULT_LIMIT)

    db.library.list_files.assert_not_called()

    db.library.list_file_tags_for_files.assert_called_once_with([1])


@pytest.mark.unit
async def test_clear_library_data_truncates_all_facades() -> None:

    db = make_db()

    db.ml.list_vector_collection_names.return_value = ["vectors_track__hot__effnet"]

    db.library.list_files.return_value = [
        {"id": 1},
        {"id": 2},
        {"id": None},
    ]

    with patch(
        "nomarr.components.ml.inference.ml_output_stream_store_comp.delete_output_streams"
    ) as mock_delete_output_streams:
        await clear_library_data(db)

    db.ml.clear_vector_collection.assert_called_once_with("vectors_track__hot__effnet")

    db.library.list_files.assert_called_once_with(limit=None)

    assert mock_delete_output_streams.call_args_list == [
        call(db, 1),
        call(db, 2),
    ]

    db.library.maintenance.truncate_song_tag_edges.assert_called_once_with()

    db.app.clear_file_state_links.assert_called_once_with()

    db.library.maintenance.truncate_file_links.assert_called_once_with()

    db.library.maintenance.truncate_folder_links.assert_called_once_with()

    db.app.clear_pipeline_state_links.assert_called_once_with()

    db.library.maintenance.truncate_tags.assert_called_once_with()

    db.library.maintenance.truncate_files.assert_called_once_with()

    db.library.maintenance.truncate_folders.assert_called_once_with()

    db.library.maintenance.truncate_scan_records.assert_called_once_with()


@pytest.mark.unit
async def test_collect_file_ids_for_tag_ids_returns_edge_sources() -> None:

    db = make_db()

    db.library.file_tag_repo.get_file_tag_edges_for_tags.return_value = [
        {"file_id": 1, "tag_id": 1},
        {"file_id": 2, "tag_id": 2},
        {"tag_id": 3},
    ]

    result = await _collect_file_ids_for_tag_ids(db, {1, 2})

    assert result == {1, 2}

    db.library.file_tag_repo.get_file_tag_edges_for_tags.assert_called_once()


@pytest.mark.unit
async def test_search_library_files_with_tags_filters_and_hydrates_page() -> None:
    db = make_db()
    file_docs = [
        {
            "id": 1,
            "artist": "Artist",
            "album": "Album",
            "title": "Song One",
            "path": "D:/Music/one.flac",
        },
        {
            "id": 2,
            "artist": "Artist",
            "album": "Album",
            "title": "Other",
            "path": "D:/Music/two.flac",
        },
    ]
    db.library.file_tag_repo.search_files_by_tag_pattern.side_effect = [file_docs, file_docs, [file_docs[0]]]
    db.library.count_tags.return_value = 1
    db.library.list_tags_by_name.return_value = [{"id": 1, "value": "rock"}]
    db.library.file_tag_repo.get_file_tag_edges_for_tags.return_value = [{"file_id": 1, "tag_id": 1}]
    db.app.list_files_in_state.return_value = [1]
    db.library.list_files_by_ids.return_value = [{**file_docs[0], "library_key": "1"}]
    db.library.list_file_tags_for_files.return_value = {1: [{"name": "genre", "value": "rock"}]}
    db.library.get_library_ids_for_files.return_value = {1: 1}

    with patch(
        "nomarr.components.library.library_file_query_comp.hydrate_songs_with_metadata",
        side_effect=lambda _db, docs: docs,
    ):
        rows, total = await search_library_files_with_tags(
            db,
            query_text="song",
            artist="Artist",
            album="Album",
            tag_key="genre",
            tag_value="rock",
            tagged_only=True,
            limit=10,
            offset=0,
        )

    assert total == 1
    assert rows == [
        {
            "id": 1,
            "artist": "Artist",
            "album": "Album",
            "title": "Song One",
            "path": "D:/Music/one.flac",
            "library_key": "1",
            "tags": [{"key": "genre", "value": "rock", "type": "string", "is_nomarr": False}],
            "library_id": 1,
        }
    ]
    assert db.library.file_tag_repo.search_files_by_tag_pattern.call_args_list == [
        call("artist", "%Artist%", limit=None),
        call("album", "%Album%", limit=None),
        call("title", "%song%", limit=None),
    ]
    db.library.count_tags.assert_called_once_with()
    db.library.list_tags_by_name.assert_called_once_with("genre", limit=1)
    db.library.file_tag_repo.get_file_tag_edges_for_tags.assert_called_once_with([1])
    db.app.list_files_in_state.assert_called_once_with(STATE_PROCESSED, limit=DEFAULT_LIMIT)
    db.library.list_files_by_ids.assert_called_once_with([1])
    db.library.list_file_tags_for_files.assert_called_once_with([1])


@pytest.mark.unit
async def test_count_files_by_tag_uses_library_facade_for_string_and_numeric_modes() -> None:
    db = make_db()
    db.library.count_tags.return_value = 1
    db.library.list_tags_by_name.return_value = [{"id": 1, "value": "rock"}]
    db.library.file_tag_repo.get_file_tag_edges_for_tags.return_value = [
        {"file_id": 1, "tag_id": 1},
        {"file_id": 2, "tag_id": 1},
    ]

    string_count = await count_files_by_tag(db, "genre", "rock")

    assert string_count == 2
    db.library.count_tags.assert_called_once_with()
    db.library.list_tags_by_name.assert_called_once_with("genre", limit=1)
    db.library.file_tag_repo.get_file_tag_edges_for_tags.assert_called_once_with([1])

    db = make_db()
    db.library.count_tags.return_value = 2
    db.library.list_tags_by_name.return_value = [
        {"id": 1, "value": 120.0},
        {"id": 2, "value": True},
    ]
    db.library.file_tag_repo.get_file_tag_edges_for_tags.return_value = [{"file_id": 1, "tag_id": 1}]

    numeric_count = await count_files_by_tag(db, "nom:bpm", 120.0)

    assert numeric_count == 1
    db.library.count_tags.assert_called_once_with()
    db.library.list_tags_by_name.assert_called_once_with("nom:bpm", limit=2)
    db.library.file_tag_repo.get_file_tag_edges_for_tags.assert_called_once_with([1])


@pytest.mark.unit
async def test_search_files_by_tag_numeric_sorts_by_distance_and_hydrates_tags() -> None:
    db = make_db()
    db.library.count_tags.return_value = 2
    db.library.list_tags_by_name.return_value = [
        {"id": 1, "value": 118.0},
        {"id": 2, "value": 121.0},
    ]
    db.library.file_tag_repo.get_file_tag_edges_for_tags.return_value = [
        {"file_id": 1, "tag_id": 1},
        {"file_id": 2, "tag_id": 2},
    ]
    db.library.list_files_by_ids.return_value = [
        {
            "id": 1,
            "artist": "B",
            "album": "A",
            "title": "Far",
            "library_key": "1",
        },
        {
            "id": 2,
            "artist": "A",
            "album": "A",
            "title": "Near",
            "library_key": "1",
        },
    ]
    db.library.list_file_tags_for_files.return_value = {
        1: [{"name": "nom:bpm", "value": 118.0}],
        2: [{"name": "nom:bpm", "value": 121.0}],
    }
    db.library.get_library_ids_for_files.return_value = {2: 1}

    with patch(
        "nomarr.components.library.library_file_query_comp.hydrate_songs_with_metadata",
        side_effect=lambda _db, docs: docs,
    ):
        result = await search_files_by_tag(db, "nom:bpm", 120.0, limit=1, offset=0)

    assert result[0]["id"] == 2
    assert result[0]["distance"] == 1.0
    assert result[0]["library_id"] == 1
    db.library.count_tags.assert_called_once_with()
    db.library.list_tags_by_name.assert_called_once_with("nom:bpm", limit=2)
    db.library.file_tag_repo.get_file_tag_edges_for_tags.assert_called_once_with([1, 2], limit=DEFAULT_LIMIT)
    db.library.list_files_by_ids.assert_called_once_with([1, 2])
    db.library.list_file_tags_for_files.assert_called_once_with([2])


@pytest.mark.unit
async def test_require_library_file_id_returns_id_for_existing_file() -> None:

    db = make_db()

    with patch("nomarr.components.library.library_file_query_comp.get_library_file") as mock_get_library_file:
        mock_get_library_file.return_value = {"id": 123}

        result = await require_library_file_id(db, "D:/Music/song.flac", library_id=1)

    assert result == 123

    mock_get_library_file.assert_called_once_with(db, "D:/Music/song.flac", library_id=1)


@pytest.mark.unit
async def test_require_library_file_id_raises_for_missing_file() -> None:

    db = make_db()

    with patch("nomarr.components.library.library_file_query_comp.get_library_file") as mock_get_library_file:
        mock_get_library_file.return_value = None

        with pytest.raises(FileNotFoundError, match=r"File not in library: D:/Music/missing\.flac"):
            await require_library_file_id(db, "D:/Music/missing.flac")

    mock_get_library_file.assert_called_once_with(db, "D:/Music/missing.flac", library_id=None)


@pytest.mark.unit
async def test_list_all_file_ids_filters_non_string_ids_and_uses_default_limit() -> None:

    db = make_db()

    db.library.list_files.return_value = [
        {"id": 1},
        {"id": "not_int"},
        {"path": "D:/Music/three.flac"},
        {"id": 4},
    ]

    result = await list_all_file_ids(db)

    assert result == [1, 4]

    db.library.list_files.assert_called_once_with(limit=DEFAULT_LIMIT)


@pytest.mark.unit
async def test_get_sample_normalized_path_returns_first_value() -> None:

    db = make_db()

    db.library.list_files.return_value = [{"normalized_path": "Artist/Album/song.flac"}]

    result = await get_sample_normalized_path(db)

    assert result == "Artist/Album/song.flac"

    db.library.list_files.assert_called_once_with(limit=1)


@pytest.mark.unit
async def test_find_move_candidate_by_chromaprint_normalizes_library_id() -> None:

    db = make_db()

    candidate = {"id": 9, "chromaprint": "abc123"}

    db.library.find_library_file_by_chromaprint.return_value = candidate

    result = await find_move_candidate_by_chromaprint(db, 9, "abc123")

    assert result == candidate

    db.library.find_library_file_by_chromaprint.assert_called_once_with(9, "abc123")
