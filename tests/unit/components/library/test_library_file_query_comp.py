"""Tests for ``nomarr.components.library.library_file_query_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.components.library.library_file_query_comp import (
    DEFAULT_LIMIT,
    _collect_file_ids_for_tag_ids,
    clear_library_data,
    count_files_by_tag,
    count_library_files,
    count_recently_tagged,
    detect_nd_path_prefix,
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
    get_tagged_file_paths,
    get_tracks_by_file_ids,
    get_tracks_for_matching,
    list_library_files,
    search_files_by_tag,
    search_library_files_with_tags,
)
from nomarr.helpers.constants.file_states import STATE_TAGGED


def make_db() -> MagicMock:
    db = MagicMock()
    db.library = MagicMock()
    db.app = MagicMock()
    db.ml = MagicMock()
    return db


@pytest.mark.unit
def test_get_file_by_id_uses_library_facade() -> None:
    db = make_db()
    db.library.get_file.return_value = {"_id": "library_files/1"}

    result = get_file_by_id(db, "library_files/1")

    assert result == {"_id": "library_files/1"}
    db.library.get_file.assert_called_once_with("library_files/1")


@pytest.mark.unit
def test_count_recently_tagged_uses_library_counter() -> None:
    db = make_db()
    db.library.count_recently_tagged.return_value = 2

    with patch("nomarr.components.library.library_file_query_comp.now_ms") as mock_now_ms:
        mock_now_ms.return_value.value = 10_000
        result = count_recently_tagged(db, window_seconds=5)

    assert result == 2
    db.library.count_recently_tagged.assert_called_once_with(5_000)


@pytest.mark.unit
def test_get_existing_file_paths_uses_library_batch_lookup() -> None:
    db = make_db()
    paths = ["D:/Music/song.flac", "D:/Music/other.flac"]
    db.library.list_existing_file_paths.return_value = ["D:/Music/song.flac", "D:/Music/song.flac"]

    result = get_existing_file_paths(db, paths)

    assert result == {"D:/Music/song.flac"}
    db.library.list_existing_file_paths.assert_called_once_with(paths)


@pytest.mark.unit
def test_get_files_by_ids_with_tags_hydrates_tags_and_library_ids() -> None:
    db = make_db()
    db.library.get_files_by_ids.return_value = [{"_id": "library_files/1", "path": "D:/Music/song.flac"}]
    db.library.get_tags_for_files_batch.return_value = [
        {"start_id": "library_files/1", "v": {"name": "genre", "value": "rock"}}
    ]
    db.library.get_library_ids_for_files.return_value = {"library_files/1": "libraries/1"}

    result = get_files_by_ids_with_tags(db, ["library_files/1"])

    assert result == [
        {
            "_id": "library_files/1",
            "path": "D:/Music/song.flac",
            "tags": [{"key": "genre", "value": "rock", "type": "string", "is_nomarr": False}],
            "library_id": "libraries/1",
        }
    ]
    db.library.get_files_by_ids.assert_called_once_with(["library_files/1"])
    db.library.get_tags_for_files_batch.assert_called_once_with(["library_files/1"])
    db.library.get_library_ids_for_files.assert_called_once_with(["library_files/1"])


@pytest.mark.unit
def test_get_files_by_ids_with_tags_returns_empty_list_when_ids_empty() -> None:
    db = make_db()

    result = get_files_by_ids_with_tags(db, [])

    assert result == []
    db.library.get_files_by_ids.assert_not_called()


@pytest.mark.unit
def test_get_library_file_scoped_filters_library_files() -> None:
    db = make_db()
    row = {
        "_id": "library_files/1",
        "_key": "1",
        "path": "D:/Music/song.flac",
        "normalized_path": "song.flac",
    }
    db.library.list_library_files.return_value = [row]

    result = get_library_file(db, "song.flac", library_id="libraries/1")

    assert result == row
    db.library.list_library_files.assert_called_once_with("libraries/1", limit=None)


@pytest.mark.unit
def test_get_library_file_unscoped_tries_normalized_then_unscoped_path() -> None:
    db = make_db()
    row = {"_id": "library_files/1", "path": "D:/Music/song.flac"}
    db.library.list_files.return_value = []
    db.library.get_file_by_path_unscoped.return_value = row

    result = get_library_file(db, "D:/Music/song.flac")

    assert result == row
    db.library.list_files.assert_called_once_with(filters={"normalized_path": "D:/Music/song.flac"}, limit=1)
    db.library.get_file_by_path_unscoped.assert_called_once_with("D:/Music/song.flac")


@pytest.mark.unit
def test_get_files_by_paths_bulk_maps_only_found_paths() -> None:
    db = make_db()

    with patch(
        "nomarr.components.library.library_file_query_comp.get_library_file",
        side_effect=[None, {"_id": "library_files/2", "path": "D:/Music/found.flac"}],
    ) as get_library_file_mock:
        result = get_files_by_paths_bulk(db, ["missing.flac", "D:/Music/found.flac"])

    assert result == {"D:/Music/found.flac": {"_id": "library_files/2", "path": "D:/Music/found.flac"}}
    get_library_file_mock.assert_has_calls([call(db, "missing.flac"), call(db, "D:/Music/found.flac")])


@pytest.mark.unit
def test_get_files_by_paths_bulk_returns_empty_mapping_when_paths_empty() -> None:
    db = make_db()

    result = get_files_by_paths_bulk(db, [])

    assert result == {}
    db.library.get_file_by_path_unscoped.assert_not_called()


@pytest.mark.unit
def test_detect_nd_path_prefix_uses_longest_matching_normalized_path() -> None:
    db = make_db()
    db.library.list_files.return_value = [
        {"normalized_path": "song.flac"},
        {"normalized_path": "artist/song.flac"},
    ]

    result = detect_nd_path_prefix(db, "/music/artist/song.flac")

    assert result == "/music/"
    db.library.list_files.assert_called_once_with(limit=DEFAULT_LIMIT)


@pytest.mark.unit
def test_detect_nd_path_prefix_returns_none_without_match() -> None:
    db = make_db()
    db.library.list_files.return_value = []

    assert detect_nd_path_prefix(db, "/music/missing.flac") is None


@pytest.mark.unit
def test_list_library_files_unscoped_sorts_and_paginates() -> None:
    db = make_db()
    db.library.list_files.return_value = [
        {"_id": "library_files/2", "artist": "B", "album": "A", "title": "T2"},
        {"_id": "library_files/1", "artist": "A", "album": "A", "title": "T1"},
    ]

    rows, total = list_library_files(db, limit=1, offset=1)

    assert rows == [{"_id": "library_files/2", "artist": "B", "album": "A", "title": "T2"}]
    assert total == 2
    db.library.list_files.assert_called_once_with(limit=DEFAULT_LIMIT)


@pytest.mark.unit
def test_list_library_files_scoped_filters_in_python() -> None:
    db = make_db()
    matching_row = {"_id": "library_files/9", "artist": "Artist", "album": "Album", "title": "Song"}
    db.library.list_library_files.return_value = [
        {"_id": "library_files/8", "artist": "Other", "album": "Album", "title": "Song"},
        matching_row,
    ]

    rows, total = list_library_files(db, artist="Artist", album="Album", library_id="libraries/1")

    assert rows == [matching_row]
    assert total == 1
    db.library.list_library_files.assert_called_once_with("libraries/1", limit=None)


@pytest.mark.unit
def test_get_all_library_paths_uses_list_files() -> None:
    db = make_db()
    db.library.list_files.return_value = [{"path": "D:/Music/a.flac"}, {"path": "D:/Music/b.flac"}]

    result = get_all_library_paths(db)

    assert result == ["D:/Music/a.flac", "D:/Music/b.flac"]
    db.library.list_files.assert_called_once_with(limit=DEFAULT_LIMIT)


@pytest.mark.unit
def test_get_file_modified_times_builds_mapping_from_list_files() -> None:
    db = make_db()
    db.library.list_files.return_value = [
        {"path": "D:/Music/a.flac", "modified_time": 10},
        {"path": "D:/Music/b.flac", "modified_time": 20},
        {"path": "D:/Music/skip.flac", "modified_time": None},
    ]

    result = get_file_modified_times(db)

    assert result == {"D:/Music/a.flac": 10, "D:/Music/b.flac": 20}
    db.library.list_files.assert_called_once_with(limit=DEFAULT_LIMIT)


@pytest.mark.unit
def test_get_tagged_file_paths_reads_tagged_file_docs_from_app_facade() -> None:
    db = make_db()
    db.app.list_file_docs_in_state.return_value = [
        {"_id": "library_files/1", "path": "D:/Music/a.flac"},
        {"_id": "library_files/2", "path": "D:/Music/b.flac"},
    ]

    result = get_tagged_file_paths(db)

    assert result == ["D:/Music/a.flac", "D:/Music/b.flac"]
    db.app.list_file_docs_in_state.assert_called_once_with(STATE_TAGGED, limit=DEFAULT_LIMIT)


@pytest.mark.unit
def test_get_folder_rel_paths_uses_library_folder_listing() -> None:
    db = make_db()
    db.library.list_folders_for_library.return_value = [{"path": "Artist"}, {"path": "Artist/Album"}]

    result = get_folder_rel_paths(db, "abc123")

    assert result == {"Artist", "Artist/Album"}
    db.library.list_folders_for_library.assert_called_once_with("libraries/abc123")


@pytest.mark.unit
def test_get_files_for_folder_marks_tagged_state_from_app_facade() -> None:
    db = make_db()
    matching_doc = {
        "_id": "library_files/1",
        "path": "D:/Music/Artist/Album/song.flac",
        "normalized_path": "Artist/Album/song.flac",
        "has_tagged_state": True,
    }
    db.library.list_library_files_for_folder.return_value = [matching_doc]

    result = get_files_for_folder(db, "libraries/1", "Artist/Album")

    assert result == {matching_doc["path"]: matching_doc}
    db.library.list_library_files_for_folder.assert_called_once_with("libraries/1", "Artist/Album")


@pytest.mark.unit
def test_get_files_for_folders_matches_root_and_nested_paths() -> None:
    db = make_db()
    root_doc = {"_id": "library_files/1", "path": "D:/Music/root.flac", "normalized_path": "root.flac"}
    nested_doc = {"_id": "library_files/2", "path": "D:/Music/Artist/song.flac", "normalized_path": "Artist/song.flac"}
    db.library.list_library_files.return_value = [root_doc, nested_doc]
    db.app.list_files_in_state.return_value = ["library_files/2"]

    result = get_files_for_folders(db, "libraries/1", ["", "Artist"])

    assert result == {
        root_doc["path"]: {**root_doc, "has_tagged_state": False},
        nested_doc["path"]: {**nested_doc, "has_tagged_state": True},
    }


@pytest.mark.unit
def test_count_library_files_normalizes_library_id_for_facade_count() -> None:
    db = make_db()
    db.library.count_library_file_links.return_value = 7

    result = count_library_files(db, "abc123")

    assert result == 7
    db.library.count_library_file_links.assert_called_once_with("libraries/abc123")


@pytest.mark.unit
def test_get_recently_processed_sorts_by_latest_activity() -> None:
    db = make_db()
    db.app.list_file_docs_in_state.return_value = [
        {
            "_id": "library_files/1",
            "normalized_path": "Artist/older.flac",
            "title": "Older",
            "artist": "Artist",
            "album": "Album",
            "scanned_at": 10,
        },
        {
            "_id": "library_files/2",
            "normalized_path": "Artist/newer.flac",
            "title": "Newer",
            "artist": "Artist",
            "album": "Album",
            "last_tagged_at": 20,
        },
    ]

    result = get_recently_processed(db, limit=1)

    assert result == [
        {
            "file_id": "library_files/2",
            "path": "Artist/newer.flac",
            "title": "Newer",
            "artist": "Artist",
            "album": "Album",
            "activity_at": 20,
            "activity_event": "tagged",
        }
    ]
    db.app.list_file_docs_in_state.assert_called_once_with(STATE_TAGGED, limit=DEFAULT_LIMIT)


@pytest.mark.unit
def test_get_recently_processed_scopes_to_library_ids() -> None:
    db = make_db()
    db.app.list_file_docs_in_state.return_value = [
        {"_id": "library_files/1", "normalized_path": "keep.flac", "scanned_at": 5},
        {"_id": "library_files/2", "normalized_path": "skip.flac", "scanned_at": 6},
    ]
    db.library.list_library_file_ids.return_value = ["library_files/1"]

    result = get_recently_processed(db, library_id="main")

    assert [row["file_id"] for row in result] == ["library_files/1"]
    db.library.list_library_file_ids.assert_called_once_with("libraries/main", limit=DEFAULT_LIMIT)


@pytest.mark.unit
def test_get_files_by_chromaprint_scoped_filters_library_files() -> None:
    db = make_db()
    matching_doc = {"_id": "library_files/1", "chromaprint": "abc"}
    db.library.list_library_files.return_value = [matching_doc, {"_id": "library_files/2", "chromaprint": "def"}]

    result = get_files_by_chromaprint(db, "abc", library_id="libraries/1")

    assert result == [matching_doc]
    db.library.list_library_files.assert_called_once_with("libraries/1", limit=None)


@pytest.mark.unit
def test_get_files_by_chromaprint_unscoped_uses_filtered_list_files() -> None:
    db = make_db()
    db.library.list_files.return_value = [{"_id": "library_files/1", "chromaprint": "abc"}]

    result = get_files_by_chromaprint(db, "abc")

    assert result == [{"_id": "library_files/1", "chromaprint": "abc"}]
    db.library.list_files.assert_called_once_with(filters={"chromaprint": "abc"}, limit=None)


@pytest.mark.unit
def test_get_tracks_by_file_ids_sorts_and_applies_defaults() -> None:
    db = make_db()
    db.library.get_files_by_ids.return_value = [
        {"path": "D:/Music/one.flac", "title": None, "artist": None, "album": None, "sort_rank": 1},
        {"path": "D:/Music/two.flac", "title": "Two", "artist": "Artist", "album": "Album", "sort_rank": 2},
    ]

    result = get_tracks_by_file_ids(db, {"library_files/1", "library_files/2"}, [("sort_rank", "desc")], limit=1)

    assert result == [{"path": "D:/Music/two.flac", "title": "Two", "artist": "Artist", "album": "Album"}]
    db.library.get_files_by_ids.assert_called_once()


@pytest.mark.unit
def test_get_library_stats_aggregates_global_file_docs() -> None:
    db = make_db()
    db.library.list_files.return_value = [
        {"artist": "Artist A", "album": "Album A", "duration_seconds": 10.5, "file_size": 100},
        {"artist": "Artist B", "album": "Album A", "duration_seconds": 9.5, "file_size": 200},
    ]
    db.library.count_files.return_value = 2

    with patch("nomarr.components.library.library_file_query_comp.count_untagged_files", return_value=4):
        result = get_library_stats(db)

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


@pytest.mark.unit
def test_get_library_counts_groups_parent_folders_by_library() -> None:
    db = make_db()
    db.library.list_library_keys.return_value = ["1"]
    db.library.list_library_files.return_value = [
        {"path": "D:/Music/Artist A/song.flac"},
        {"path": "D:/Music/Artist B/other.flac"},
    ]

    result = get_library_counts(db)

    assert result == {"libraries/1": {"file_count": 2, "folder_count": 2}}
    db.library.list_library_files.assert_called_once_with("libraries/1", limit=None)


@pytest.mark.unit
def test_get_artist_album_frequencies_delegates_to_library_facade() -> None:
    db = make_db()
    db.library.get_artist_album_frequencies.return_value = {
        "artist_rows": [("Artist A", 3)],
        "album_rows": [("Album A", 2)],
    }

    result = get_artist_album_frequencies(db, limit=5)

    assert result == {"artist_rows": [("Artist A", 3)], "album_rows": [("Album A", 2)]}
    db.library.get_artist_album_frequencies.assert_called_once_with(5)


@pytest.mark.unit
def test_search_library_files_with_tags_filters_and_hydrates_page() -> None:
    db = make_db()
    file_docs = [
        {
            "_id": "library_files/1",
            "artist": "Artist",
            "album": "Album",
            "title": "Song One",
            "path": "D:/Music/one.flac",
        },
        {"_id": "library_files/2", "artist": "Artist", "album": "Album", "title": "Other", "path": "D:/Music/two.flac"},
    ]
    db.library.search_files_by_text.side_effect = [file_docs, file_docs, [file_docs[0]]]
    db.library.list_tags.return_value = [{"_id": "tags/1"}]
    db.library.get_song_tag_edges_for_tags.return_value = [{"_from": "library_files/1", "_to": "tags/1"}]
    db.app.list_files_in_state.return_value = ["library_files/1"]
    db.library.get_files_by_ids.return_value = [file_docs[0]]
    db.library.get_tags_for_files_batch.return_value = [
        {"start_id": "library_files/1", "v": {"name": "genre", "value": "rock"}}
    ]
    db.library.get_library_ids_for_files.return_value = {"library_files/1": "libraries/1"}

    rows, total = search_library_files_with_tags(
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
            "_id": "library_files/1",
            "artist": "Artist",
            "album": "Album",
            "title": "Song One",
            "path": "D:/Music/one.flac",
            "tags": [{"key": "genre", "value": "rock", "type": "string", "is_nomarr": False}],
            "library_id": "libraries/1",
        }
    ]
    assert db.library.search_files_by_text.call_args_list == [
        call("artist", "%Artist%", limit=None),
        call("album", "%Album%", limit=None),
        call("title", "%song%", limit=None),
    ]
    db.library.list_tags.assert_called_once_with(limit=DEFAULT_LIMIT, name="genre", value="rock")
    db.library.get_song_tag_edges_for_tags.assert_called_once_with(["tags/1"])
    db.app.list_files_in_state.assert_called_once_with(STATE_TAGGED, limit=DEFAULT_LIMIT)
    db.library.get_tags_for_files_batch.assert_called_once_with(["library_files/1"])
    db.library.get_library_ids_for_files.assert_called_once_with(["library_files/1"])


@pytest.mark.unit
def test_search_files_by_tag_numeric_sorts_by_distance_and_hydrates_tags() -> None:
    db = make_db()
    db.library.list_tags.return_value = [{"_id": "tags/1", "value": 118.0}, {"_id": "tags/2", "value": 121.0}]
    db.library.get_song_tag_edges_for_tags.return_value = [
        {"_from": "library_files/1", "_to": "tags/1"},
        {"_from": "library_files/2", "_to": "tags/2"},
    ]
    db.library.get_files_by_ids.return_value = [
        {"_id": "library_files/1", "artist": "B", "album": "A", "title": "Far"},
        {"_id": "library_files/2", "artist": "A", "album": "A", "title": "Near"},
    ]
    db.library.get_tags_for_files_batch.return_value = [
        {"start_id": "library_files/1", "v": {"name": "nom:bpm", "value": 118.0}},
        {"start_id": "library_files/2", "v": {"name": "nom:bpm", "value": 121.0}},
    ]
    db.library.get_library_ids_for_files.return_value = {
        "library_files/1": "libraries/1",
        "library_files/2": "libraries/1",
    }

    result = search_files_by_tag(db, "nom:bpm", 120.0, limit=1, offset=0)

    assert result[0]["_id"] == "library_files/2"
    assert result[0]["distance"] == 1.0
    assert result[0]["library_id"] == "libraries/1"
    db.library.list_tags.assert_called_once_with(name="nom:bpm", limit=DEFAULT_LIMIT)
    db.library.get_song_tag_edges_for_tags.assert_called_once_with(["tags/1", "tags/2"], limit=DEFAULT_LIMIT)
    db.library.get_tags_for_files_batch.assert_called_once_with(["library_files/2"])
    db.library.get_library_ids_for_files.assert_called_once_with(["library_files/2"])


@pytest.mark.unit
def test_count_files_by_tag_uses_library_facade_for_string_and_numeric_modes() -> None:
    db = make_db()
    db.library.list_tags.return_value = [{"_id": "tags/1"}]
    db.library.get_song_tag_edges_for_tags.return_value = [
        {"_from": "library_files/1", "_to": "tags/1"},
        {"_from": "library_files/2", "_to": "tags/1"},
    ]

    string_count = count_files_by_tag(db, "genre", "rock")

    assert string_count == 2
    db.library.list_tags.assert_called_once_with(name="genre", value="rock", limit=DEFAULT_LIMIT)
    db.library.get_song_tag_edges_for_tags.assert_called_once_with(["tags/1"])

    db = make_db()
    db.library.list_tags.return_value = [{"_id": "tags/1", "value": 120.0}, {"_id": "tags/2", "value": True}]
    db.library.get_song_tag_edges_for_tags.return_value = [{"_from": "library_files/1", "_to": "tags/1"}]

    numeric_count = count_files_by_tag(db, "nom:bpm", 120.0)

    assert numeric_count == 1
    db.library.list_tags.assert_called_once_with(name="nom:bpm", limit=DEFAULT_LIMIT)
    db.library.get_song_tag_edges_for_tags.assert_called_once_with(["tags/1"])


@pytest.mark.unit
def test_get_tracks_for_matching_filters_valid_files_and_projects_isrc() -> None:
    db = make_db()
    db.library.list_files.return_value = [
        {
            "_id": "library_files/1",
            "path": "D:/Music/song.flac",
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
        }
    ]
    db.library.get_tags_for_files_batch.return_value = [
        {"start_id": "library_files/1", "v": {"name": "isrc", "value": "ABC123"}}
    ]

    result = get_tracks_for_matching(db)

    assert result == [
        {
            "_id": "library_files/1",
            "path": "D:/Music/song.flac",
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
            "isrc": "ABC123",
        }
    ]
    db.library.list_files.assert_called_once_with(filters={"is_valid": True}, limit=DEFAULT_LIMIT)
    db.library.get_tags_for_files_batch.assert_called_once_with(["library_files/1"])


@pytest.mark.unit
def test_get_tracks_for_matching_scopes_to_library_and_projects_isrc() -> None:
    db = make_db()
    db.library.list_library_files.return_value = [
        {
            "_id": "library_files/1",
            "is_valid": True,
            "path": "D:/Music/song.flac",
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
        }
    ]
    db.library.get_tags_for_files_batch.return_value = [
        {"start_id": "library_files/1", "v": {"name": "isrc", "value": "XYZ789"}}
    ]

    result = get_tracks_for_matching(db, library_id="main")

    assert result == [
        {
            "_id": "library_files/1",
            "path": "D:/Music/song.flac",
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
            "isrc": "XYZ789",
        }
    ]
    db.library.list_library_files.assert_called_once_with("libraries/main", limit=None)
    db.library.list_files.assert_not_called()
    db.library.get_tags_for_files_batch.assert_called_once_with(["library_files/1"])


@pytest.mark.unit
def test_clear_library_data_truncates_all_facades() -> None:
    db = make_db()
    db.ml.list_registered_vector_collection_names.return_value = ["vectors_track__hot__effnet"]
    db.library.list_files.return_value = [
        {"_id": "library_files/1"},
        {"_id": "library_files/2"},
        {"_id": None},
    ]

    with patch(
        "nomarr.components.ml.inference.ml_output_stream_store_comp.delete_output_streams"
    ) as mock_delete_output_streams:
        clear_library_data(db)

    db.ml.truncate_vector_collection.assert_called_once_with("vectors_track__hot__effnet")
    db.library.list_files.assert_called_once_with(limit=None)
    assert mock_delete_output_streams.call_args_list == [call(db, "library_files/1"), call(db, "library_files/2")]
    db.ml.truncate_vector_edges.assert_called_once_with()
    db.library.truncate_song_tag_edges.assert_called_once_with()
    db.app.truncate_file_state_edges.assert_called_once_with()
    db.library.truncate_file_links.assert_called_once_with()
    db.library.truncate_folder_links.assert_called_once_with()
    db.app.truncate_library_scan_edges.assert_called_once_with()
    db.app.truncate_pipeline_state_edges.assert_called_once_with()
    db.library.truncate_tags.assert_called_once_with()
    db.library.truncate_files.assert_called_once_with()
    db.library.truncate_folders.assert_called_once_with()
    db.app.truncate_scan_records.assert_called_once_with()
    db.app.truncate_pipeline_states.assert_called_once_with()


@pytest.mark.unit
def test_collect_file_ids_for_tag_ids_returns_edge_sources() -> None:
    db = make_db()
    db.library.get_song_tag_edges_for_tags.return_value = [
        {"_from": "library_files/1", "_to": "tags/1"},
        {"_from": "library_files/2", "_to": "tags/2"},
        {"_to": "tags/3"},
    ]

    result = _collect_file_ids_for_tag_ids(db, {"tags/1", "tags/2"})

    assert result == {"library_files/1", "library_files/2"}
    db.library.get_song_tag_edges_for_tags.assert_called_once()
