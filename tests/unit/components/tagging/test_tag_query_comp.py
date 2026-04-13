"""Tests for nomarr.components.tagging.tag_query_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.tagging.tag_query_comp import (
    _candidate_filter_values,
    _enrich_tag,
    _filter_tags_by_search,
    _first_rel_value,
    _matches_tag_operator,
    _numeric_value,
    count_tags_by_rel,
    get_distinct_tag_values_for_files,
    get_song_tags,
    get_tag,
    get_tag_values_grouped_by_file,
    list_songs_for_tag,
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
        tag = {"_id": "tags/1", "_key": "1", "rel": "genre", "value": "rock"}

        result = _enrich_tag(tag, 3)

        assert result == {
            "_id": "tags/1",
            "_key": "1",
            "rel": "genre",
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


class TestFirstRelValue:
    """Tests for _first_rel_value."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_first_matching_string_value(self) -> None:
        tag_docs = [
            {"rel": "artist", "value": "First Artist"},
            {"rel": "genre", "value": "Rock"},
            {"rel": "artist", "value": "Second Artist"},
        ]

        result = _first_rel_value(tag_docs, "artist")

        assert result == "First Artist"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_string_when_no_match_is_found(self) -> None:
        result = _first_rel_value([{"rel": "genre", "value": "Rock"}], "artist")

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


class TestGetTag:
    """Tests for get_tag."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_calls_db_get_and_returns_tag(self) -> None:
        mock_db = MagicMock()
        mock_db.tags.get.return_value = {"_id": "tags/1", "value": "rock"}

        result = get_tag(mock_db, "tags/1")

        assert result == {"_id": "tags/1", "value": "rock"}
        mock_db.tags.get.assert_called_once_with("tags/1")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_when_tag_is_not_found(self) -> None:
        mock_db = MagicMock()
        mock_db.tags.get.return_value = None

        result = get_tag(mock_db, "tags/missing")

        assert result is None
        mock_db.tags.get.assert_called_once_with("tags/missing")


class TestListSongsForTag:
    """Tests for list_songs_for_tag."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_from_values_as_strings(self) -> None:
        mock_db = MagicMock()
        mock_db.song_has_tags._to.get.many.return_value = [
            {"_from": "library_files/1"},
            {"_from": 123},
            {"_from": None},
        ]

        result = list_songs_for_tag(mock_db, "tags/1", limit=5, offset=2)

        assert result == ["library_files/1", "123"]
        mock_db.song_has_tags._to.get.many.assert_called_once_with(
            "tags/1",
            limit=5,
            offset=2,
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_list_when_no_edges_exist(self) -> None:
        mock_db = MagicMock()
        mock_db.song_has_tags._to.get.many.return_value = []

        result = list_songs_for_tag(mock_db, "tags/1")

        assert result == []


class TestCountTagsByRel:
    """Tests for count_tags_by_rel."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_count_for_relation(self) -> None:
        mock_db = MagicMock()
        mock_db.tags.count.return_value = 3
        mock_db.tags.rel.get.many.return_value = [
            {"value": "Rock"},
            {"value": "Jazz"},
            {"value": "Pop"},
        ]

        result = count_tags_by_rel(mock_db, rel="genre", search=None)

        assert result == 3
        mock_db.tags.rel.get.many.assert_called_once_with("genre", limit=3)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_applies_search_filter_when_provided(self) -> None:
        mock_db = MagicMock()
        mock_db.tags.count.return_value = 3
        mock_db.tags.get.many.by_filter.return_value = [
            {"value": "Dream Pop"},
            {"value": "Pop Rock"},
            {"value": "Jazz"},
        ]

        result = count_tags_by_rel(mock_db, rel=None, search="pop")

        assert result == 2
        mock_db.tags.get.many.by_filter.assert_called_once_with({}, limit=3, offset=0)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_when_no_tags_match_search(self) -> None:
        mock_db = MagicMock()
        mock_db.tags.count.return_value = 2
        mock_db.tags.rel.get.many.return_value = [
            {"value": "Rock"},
            {"value": "Jazz"},
        ]

        result = count_tags_by_rel(mock_db, rel="genre", search="classical")

        assert result == 0


class TestGetDistinctTagValuesForFiles:
    """Tests for get_distinct_tag_values_for_files."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_list_for_empty_file_ids(self) -> None:
        mock_db = MagicMock()

        result = get_distinct_tag_values_for_files(mock_db, [], "genre")

        assert result == []
        mock_db.library_files.traversal.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_sorted_distinct_string_values(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.traversal.side_effect = [
            [
                {"rel": "genre", "value": "Rock"},
                {"rel": "genre", "value": "Pop"},
                {"rel": "artist", "value": "Artist One"},
            ],
            [
                {"rel": "genre", "value": "Rock"},
                {"rel": "genre", "value": "Ambient"},
                {"rel": "genre", "value": 123},
            ],
        ]

        result = get_distinct_tag_values_for_files(
            mock_db,
            ["library_files/1", "library_files/2"],
            "genre",
        )

        assert result == ["Ambient", "Pop", "Rock"]


class TestGetTagValuesGroupedByFile:
    """Tests for get_tag_values_grouped_by_file."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_dict_for_empty_file_ids(self) -> None:
        mock_db = MagicMock()

        result = get_tag_values_grouped_by_file(mock_db, [], "genre")

        assert result == {}
        mock_db.library_files.traversal.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_groups_matching_values_by_file(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.traversal.side_effect = [
            [
                {"rel": "genre", "value": "Rock"},
                {"rel": "genre", "value": "Pop"},
                {"rel": "artist", "value": "Artist One"},
            ],
            [{"rel": "artist", "value": "Artist Two"}],
            [
                {"rel": "genre", "value": "Jazz"},
                {"rel": "genre", "value": "Jazz"},
            ],
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


class TestGetSongTags:
    """Tests for get_song_tags."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_all_tags_when_no_filters_are_provided(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.traversal.return_value = [
            {"rel": "genre", "value": "Rock"},
            {"rel": "artist", "value": "Artist One"},
            {"rel": 123, "value": "skip"},
            {"rel": "mood"},
        ]

        result = get_song_tags(mock_db, "library_files/1")

        assert result.to_dict() == {
            "artist": ("Artist One",),
            "genre": ("Rock",),
        }
        mock_db.library_files.traversal.assert_called_once_with(
            "library_files/1",
            "song_has_tags",
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_filters_by_relation_when_rel_is_provided(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.traversal.return_value = [
            {"rel": "genre", "value": "Rock"},
            {"rel": "artist", "value": "Artist One"},
            {"rel": "genre", "value": "Pop"},
        ]

        result = get_song_tags(mock_db, "library_files/1", rel="genre")

        assert result.to_dict() == {"genre": ("Rock", "Pop")}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_filters_to_nomarr_tags_when_nomarr_only_is_true(self) -> None:
        mock_db = MagicMock()
        mock_db.library_files.traversal.return_value = [
            {"rel": "genre", "value": "Rock"},
            {"rel": "nom:mood-tier-1", "value": "calm"},
            {"rel": "nom:mood-tier-1", "value": "bright"},
        ]

        result = get_song_tags(mock_db, "library_files/1", nomarr_only=True)

        assert result.to_dict() == {"nom:mood-tier-1": ("calm", "bright")}
