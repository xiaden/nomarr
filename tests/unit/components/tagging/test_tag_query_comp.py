"""Tests for nomarr.components.tagging.tag_query_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from nomarr.components.tagging.tag_query_comp import (
    _candidate_filter_values,
    _enrich_tag,
    _file_ids_for_tag_docs,
    _filter_tags_by_search,
    _first_name_value,
    _matches_tag_operator,
    _numeric_value,
    count_tags_by_name,
    get_distinct_tag_values_for_files,
    get_file_ids_matching_tag,
    get_nomarr_tags_bulk,
    get_song_tags,
    get_tag,
    get_tag_values_grouped_by_file,
    list_songs_for_tag,
    list_tags_by_name,
)


class TestFilterTagsBySearch:
    """Tests for _filter_tags_by_search."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_all_tags_when_search_is_none(self) -> None:
        tags = [{"value": "Rock"}, {"value": "Jazz"}]

        result = _filter_tags_by_search(tags, None)

        assert result == tags

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_list_when_no_tags_match(self) -> None:
        tags = [{"value": "Rock"}, {"value": "Jazz"}]

        result = _filter_tags_by_search(tags, "classical")

        assert result == []

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_filters_case_insensitively(self) -> None:
        tags = [{"value": "Dream Pop"}, {"value": "Metal"}]

        result = _filter_tags_by_search(tags, "dream")

        assert result == [{"value": "Dream Pop"}]


class TestMatchesTagOperator:
    """Tests for _matches_tag_operator."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_true_for_equal_values(self) -> None:
        assert _matches_tag_operator("rock", "==", "rock") is True
        assert _matches_tag_operator("rock", "==", "jazz") is False

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_true_for_different_values_with_not_equal(self) -> None:
        assert _matches_tag_operator("rock", "!=", "jazz") is True
        assert _matches_tag_operator("rock", "!=", "rock") is False

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_contains_is_case_insensitive(self) -> None:
        assert _matches_tag_operator("Dream Pop", "CONTAINS", "dream") is True
        assert _matches_tag_operator("Dream Pop", "CONTAINS", "metal") is False

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_notcontains_returns_true_when_value_is_absent(self) -> None:
        assert _matches_tag_operator("Dream Pop", "NOTCONTAINS", "metal") is True
        assert _matches_tag_operator("Dream Pop", "NOTCONTAINS", "dream") is False

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_greater_than_compares_numerically_when_possible(self) -> None:
        assert _matches_tag_operator("10", ">", 2) is True
        assert _matches_tag_operator("2", ">", 10) is False

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_less_than_compares_numerically_when_possible(self) -> None:
        assert _matches_tag_operator("2", "<", 10) is True
        assert _matches_tag_operator("10", "<", 2) is False

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_falls_back_to_string_comparison_for_non_numeric_values(self) -> None:
        assert _matches_tag_operator("beta", ">", "alpha") is True
        assert _matches_tag_operator("alpha", "<", "beta") is True


class TestEnrichTag:
    """Tests for _enrich_tag."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_expected_fields_with_song_count(self) -> None:
        tag = {"_id": "tags/1", "_key": "1", "name": "genre", "value": "rock"}

        result = _enrich_tag(tag, 3)

        assert result == {
            "_id": "tags/1",
            "_key": "1",
            "name": "genre",
            "value": "rock",
            "song_count": 3,
        }


class TestCandidateFilterValues:
    """Tests for _candidate_filter_values."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_integer_string_generates_string_and_int_candidates(self) -> None:
        assert _candidate_filter_values("1") == ["1", 1]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_float_string_generates_string_and_float_candidates(self) -> None:
        assert _candidate_filter_values("3.14") == ["3.14", 3.14]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_non_numeric_string_returns_only_string_candidate(self) -> None:
        assert _candidate_filter_values("rock") == ["rock"]


class TestFirstNameValue:
    """Tests for _first_name_value."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_first_matching_string_value(self) -> None:
        tag_docs = [
            {"name": "artist", "value": "First Artist"},
            {"name": "genre", "value": "Rock"},
            {"name": "artist", "value": "Second Artist"},
        ]

        result = _first_name_value(tag_docs, "artist")

        assert result == "First Artist"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_string_when_no_match_is_found(self) -> None:
        result = _first_name_value([{"name": "genre", "value": "Rock"}], "artist")

        assert result == ""


