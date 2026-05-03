"""Tests for ``nomarr.components.library.library_file_query_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.library_file_query_comp import (
    clear_library_data,
    count_files_by_tag,
    count_library_files,
    detect_nd_path_prefix,
    get_all_library_paths,
    get_artist_album_frequencies,
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
from nomarr.persistence.constructor.pagination import DEFAULT_LIMIT


class TestGetFileById:
    """Tests for ``get_file_by_id()``."""

    @pytest.mark.unit
    def test_returns_library_file_document(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.get.return_value = {"_id": "library_files/1"}

        result = get_file_by_id(mock_db, "library_files/1")

        assert result == {"_id": "library_files/1"}
        mock_db.library_files.get.assert_called_once_with("library_files/1")


class TestGetFilesByIdsWithTags:
    """Tests for ``get_files_by_ids_with_tags()``."""

    @pytest.mark.unit
    def test_returns_hydrated_files_from_constructor_calls(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.get.many.return_value = [{"_id": "library_files/1", "path": "D:/Music/song.flac"}]
        mock_db.library_files.traversal.return_value = [{"rel": "genre", "value": "rock"}]
        mock_db.library_contains_file._to.get.many.return_value = [{"_from": "libraries/1"}]

        result = get_files_by_ids_with_tags(mock_db, ["library_files/1"])

        assert result == [
            {
                "_id": "library_files/1",
                "path": "D:/Music/song.flac",
                "tags": [{"key": "genre", "value": "rock", "type": "string", "is_nomarr": False}],
                "library_id": "libraries/1",
            }
        ]
        mock_db.library_files.get.many.assert_called_once_with(["library_files/1"])
        mock_db.library_files.traversal.assert_called_once_with("library_files/1", "song_has_tags", limit=DEFAULT_LIMIT)
        mock_db.library_contains_file._to.get.many.assert_called_once_with("library_files/1", limit=1)

    @pytest.mark.unit
    def test_returns_empty_list_without_query_when_ids_empty(self) -> None:
        mock_db = MagicMock()

        result = get_files_by_ids_with_tags(mock_db, [])

        assert result == []
        mock_db.library_files.get.many.assert_not_called()


class TestGetLibraryFile:
    """Tests for ``get_library_file()``."""

    @pytest.mark.unit
    def test_returns_first_match_for_library_scoped_query(self) -> None:
        mock_db = MagicMock()
        row = {
            "_id": "library_files/1",
            "path": "D:/Music/song.flac",
            "normalized_path": "song.flac",
        }
        mock_db.libraries.traversal.return_value = [row]

        result = get_library_file(mock_db, "song.flac", library_id="libraries/1")

        assert result == row
        mock_db.libraries.traversal.assert_called_once_with("libraries/1", "library_contains_file", limit=DEFAULT_LIMIT)

    @pytest.mark.unit
    def test_returns_none_when_query_has_no_match(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.normalized_path.get.many.return_value = []
        mock_db.library_files.path.get.return_value = None

        result = get_library_file(mock_db, "missing.flac")

        assert result is None

    @pytest.mark.unit
    def test_falls_back_to_absolute_path_lookup_when_normalized_path_has_no_match(self) -> None:
        mock_db = MagicMock()
        row = {"_id": "library_files/1", "path": "D:/Music/song.flac"}
        mock_db.library_files.normalized_path.get.many.return_value = []
        mock_db.library_files.path.get.return_value = row

        result = get_library_file(mock_db, "D:/Music/song.flac")

        assert result == row
        mock_db.library_files.normalized_path.get.many.assert_called_once_with("D:/Music/song.flac", limit=1)
        mock_db.library_files.path.get.assert_called_once_with("D:/Music/song.flac")


class TestGetFilesByPathsBulk:
    """Tests for ``get_files_by_paths_bulk()``."""

    @pytest.mark.unit
    def test_maps_results_by_matching_normalized_and_absolute_paths(self) -> None:
        mock_db = MagicMock()
        doc = {
            "_id": "library_files/1",
            "normalized_path": "artist/song.flac",
            "path": "D:/Music/artist/song.flac",
        }
        mock_db.library_files.path.get.in_.return_value = [doc]
        mock_db.library_files.normalized_path.get.in_.return_value = [doc]

        result = get_files_by_paths_bulk(
            mock_db,
            ["artist/song.flac", "D:/Music/artist/song.flac"],
        )

        assert result == {
            "artist/song.flac": doc,
            "D:/Music/artist/song.flac": doc,
        }

    @pytest.mark.unit
    def test_returns_empty_mapping_without_query_when_paths_empty(self) -> None:
        mock_db = MagicMock()

        result = get_files_by_paths_bulk(mock_db, [])

        assert result == {}
        mock_db.library_files.path.get.in_.assert_not_called()
        mock_db.library_files.normalized_path.get.in_.assert_not_called()


class TestDetectNdPathPrefix:
    """Tests for ``detect_nd_path_prefix()``."""

    @pytest.mark.unit
    def test_returns_prefix_for_longest_matching_normalized_path(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.normalized_path.collect.return_value = [
            "song.flac",
            "artist/song.flac",
        ]

        result = detect_nd_path_prefix(mock_db, "/music/artist/song.flac")

        assert result == "/music/"

    @pytest.mark.unit
    def test_returns_none_when_prefix_not_found(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.normalized_path.collect.return_value = []

        result = detect_nd_path_prefix(mock_db, "/music/missing.flac")

        assert result is None


class TestListLibraryFiles:
    """Tests for ``list_library_files()``."""

    @pytest.mark.unit
    def test_lists_all_files_and_total_without_filters(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.get.many.by_filter.return_value = [
            {"_id": "library_files/2", "artist": "B", "album": "A", "title": "T2"},
            {"_id": "library_files/1", "artist": "A", "album": "A", "title": "T1"},
        ]

        rows, total = list_library_files(mock_db, limit=10, offset=5)

        assert rows == []
        assert total == 2
        mock_db.library_files.get.many.by_filter.assert_called_once_with({}, limit=DEFAULT_LIMIT)

    @pytest.mark.unit
    def test_lists_library_scoped_files_with_artist_and_album_filters(self) -> None:
        mock_db = MagicMock()
        matching_row = {"_id": "library_files/9", "artist": "Artist", "album": "Album", "title": "Song"}
        mock_db.libraries.traversal.return_value = [
            {"_id": "library_files/8", "artist": "Other", "album": "Album", "title": "Song"},
            matching_row,
        ]

        rows, total = list_library_files(
            mock_db,
            limit=3,
            offset=0,
            artist="Artist",
            album="Album",
            library_id="libraries/1",
        )

        assert rows == [matching_row]
        assert total == 1
        mock_db.libraries.traversal.assert_called_once_with("libraries/1", "library_contains_file", limit=DEFAULT_LIMIT)


class TestPhaseOneQueryHelpers:
    """Tests for Phase 1 constructor-backed query helpers."""

    @pytest.mark.unit
    def test_get_all_library_paths_collects_paths_with_default_limit(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.path.collect.return_value = ["D:/Music/a.flac", "D:/Music/b.flac"]

        result = get_all_library_paths(mock_db)

        assert result == ["D:/Music/a.flac", "D:/Music/b.flac"]
        mock_db.library_files.path.collect.assert_called_once_with(limit=DEFAULT_LIMIT)

    @pytest.mark.unit
    def test_get_file_modified_times_builds_mapping_from_full_scan(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.get.many.by_filter.return_value = [
            {"path": "D:/Music/a.flac", "modified_time": 10},
            {"path": "D:/Music/b.flac", "modified_time": 20},
        ]

        result = get_file_modified_times(mock_db)

        assert result == {"D:/Music/a.flac": 10, "D:/Music/b.flac": 20}
        mock_db.library_files.get.many.by_filter.assert_called_once_with({}, limit=DEFAULT_LIMIT)

    @pytest.mark.unit
    def test_get_tagged_file_paths_hydrates_paths_from_tagged_file_ids(self) -> None:
        mock_db = MagicMock()
        mock_db.file_states.traversal.return_value = [{"_id": "library_files/1"}, {"_id": "library_files/2"}]
        mock_db.library_files.get.many.return_value = [
            {"_id": "library_files/2", "path": "D:/Music/b.flac"},
            {"_id": "library_files/1", "path": "D:/Music/a.flac"},
        ]

        result = get_tagged_file_paths(mock_db)

        assert result == ["D:/Music/a.flac", "D:/Music/b.flac"]
        mock_db.file_states.traversal.assert_called_once_with(
            "file_states/tagged", "file_has_state", limit=DEFAULT_LIMIT
        )
        mock_db.library_files.get.many.assert_called_once_with(["library_files/1", "library_files/2"])

    @pytest.mark.unit
    def test_get_folder_rel_paths_returns_traversed_folder_paths(self) -> None:
        mock_db = MagicMock()
        mock_db.libraries.traversal.return_value = [{"path": "Artist"}, {"path": "Artist/Album"}]

        result = get_folder_rel_paths(mock_db, "abc123")

        assert result == {"Artist", "Artist/Album"}
        mock_db.libraries.traversal.assert_called_once_with(
            "libraries/abc123", "library_contains_folder", limit=DEFAULT_LIMIT
        )

    @pytest.mark.unit
    def test_get_files_for_folder_filters_by_normalized_prefix(self) -> None:
        mock_db = MagicMock()
        matching_doc = {"path": "D:/Music/Artist/Album/song.flac", "normalized_path": "Artist/Album/song.flac"}
        mock_db.libraries.traversal.return_value = [
            matching_doc,
            {"path": "D:/Music/Other/song.flac", "normalized_path": "Other/song.flac"},
        ]

        result = get_files_for_folder(mock_db, "libraries/1", "Artist/Album")

        assert result == {matching_doc["path"]: matching_doc}

    @pytest.mark.unit
    def test_get_files_for_folders_matches_root_and_nested_paths(self) -> None:
        mock_db = MagicMock()
        root_doc = {"path": "D:/Music/root.flac", "normalized_path": "root.flac"}
        nested_doc = {"path": "D:/Music/Artist/song.flac", "normalized_path": "Artist/song.flac"}
        mock_db.libraries.traversal.return_value = [root_doc, nested_doc]

        result = get_files_for_folders(mock_db, "libraries/1", ["", "Artist"])

        assert result == {root_doc["path"]: root_doc, nested_doc["path"]: nested_doc}

    @pytest.mark.unit
    def test_count_library_files_normalizes_library_id_for_edge_count(self) -> None:
        mock_db = MagicMock()
        mock_db.library_contains_file._from.count.return_value = 7

        result = count_library_files(mock_db, "abc123")

        assert result == 7
        mock_db.library_contains_file._from.count.assert_called_once_with("libraries/abc123")

    @pytest.mark.unit
    def test_get_recently_processed_sorts_and_projects_rows(self) -> None:
        mock_db = MagicMock()
        mock_db.file_states.traversal.return_value = [
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
                "scanned_at": 20,
            },
        ]

        result = get_recently_processed(mock_db, limit=1)

        assert result == [
            {
                "file_id": "library_files/2",
                "path": "Artist/newer.flac",
                "title": "Newer",
                "artist": "Artist",
                "album": "Album",
                "activity_at": 20,
                "activity_event": "scanned",
            },
        ]

    @pytest.mark.unit
    def test_get_files_by_chromaprint_filters_library_traversal_results(self) -> None:
        mock_db = MagicMock()
        matching_doc = {"_id": "library_files/1", "chromaprint": "abc"}
        mock_db.libraries.traversal.return_value = [matching_doc, {"_id": "library_files/2", "chromaprint": "def"}]

        result = get_files_by_chromaprint(mock_db, "abc", library_id="libraries/1")

        assert result == [matching_doc]

    @pytest.mark.unit
    def test_get_tracks_by_file_ids_sorts_and_applies_defaults(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.get.many.return_value = [
            {"path": "D:/Music/one.flac", "title": None, "artist": None, "album": None, "sort_rank": 1},
            {
                "path": "D:/Music/two.flac",
                "title": "Two",
                "artist": "Artist",
                "album": "Album",
                "sort_rank": 2,
            },
        ]

        result = get_tracks_by_file_ids(
            mock_db, {"library_files/1", "library_files/2"}, [("sort_rank", "desc")], limit=1
        )

        assert result == [{"path": "D:/Music/two.flac", "title": "Two", "artist": "Artist", "album": "Album"}]

    @pytest.mark.unit
    def test_get_library_stats_aggregates_file_docs_and_needs_tagging_count(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.get.many.by_filter.return_value = [
            {"artist": "Artist A", "album": "Album A", "duration_seconds": 10.5, "file_size": 100},
            {"artist": "Artist B", "album": "Album A", "duration_seconds": 9.5, "file_size": 200},
        ]
        mock_db.library_files.count.return_value = 2

        with patch(
            "nomarr.components.library.library_file_query_comp.count_untagged_files",
            return_value=4,
        ):
            result = get_library_stats(mock_db)

        assert result == {
            "total_files": 2,
            "total_artists": 2,
            "total_albums": 1,
            "total_duration": 20.0,
            "total_size": 300,
            "needs_tagging_count": 4,
        }

    @pytest.mark.unit
    def test_get_library_counts_groups_edges_and_unique_parent_folders(self) -> None:
        mock_db = MagicMock()
        mock_db.library_contains_file._from.collect.return_value = ["libraries/1"]
        mock_db.library_contains_file._from.get.many.return_value = [
            {"_to": "library_files/1"},
            {"_to": "library_files/2"},
        ]
        mock_db.library_files.get.many.return_value = [
            {"path": "D:/Music/Artist A/song.flac"},
            {"path": "D:/Music/Artist B/other.flac"},
        ]

        result = get_library_counts(mock_db)

        assert result == {"libraries/1": {"file_count": 2, "folder_count": 2}}

    @pytest.mark.unit
    def test_get_artist_album_frequencies_converts_aggregate_rows(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.artist.aggregate.return_value = [
            {"value": "Artist A", "count": 3},
            {"value": None, "count": 1},
        ]
        mock_db.library_files.album.aggregate.return_value = [
            {"value": "Album A", "count": 2},
        ]

        result = get_artist_album_frequencies(mock_db, limit=5)

        assert result == {
            "artist_rows": [("Artist A", 3)],
            "album_rows": [("Album A", 2)],
        }
        mock_db.library_files.artist.aggregate.assert_called_once_with(limit=5)
        mock_db.library_files.album.aggregate.assert_called_once_with(limit=5)


class TestPhaseTwoQueryHelpers:
    """Tests for Phase 2 constructor-backed query helpers."""

    @pytest.mark.unit
    def test_search_library_files_with_tags_filters_and_hydrates_page(self) -> None:
        mock_db = MagicMock()
        file_docs = [
            {
                "_id": "library_files/1",
                "artist": "Artist",
                "album": "Album",
                "title": "Song One",
                "path": "D:/Music/one.flac",
            },
            {
                "_id": "library_files/2",
                "artist": "Artist",
                "album": "Album",
                "title": "Other",
                "path": "D:/Music/two.flac",
            },
        ]
        # artist/album LIKE queries each return both files; title LIKE (t: prefix) narrows to file 1
        mock_db.library_files.artist.get.like.return_value = file_docs
        mock_db.library_files.album.get.like.return_value = file_docs
        mock_db.library_files.title.get.like.return_value = [file_docs[0]]
        # final by-id fetch returns the narrowed page
        mock_db.library_files.get.many.return_value = [file_docs[0]]
        mock_db.tags.get.many.by_filter.return_value = [{"_id": "tags/1"}]
        mock_db.song_has_tags._to.get.in_.return_value = [{"_from": "library_files/1"}]
        mock_db.file_states.traversal.return_value = [{"_id": "library_files/1"}]
        mock_db.library_files.traversal.return_value = [{"rel": "genre", "value": "rock"}]
        mock_db.library_contains_file._to.get.many.return_value = [{"_from": "libraries/1"}]

        rows, total = search_library_files_with_tags(
            mock_db,
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
        mock_db.song_has_tags._to.get.in_.assert_called_once_with(["tags/1"], limit=None)

    @pytest.mark.unit
    def test_search_files_by_tag_numeric_sorts_by_distance_and_hydrates_tags(self) -> None:
        mock_db = MagicMock()
        mock_db.tags.rel.get.many.return_value = [
            {"_id": "tags/1", "value": 118.0},
            {"_id": "tags/2", "value": 121.0},
        ]
        mock_db.song_has_tags._to.get.many.side_effect = [
            [{"_from": "library_files/1"}],
            [{"_from": "library_files/2"}],
        ]
        mock_db.library_files.get.many.return_value = [
            {"_id": "library_files/1", "artist": "B", "album": "A", "title": "Far"},
            {"_id": "library_files/2", "artist": "A", "album": "A", "title": "Near"},
        ]
        mock_db.library_files.traversal.return_value = [{"rel": "nom:bpm", "value": 121.0}]
        mock_db.library_contains_file._to.get.many.return_value = [{"_from": "libraries/1"}]

        result = search_files_by_tag(mock_db, "nom:bpm", 120.0, limit=1, offset=0)

        assert result[0]["_id"] == "library_files/2"
        assert result[0]["distance"] == 1.0
        assert result[0]["library_id"] == "libraries/1"
        assert mock_db.song_has_tags._to.get.many.call_count == 2

    @pytest.mark.unit
    def test_count_files_by_tag_uses_exact_and_numeric_constructor_lookups(self) -> None:
        mock_db = MagicMock()
        mock_db.tags.get.many.by_filter.return_value = [{"_id": "tags/1"}]
        mock_db.song_has_tags._to.get.in_.return_value = [
            {"_from": "library_files/1"},
            {"_from": "library_files/2"},
        ]

        string_count = count_files_by_tag(mock_db, "genre", "rock")

        assert string_count == 2
        mock_db.tags.get.many.by_filter.assert_called_once_with({"rel": "genre", "value": "rock"}, limit=DEFAULT_LIMIT)
        mock_db.song_has_tags._to.get.in_.assert_called_once_with(["tags/1"], limit=None)

        mock_db = MagicMock()
        mock_db.tags.rel.get.many.return_value = [
            {"_id": "tags/1", "value": 120.0},
            {"_id": "tags/2", "value": True},
        ]
        mock_db.song_has_tags._to.get.in_.return_value = [{"_from": "library_files/1"}]

        numeric_count = count_files_by_tag(mock_db, "nom:bpm", 120.0)

        assert numeric_count == 1
        mock_db.tags.rel.get.many.assert_called_once_with("nom:bpm", limit=DEFAULT_LIMIT)
        mock_db.song_has_tags._to.get.in_.assert_called_once_with(["tags/1"], limit=None)

    @pytest.mark.unit
    def test_get_tracks_for_matching_filters_valid_files_and_projects_isrc(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.get.many.by_filter.return_value = [
            {
                "_id": "library_files/1",
                "path": "D:/Music/song.flac",
                "title": "Song",
                "artist": "Artist",
                "album": "Album",
            }
        ]
        mock_db.library_files.traversal.by_ids.return_value = [
            {"start_id": "library_files/1", "v": {"rel": "isrc", "value": "ABC123"}},
        ]

        result = get_tracks_for_matching(mock_db)

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
        mock_db.library_files.get.many.by_filter.assert_called_once_with({"is_valid": True}, limit=DEFAULT_LIMIT)
        mock_db.library_files.traversal.by_ids.assert_called_once_with(
            ["library_files/1"],
            "song_has_tags",
            target_filter={"rel": "isrc"},
        )

    @pytest.mark.unit
    def test_get_tracks_for_matching_scopes_to_library_and_projects_isrc(self) -> None:
        mock_db = MagicMock()
        mock_db.libraries.traversal.return_value = [
            {
                "_id": "library_files/1",
                "is_valid": True,
                "path": "D:/Music/song.flac",
                "title": "Song",
                "artist": "Artist",
                "album": "Album",
            }
        ]
        mock_db.library_files.traversal.by_ids.return_value = [
            {"start_id": "library_files/1", "v": {"rel": "isrc", "value": "XYZ789"}},
        ]

        result = get_tracks_for_matching(mock_db, library_id="main")

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
        mock_db.libraries.traversal.assert_called_once_with(
            "libraries/main",
            "library_contains_file",
            limit=DEFAULT_LIMIT,
        )
        mock_db.library_files.get.many.by_filter.assert_not_called()
        mock_db.library_files.traversal.by_ids.assert_called_once_with(
            ["library_files/1"],
            "song_has_tags",
            target_filter={"rel": "isrc"},
        )

    @pytest.mark.unit
    def test_clear_library_data_truncates_then_batches_library_files(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files._id.collect.side_effect = [["library_files/1"], []]

        with patch(
            "nomarr.components.ml.vectors.ml_vector_registry_comp.delete_vectors_by_file_ids"
        ) as mock_delete_vectors:
            clear_library_data(mock_db)

        mock_db.segment_scores_stats.truncate.assert_called_once()
        mock_db.song_has_tags.truncate.assert_called_once()
        mock_delete_vectors.assert_called_once_with(mock_db, ["library_files/1"])
        mock_db.library_files.delete.assert_called_once_with(["library_files/1"])
