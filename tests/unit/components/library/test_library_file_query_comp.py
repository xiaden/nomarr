"""Tests for ``nomarr.components.library.library_file_query_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.components.library.library_file_query_comp import (
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
from nomarr.persistence.base import Field
from nomarr.persistence.constructor.pagination import DEFAULT_LIMIT


class TestGetFileById:
    """Tests for ``get_file_by_id()``."""

    @pytest.mark.unit
    def test_returns_library_file_document(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.get.return_value = {"_id": "library_files/1"}

        result = get_file_by_id(mock_db, "library_files/1")

        assert result == {"_id": "library_files/1"}
        mock_db.library_files.get.assert_called_once_with(_id="library_files/1")


class TestCountRecentlyTagged:
    """Tests for ``count_recently_tagged()``."""

    @pytest.mark.unit
    def test_counts_docs_from_field_based_gte_lookup(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.get.gte.return_value = [{"_id": "library_files/1"}, {"_id": "library_files/2"}]

        with patch("nomarr.components.library.library_file_query_comp.now_ms") as mock_now_ms:
            mock_now_ms.return_value.value = 10_000

            result = count_recently_tagged(mock_db, window_seconds=5)

        assert result == 2
        mock_db.library_files.get.gte.assert_called_once_with("last_tagged_at", 5_000)


class TestGetExistingFilePaths:
    """Tests for ``get_existing_file_paths()``."""

    @pytest.mark.unit
    def test_returns_existing_paths_from_field_lookup(self) -> None:
        mock_db = MagicMock()
        paths = ["D:/Music/song.flac", "D:/Music/other.flac"]
        mock_db.library_files.get.in_.return_value = [
            {"path": "D:/Music/song.flac"},
            {"path": "D:/Music/song.flac"},
            {"missing": True},
        ]

        result = get_existing_file_paths(mock_db, paths)

        assert result == {"D:/Music/song.flac"}
        mock_db.library_files.get.in_.assert_called_once_with(Field("path", paths))


class TestGetFilesByIdsWithTags:
    """Tests for ``get_files_by_ids_with_tags()``."""

    @pytest.mark.unit
    def test_returns_hydrated_files_from_constructor_calls(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.get.in_.return_value = [{"_id": "library_files/1", "path": "D:/Music/song.flac"}]
        mock_db.library_files.song_has_tags.return_value = [{"name": "genre", "value": "rock"}]
        mock_db.library_contains_file.get.return_value = [{"_from": "libraries/1"}]

        result = get_files_by_ids_with_tags(mock_db, ["library_files/1"])

        assert result == [
            {
                "_id": "library_files/1",
                "path": "D:/Music/song.flac",
                "tags": [{"key": "genre", "value": "rock", "type": "string", "is_nomarr": False}],
                "library_id": "libraries/1",
            }
        ]
        mock_db.library_files.get.in_.assert_called_once_with(Field("_id", ["library_files/1"]), limit=None)
        mock_db.library_files.song_has_tags.assert_called_once_with("library_files/1", limit=DEFAULT_LIMIT)
        mock_db.library_contains_file.get.assert_called_once_with(_to="library_files/1", limit=1)

    @pytest.mark.unit
    def test_returns_empty_list_without_query_when_ids_empty(self) -> None:
        mock_db = MagicMock()

        result = get_files_by_ids_with_tags(mock_db, [])

        assert result == []
        mock_db.library_files.get.in_.assert_not_called()


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
        mock_db.libraries.library_contains_file.return_value = [row]

        result = get_library_file(mock_db, "song.flac", library_id="libraries/1")

        assert result == row
        mock_db.libraries.library_contains_file.assert_called_once_with("libraries/1", limit=DEFAULT_LIMIT)

    @pytest.mark.unit
    def test_returns_none_when_query_has_no_match(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.get.side_effect = [[], None]

        result = get_library_file(mock_db, "missing.flac")

        assert result is None

    @pytest.mark.unit
    def test_falls_back_to_absolute_path_lookup_when_normalized_path_has_no_match(self) -> None:
        mock_db = MagicMock()
        row = {"_id": "library_files/1", "path": "D:/Music/song.flac"}
        mock_db.library_files.get.side_effect = [[], row]

        result = get_library_file(mock_db, "D:/Music/song.flac")

        assert result == row
        assert mock_db.library_files.get.call_args_list == [
            call(normalized_path="D:/Music/song.flac", limit=1),
            call(path="D:/Music/song.flac"),
        ]


class TestGetFilesByPathsBulk:
    """Tests for ``get_files_by_paths_bulk()``."""

    @pytest.mark.unit
    def test_delegates_to_concrete_library_files_bulk_lookup_when_available(self) -> None:
        class LibraryFilesOps:
            def __init__(self) -> None:
                self.calls: list[list[str]] = []

            def get_files_by_paths_bulk(self, paths: list[str]) -> dict[str, dict[str, str]]:
                self.calls.append(paths)
                return {paths[0]: {"_id": "library_files/1"}}

        mock_db = MagicMock()
        mock_db.library_files = LibraryFilesOps()

        result = get_files_by_paths_bulk(mock_db, ["artist/song.flac"])

        assert result == {"artist/song.flac": {"_id": "library_files/1"}}
        assert mock_db.library_files.calls == [["artist/song.flac"]]

    @pytest.mark.unit
    def test_maps_results_by_matching_normalized_and_absolute_paths(self) -> None:
        mock_db = MagicMock()
        doc = {
            "_id": "library_files/1",
            "normalized_path": "artist/song.flac",
            "path": "D:/Music/artist/song.flac",
        }
        mock_db.library_files.get.in_.side_effect = [[doc], [doc]]

        result = get_files_by_paths_bulk(
            mock_db,
            ["artist/song.flac", "D:/Music/artist/song.flac"],
        )

        assert result == {
            "artist/song.flac": doc,
            "D:/Music/artist/song.flac": doc,
        }
        mock_db.library_files.get.in_.assert_has_calls(
            [
                call(Field("path", ["artist/song.flac", "D:/Music/artist/song.flac"]), limit=None),
                call(Field("normalized_path", ["artist/song.flac", "D:/Music/artist/song.flac"]), limit=None),
            ]
        )

    @pytest.mark.unit
    def test_returns_empty_mapping_without_query_when_paths_empty(self) -> None:
        mock_db = MagicMock()

        result = get_files_by_paths_bulk(mock_db, [])

        assert result == {}
        mock_db.library_files.get.in_.assert_not_called()


class TestDetectNdPathPrefix:
    """Tests for ``detect_nd_path_prefix()``."""

    @pytest.mark.unit
    def test_delegates_to_concrete_library_files_prefix_detection_when_available(self) -> None:
        class LibraryFilesOps:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def detect_nd_path_prefix(self, nd_path: str) -> str | None:
                self.calls.append(nd_path)
                return "/music/"

        mock_db = MagicMock()
        mock_db.library_files = LibraryFilesOps()

        result = detect_nd_path_prefix(mock_db, "/music/artist/song.flac")

        assert result == "/music/"
        assert mock_db.library_files.calls == ["/music/artist/song.flac"]

    @pytest.mark.unit
    def test_returns_prefix_for_longest_matching_normalized_path(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.aggregate.return_value = [
            {"value": "song.flac"},
            {"value": "artist/song.flac"},
        ]

        result = detect_nd_path_prefix(mock_db, "/music/artist/song.flac")

        assert result == "/music/"

    @pytest.mark.unit
    def test_returns_none_when_prefix_not_found(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.aggregate.return_value = []

        result = detect_nd_path_prefix(mock_db, "/music/missing.flac")

        assert result is None


class TestListLibraryFiles:
    """Tests for ``list_library_files()``."""

    @pytest.mark.unit
    def test_lists_all_files_and_total_without_filters(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.aggregate.return_value = [
            {"value": "library_files/2"},
            {"value": "library_files/1"},
        ]
        mock_db.library_files.get.in_.return_value = [
            {"_id": "library_files/2", "artist": "B", "album": "A", "title": "T2"},
            {"_id": "library_files/1", "artist": "A", "album": "A", "title": "T1"},
        ]

        rows, total = list_library_files(mock_db, limit=10, offset=5)

        assert rows == []
        assert total == 2
        mock_db.library_files.aggregate.assert_called_once_with("_id", limit=DEFAULT_LIMIT)
        mock_db.library_files.get.in_.assert_called_once_with(
            Field("_id", ["library_files/2", "library_files/1"]), limit=None
        )

    @pytest.mark.unit
    def test_lists_library_scoped_files_with_artist_and_album_filters(self) -> None:
        mock_db = MagicMock()
        matching_row = {"_id": "library_files/9", "artist": "Artist", "album": "Album", "title": "Song"}
        mock_db.libraries.library_contains_file.return_value = [
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
        mock_db.libraries.library_contains_file.assert_called_once_with("libraries/1", limit=DEFAULT_LIMIT)


class TestPhaseOneQueryHelpers:
    """Tests for Phase 1 constructor-backed query helpers."""

    @pytest.mark.unit
    def test_get_all_library_paths_collects_paths_with_default_limit(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.aggregate.return_value = [{"value": "D:/Music/a.flac"}, {"value": "D:/Music/b.flac"}]

        result = get_all_library_paths(mock_db)

        assert result == ["D:/Music/a.flac", "D:/Music/b.flac"]
        mock_db.library_files.aggregate.assert_called_once_with("path", limit=DEFAULT_LIMIT)

    @pytest.mark.unit
    def test_get_file_modified_times_builds_mapping_from_full_scan(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.aggregate.return_value = [
            {"value": "library_files/1"},
            {"value": "library_files/2"},
        ]
        mock_db.library_files.get.in_.return_value = [
            {"path": "D:/Music/a.flac", "modified_time": 10},
            {"path": "D:/Music/b.flac", "modified_time": 20},
        ]

        result = get_file_modified_times(mock_db)

        assert result == {"D:/Music/a.flac": 10, "D:/Music/b.flac": 20}
        mock_db.library_files.aggregate.assert_called_once_with("_id", limit=DEFAULT_LIMIT)
        mock_db.library_files.get.in_.assert_called_once_with(
            Field("_id", ["library_files/1", "library_files/2"]), limit=None
        )

    @pytest.mark.unit
    def test_get_tagged_file_paths_hydrates_paths_from_tagged_file_ids(self) -> None:
        mock_db = MagicMock()
        mock_db.file_states.file_has_state.return_value = [{"_id": "library_files/1"}, {"_id": "library_files/2"}]
        mock_db.library_files.get.in_.return_value = [
            {"_id": "library_files/2", "path": "D:/Music/b.flac"},
            {"_id": "library_files/1", "path": "D:/Music/a.flac"},
        ]

        result = get_tagged_file_paths(mock_db)

        assert result == ["D:/Music/a.flac", "D:/Music/b.flac"]
        mock_db.file_states.file_has_state.assert_called_once_with("file_states/tagged", limit=DEFAULT_LIMIT)
        mock_db.library_files.get.in_.assert_called_once_with(
            Field("_id", ["library_files/1", "library_files/2"]), limit=None
        )

    @pytest.mark.unit
    def test_get_folder_rel_paths_returns_traversed_folder_paths(self) -> None:
        mock_db = MagicMock()
        mock_db.libraries.library_contains_folder.return_value = [{"path": "Artist"}, {"path": "Artist/Album"}]

        result = get_folder_rel_paths(mock_db, "abc123")

        assert result == {"Artist", "Artist/Album"}
        mock_db.libraries.library_contains_folder.assert_called_once_with("libraries/abc123", limit=DEFAULT_LIMIT)

    @pytest.mark.unit
    def test_get_files_for_folder_filters_by_normalized_prefix(self) -> None:
        mock_db = MagicMock()
        matching_doc = {"path": "D:/Music/Artist/Album/song.flac", "normalized_path": "Artist/Album/song.flac"}
        mock_db.libraries.library_contains_file.return_value = [
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
        mock_db.libraries.library_contains_file.return_value = [root_doc, nested_doc]

        result = get_files_for_folders(mock_db, "libraries/1", ["", "Artist"])

        assert result == {root_doc["path"]: root_doc, nested_doc["path"]: nested_doc}

    @pytest.mark.unit
    def test_count_library_files_normalizes_library_id_for_edge_count(self) -> None:
        mock_db = MagicMock()
        mock_db.library_contains_file.count.return_value = 7

        result = count_library_files(mock_db, "abc123")

        assert result == 7
        mock_db.library_contains_file.count.assert_called_once_with(Field("_from", "libraries/abc123"))

    @pytest.mark.unit
    def test_get_recently_processed_sorts_and_projects_rows(self) -> None:
        mock_db = MagicMock()
        mock_db.file_states.file_has_state.return_value = [
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
        mock_db.libraries.library_contains_file.return_value = [
            matching_doc,
            {"_id": "library_files/2", "chromaprint": "def"},
        ]

        result = get_files_by_chromaprint(mock_db, "abc", library_id="libraries/1")

        assert result == [matching_doc]

    @pytest.mark.unit
    def test_get_files_by_chromaprint_uses_many_lookup_without_library_filter(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.get.many.return_value = [{"_id": "library_files/1", "chromaprint": "abc"}]

        result = get_files_by_chromaprint(mock_db, "abc")

        assert result == [{"_id": "library_files/1", "chromaprint": "abc"}]
        mock_db.library_files.get.many.assert_called_once_with(chromaprint="abc", limit=None)

    @pytest.mark.unit
    def test_get_tracks_by_file_ids_sorts_and_applies_defaults(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.get.in_.return_value = [
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
        mock_db.library_files.aggregate.return_value = [
            {"value": "library_files/1"},
            {"value": "library_files/2"},
        ]
        mock_db.library_files.get.in_.return_value = [
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
        mock_db.library_contains_file.aggregate.return_value = [{"value": "libraries/1"}]
        mock_db.library_contains_file.get.return_value = [
            {"_to": "library_files/1"},
            {"_to": "library_files/2"},
        ]
        mock_db.library_files.get.in_.return_value = [
            {"path": "D:/Music/Artist A/song.flac"},
            {"path": "D:/Music/Artist B/other.flac"},
        ]

        result = get_library_counts(mock_db)

        assert result == {"libraries/1": {"file_count": 2, "folder_count": 2}}

    @pytest.mark.unit
    def test_get_artist_album_frequencies_converts_aggregate_rows(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.aggregate.side_effect = [
            [
                {"value": "Artist A", "count": 3},
                {"value": None, "count": 1},
            ],
            [
                {"value": "Album A", "count": 2},
            ],
        ]

        result = get_artist_album_frequencies(mock_db, limit=5)

        assert result == {
            "artist_rows": [("Artist A", 3)],
            "album_rows": [("Album A", 2)],
        }
        assert mock_db.library_files.aggregate.call_args_list == [call("artist", limit=5), call("album", limit=5)]


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
        mock_db.library_files.get.like.side_effect = [
            file_docs,
            file_docs,
            [file_docs[0]],
        ]
        # final by-id fetch returns the narrowed page
        mock_db.library_files.get.in_.return_value = [file_docs[0]]
        mock_db.tags.get.return_value = [{"_id": "tags/1"}]
        mock_db.song_has_tags.get.in_.return_value = [{"_from": "library_files/1"}]
        mock_db.file_states.file_has_state.return_value = [{"_id": "library_files/1"}]
        mock_db.library_files.song_has_tags.return_value = [{"name": "genre", "value": "rock"}]
        mock_db.library_contains_file.get.return_value = [{"_from": "libraries/1"}]

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
        mock_db.song_has_tags.get.in_.assert_called_once_with(Field("_to", ["tags/1"]))
        mock_db.library_files.get.like.assert_has_calls(
            [
                call("artist", "%Artist%"),
                call("album", "%Album%"),
                call("title", "%song%"),
            ]
        )

    @pytest.mark.unit
    def test_search_files_by_tag_numeric_sorts_by_distance_and_hydrates_tags(self) -> None:
        mock_db = MagicMock()
        mock_db.tags.get.return_value = [
            {"_id": "tags/1", "value": 118.0},
            {"_id": "tags/2", "value": 121.0},
        ]
        mock_db.song_has_tags.get.side_effect = [
            [{"_from": "library_files/1"}],
            [{"_from": "library_files/2"}],
        ]
        mock_db.library_files.get.in_.return_value = [
            {"_id": "library_files/1", "artist": "B", "album": "A", "title": "Far"},
            {"_id": "library_files/2", "artist": "A", "album": "A", "title": "Near"},
        ]
        mock_db.library_files.song_has_tags.return_value = [{"name": "nom:bpm", "value": 121.0}]
        mock_db.library_contains_file.get.return_value = [{"_from": "libraries/1"}]

        result = search_files_by_tag(mock_db, "nom:bpm", 120.0, limit=1, offset=0)

        assert result[0]["_id"] == "library_files/2"
        assert result[0]["distance"] == 1.0
        assert result[0]["library_id"] == "libraries/1"
        assert mock_db.song_has_tags.get.call_count == 2

    @pytest.mark.unit
    def test_count_files_by_tag_uses_exact_and_numeric_constructor_lookups(self) -> None:
        mock_db = MagicMock()
        mock_db.tags.get.return_value = [{"_id": "tags/1"}]
        mock_db.song_has_tags.get.in_.return_value = [
            {"_from": "library_files/1"},
            {"_from": "library_files/2"},
        ]

        string_count = count_files_by_tag(mock_db, "genre", "rock")

        assert string_count == 2
        mock_db.tags.get.assert_called_once_with(name="genre", value="rock", limit=DEFAULT_LIMIT)
        mock_db.song_has_tags.get.in_.assert_called_once_with(Field("_to", ["tags/1"]))

        mock_db = MagicMock()
        mock_db.tags.get.return_value = [
            {"_id": "tags/1", "value": 120.0},
            {"_id": "tags/2", "value": True},
        ]
        mock_db.song_has_tags.get.in_.return_value = [{"_from": "library_files/1"}]

        numeric_count = count_files_by_tag(mock_db, "nom:bpm", 120.0)

        assert numeric_count == 1
        mock_db.tags.get.assert_called_once_with(name="nom:bpm", limit=DEFAULT_LIMIT)
        mock_db.song_has_tags.get.in_.assert_called_once_with(Field("_to", ["tags/1"]))

    @pytest.mark.unit
    def test_get_tracks_for_matching_filters_valid_files_and_projects_isrc(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.get.return_value = [
            {
                "_id": "library_files/1",
                "path": "D:/Music/song.flac",
                "title": "Song",
                "artist": "Artist",
                "album": "Album",
            }
        ]
        mock_db.library_files.song_has_tags.by_ids.return_value = [
            {"start_id": "library_files/1", "v": {"name": "isrc", "value": "ABC123"}},
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
        mock_db.library_files.get.assert_called_once_with(is_valid=True, limit=DEFAULT_LIMIT)
        mock_db.library_files.song_has_tags.by_ids.assert_called_once_with(["library_files/1"], name="isrc")

    @pytest.mark.unit
    def test_get_tracks_for_matching_scopes_to_library_and_projects_isrc(self) -> None:
        mock_db = MagicMock()
        mock_db.libraries.library_contains_file.return_value = [
            {
                "_id": "library_files/1",
                "is_valid": True,
                "path": "D:/Music/song.flac",
                "title": "Song",
                "artist": "Artist",
                "album": "Album",
            }
        ]
        mock_db.library_files.song_has_tags.by_ids.return_value = [
            {"start_id": "library_files/1", "v": {"name": "isrc", "value": "XYZ789"}},
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
        mock_db.libraries.library_contains_file.assert_called_once_with(
            "libraries/main",
            limit=DEFAULT_LIMIT,
        )
        mock_db.library_files.get.assert_not_called()
        mock_db.library_files.song_has_tags.by_ids.assert_called_once_with(["library_files/1"], name="isrc")

    @pytest.mark.unit
    def test_clear_library_data_truncates_all_collections(self) -> None:
        mock_db = MagicMock()
        vector_coll = MagicMock()
        mock_db._template_namespaces = {"vectors_track__hot__effnet": vector_coll}

        clear_library_data(mock_db)

        vector_coll.truncate.assert_called_once()
        mock_db.segment_scores_stats.truncate.assert_called_once()
        mock_db.file_has_vectors.truncate.assert_called_once()
        mock_db.file_has_segment_stats.truncate.assert_called_once()
        mock_db.song_has_tags.truncate.assert_called_once()
        mock_db.file_has_state.truncate.assert_called_once()
        mock_db.library_contains_file.truncate.assert_called_once()
        mock_db.library_contains_folder.truncate.assert_called_once()
        mock_db.library_has_scan.truncate.assert_called_once()
        mock_db.library_has_pipeline_state.truncate.assert_called_once()
        mock_db.tags.truncate.assert_called_once()
        mock_db.library_files.truncate.assert_called_once()
        mock_db.library_folders.truncate.assert_called_once()
        mock_db.library_scans.truncate.assert_called_once()
        mock_db.library_pipeline_states.truncate.assert_called_once()


@pytest.mark.unit
class TestCollectFileIdsForTagIds:
    """Tests for ``_collect_file_ids_for_tag_ids()``."""

    def test_returns_file_ids_from_matching_edges(self) -> None:
        mock_db = MagicMock()
        mock_db.song_has_tags.get.in_.return_value = [
            {"_from": "library_files/1", "_to": "tags/1"},
            {"_from": "library_files/2", "_to": "tags/2"},
        ]

        result = _collect_file_ids_for_tag_ids(mock_db, {"tags/1", "tags/2"})

        assert result == {"library_files/1", "library_files/2"}
        tag_filter = mock_db.song_has_tags.get.in_.call_args.args[0]
        assert tag_filter.name == "_to"
        assert set(tag_filter.value) == {"tags/1", "tags/2"}

    def test_returns_empty_set_when_no_edges_match(self) -> None:
        mock_db = MagicMock()
        mock_db.song_has_tags.get.in_.return_value = []

        result = _collect_file_ids_for_tag_ids(mock_db, {"tags/missing"})

        assert result == set()
        tag_filter = mock_db.song_has_tags.get.in_.call_args.args[0]
        assert tag_filter.name == "_to"
        assert tag_filter.value == ["tags/missing"]

    def test_skips_edges_with_missing_or_non_string_from(self) -> None:
        mock_db = MagicMock()
        mock_db.song_has_tags.get.in_.return_value = [
            {"_from": "library_files/1", "_to": "tags/1"},
            {"_to": "tags/1"},
            {"_from": 123, "_to": "tags/1"},
            {"_from": None, "_to": "tags/1"},
        ]

        result = _collect_file_ids_for_tag_ids(mock_db, {"tags/1"})

        assert result == {"library_files/1"}