class TestNumericValue:
    """Tests for _numeric_value."""

    @pytest.mark.unit
    @pytest.mark.mocked
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (7, 7.0),
            (3.5, 3.5),
            (" 42 ", 42.0),
            (True, 1.0),
            (False, 0.0),
        ],
    )
    def test_returns_float_for_numeric_inputs_and_bools(self, value: object, expected: float) -> None:
        assert _numeric_value(value) == expected

    @pytest.mark.unit
    @pytest.mark.mocked
    @pytest.mark.parametrize("value", ["", "abc", None])
    def test_returns_none_for_non_numeric_inputs(self, value: object) -> None:
        assert _numeric_value(value) is None


class TestListTagsByName:
    """Tests for list_tags_by_name."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_page_with_counts_from_aggregate_lookup(self) -> None:
        mock_db = MagicMock()
        mock_db.library.count_tags.return_value = 3
        mock_db.library.list_tags.return_value = [
            {"_id": "tags/1", "_key": "1", "name": "genre", "value": "Rock"},
            {"_id": "tags/2", "_key": "2", "name": "genre", "value": "Jazz"},
            {"_id": 3, "_key": "3", "name": "genre", "value": "Skip"},
        ]
        mock_db.library.count_song_tag_edges.side_effect = [4, 2]

        result = list_tags_by_name(mock_db, name="genre", limit=10, offset=0)

        assert result == [
            {"_id": "tags/2", "_key": "2", "name": "genre", "value": "Jazz", "song_count": 2},
            {"_id": "tags/1", "_key": "1", "name": "genre", "value": "Rock", "song_count": 4},
        ]
        assert mock_db.library.count_song_tag_edges.call_args_list == [call("tags/1"), call("tags/2")]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_sorts_by_song_count_using_aggregate_lookup(self) -> None:
        mock_db = MagicMock()
        mock_db.library.count_tags.return_value = 2
        mock_db.library.list_tags.return_value = [
            {"_id": "tags/1", "_key": "1", "name": "genre", "value": "Rock"},
            {"_id": "tags/2", "_key": "2", "name": "genre", "value": "Jazz"},
        ]
        mock_db.library.count_song_tag_edges.side_effect = [1, 3]

        result = list_tags_by_name(mock_db, name="genre", limit=10, offset=0, sort_by_count=True)

        assert result == [
            {"_id": "tags/2", "_key": "2", "name": "genre", "value": "Jazz", "song_count": 3},
            {"_id": "tags/1", "_key": "1", "name": "genre", "value": "Rock", "song_count": 1},
        ]
        assert mock_db.library.count_song_tag_edges.call_args_list == [call("tags/1"), call("tags/2")]


class TestGetTag:
    """Tests for get_tag."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_calls_db_get_and_returns_tag(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_tag.return_value = {"_id": "tags/1", "value": "rock"}

        result = get_tag(mock_db, "tags/1")

        assert result == {"_id": "tags/1", "value": "rock"}
        mock_db.library.get_tag.assert_called_once_with("tags/1")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_when_tag_is_not_found(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_tag.return_value = None

        result = get_tag(mock_db, "tags/missing")

        assert result is None
        mock_db.library.get_tag.assert_called_once_with("tags/missing")


class TestListSongsForTag:
    """Tests for list_songs_for_tag."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_from_values_as_strings(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_song_tag_edges_for_tags.return_value = [
            {"_from": "library_files/pre-0"},
            {"_from": "library_files/pre-1"},
            {"_from": "library_files/1"},
            {"_from": 123},
            {"_from": None},
        ]

        result = list_songs_for_tag(mock_db, "tags/1", limit=5, offset=2)

        assert result == ["library_files/1", "123"]
        mock_db.library.get_song_tag_edges_for_tags.assert_called_once_with(["tags/1"])

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_list_when_no_edges_exist(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_song_tag_edges_for_tags.return_value = []

        result = list_songs_for_tag(mock_db, "tags/1")

        assert result == []


class TestFileIdsForTagDocs:
    """Tests for _file_ids_for_tag_docs."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_batches_edge_lookup_with_single_in_query(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_song_tag_edges_for_tags.return_value = [
            {"_from": "library_files/1", "_to": "tags/1"},
            {"_from": "library_files/2", "_to": "tags/2"},
            {"_from": "library_files/1", "_to": "tags/2"},
        ]

        result = _file_ids_for_tag_docs(
            mock_db,
            [
                {"_id": "tags/1", "value": "Rock"},
                {"_id": "tags/2", "value": "Jazz"},
                {"_id": 3, "value": "Skip"},
            ],
        )

        assert result == {"library_files/1", "library_files/2"}
        mock_db.library.get_song_tag_edges_for_tags.assert_called_once_with(["tags/1", "tags/2"])


class TestCountTagsByName:
    """Tests for count_tags_by_name."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_count_for_name(self) -> None:
        mock_db = MagicMock()
        mock_db.library.count_tags.return_value = 3
        mock_db.library.list_tags.return_value = [
            {"value": "Rock"},
            {"value": "Jazz"},
            {"value": "Pop"},
        ]

        result = count_tags_by_name(mock_db, name="genre", search=None)

        assert result == 3
        mock_db.library.list_tags.assert_called_once_with(name="genre", limit=3)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_applies_search_filter_when_provided(self) -> None:
        mock_db = MagicMock()
        mock_db.library.count_tags.return_value = 3
        mock_db.library.aggregate_tag_field.return_value = [
            {"value": "tags/1"},
            {"value": "tags/2"},
            {"value": "tags/3"},
        ]
        mock_db.library.get_tag.side_effect = [
            {"value": "Dream Pop"},
            {"value": "Pop Rock"},
            {"value": "Jazz"},
        ]

        result = count_tags_by_name(mock_db, name=None, search="pop")

        assert result == 2
        mock_db.library.aggregate_tag_field.assert_called_once_with("_id", limit=3, offset=0)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_when_no_tags_match_search(self) -> None:
        mock_db = MagicMock()
        mock_db.library.count_tags.return_value = 2
        mock_db.library.list_tags.return_value = [
            {"value": "Rock"},
            {"value": "Jazz"},
        ]

        result = count_tags_by_name(mock_db, name="genre", search="classical")

        assert result == 0


class TestGetNomarrTagsBulk:
    """Tests for get_nomarr_tags_bulk."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_dict_for_empty_file_ids(self) -> None:
        mock_db = MagicMock()

        result = get_nomarr_tags_bulk(mock_db, [])

        assert result == {}
        mock_db.library.get_tags_for_files_batch.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_batches_nomarr_rows_by_file_id(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_tags_for_files_batch.return_value = [
            {"start_id": "library_files/1", "v": {"name": "nom:mood", "value": "calm"}},
            {"start_id": "library_files/1", "v": {"name": "nom:mood", "value": "bright"}},
            {"start_id": "library_files/2", "v": {"name": "nom:energy", "value": 0.91}},
        ]

        result = get_nomarr_tags_bulk(mock_db, ["library_files/1", "library_files/2"])

        assert result["library_files/1"].to_dict() == {"nom:mood": ("calm", "bright")}
        assert result["library_files/2"].to_dict() == {"nom:energy": (0.91,)}
        mock_db.library.get_tags_for_files_batch.assert_called_once_with(
            ["library_files/1", "library_files/2"],
            name_starts_with="nom:",
        )


class TestGetDistinctTagValuesForFiles:
    """Tests for get_distinct_tag_values_for_files."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_list_for_empty_file_ids(self) -> None:
        mock_db = MagicMock()

        result = get_distinct_tag_values_for_files(mock_db, [], "genre")

        assert result == []
        mock_db.library.get_tags_for_files_batch.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_sorted_distinct_string_values(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_tags_for_files_batch.return_value = [
            {"start_id": "library_files/1", "v": {"name": "genre", "value": "Rock"}},
            {"start_id": "library_files/1", "v": {"name": "genre", "value": "Pop"}},
            {"start_id": "library_files/2", "v": {"name": "genre", "value": "Rock"}},
            {"start_id": "library_files/2", "v": {"name": "genre", "value": "Ambient"}},
            {"start_id": "library_files/2", "v": {"name": "genre", "value": 123}},
        ]

        result = get_distinct_tag_values_for_files(
            mock_db,
            ["library_files/1", "library_files/2"],
            "genre",
        )

        assert result == ["Ambient", "Pop", "Rock"]
        mock_db.library.get_tags_for_files_batch.assert_called_once_with(["library_files/1", "library_files/2"])


class TestGetTagValuesGroupedByFile:
    """Tests for get_tag_values_grouped_by_file."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_dict_for_empty_file_ids(self) -> None:
        mock_db = MagicMock()

        result = get_tag_values_grouped_by_file(mock_db, [], "genre")

        assert result == {}
        mock_db.library.get_tags_for_files_batch.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_groups_matching_values_by_file(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_tags_for_files_batch.return_value = [
            {"start_id": "library_files/1", "v": {"name": "genre", "value": "Rock"}},
            {"start_id": "library_files/1", "v": {"name": "genre", "value": "Pop"}},
            {"start_id": "library_files/3", "v": {"name": "genre", "value": "Jazz"}},
            {"start_id": "library_files/3", "v": {"name": "genre", "value": "Jazz"}},
        ]

        result = get_tag_values_grouped_by_file(
            mock_db,
            ["library_files/1", "library_files/2", "library_files/3"],
            "genre",
        )

        assert result == {
            "library_files/1": {"Rock", "Pop"},
            "library_files/3": {"Jazz"},
        }
        mock_db.library.get_tags_for_files_batch.assert_called_once_with(
            ["library_files/1", "library_files/2", "library_files/3"]
        )


class TestGetSongTags:
    """Tests for get_song_tags."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_all_tags_when_no_filters_are_provided(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_tags_for_file.return_value = [
            {"name": "genre", "value": "Rock"},
            {"name": "artist", "value": "Artist One"},
            {"name": 123, "value": "skip"},
            {"name": "mood"},
        ]

        result = get_song_tags(mock_db, "library_files/1")

        assert result.to_dict() == {
            "artist": ("Artist One",),
            "genre": ("Rock",),
        }
        mock_db.library.get_tags_for_file.assert_called_once_with("library_files/1")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_filters_by_name_when_name_is_provided(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_tags_for_file.return_value = [
            {"name": "genre", "value": "Rock"},
            {"name": "artist", "value": "Artist One"},
            {"name": "genre", "value": "Pop"},
        ]

        result = get_song_tags(mock_db, "library_files/1", name="genre")

        assert result.to_dict() == {"genre": ("Rock", "Pop")}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_filters_to_nomarr_tags_when_nomarr_only_is_true(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_tags_for_file.return_value = [
            {"name": "genre", "value": "Rock"},
            {"name": "nom:mood-tier-1", "value": "calm"},
            {"name": "nom:mood-tier-1", "value": "bright"},
        ]

        result = get_song_tags(mock_db, "library_files/1", nomarr_only=True)

        assert result.to_dict() == {"nom:mood-tier-1": ("calm", "bright")}


class TestGetFileIdsMatchingTag:
    """Tests for get_file_ids_matching_tag - verifies the batched .get.in_() call path."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_uses_batched_in_query_for_file_lookup(self) -> None:
        """Matching tag ids are passed to .get.in_() in a single batch call."""
        mock_db = MagicMock()
        mock_db.library.count_tags.return_value = 2
        mock_db.library.list_tags.return_value = [
            {"_id": "tags/1", "value": "Rock"},
            {"_id": "tags/2", "value": "Jazz"},
        ]
        mock_db.library.get_song_tag_edges_for_tags.return_value = [
            {"_from": "library_files/1"},
            {"_from": "library_files/2"},
        ]

        result = get_file_ids_matching_tag(mock_db, "genre", "eq", "Rock")

        assert result == {"library_files/1", "library_files/2"}
        mock_db.library.get_song_tag_edges_for_tags.assert_called_once_with(["tags/1"])
