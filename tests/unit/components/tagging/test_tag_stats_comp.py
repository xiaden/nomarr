"""Tests for nomarr.components.tagging.tag_stats_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.tagging.tag_stats_comp import (
    _coerce_sum_value,
    _numeric_value,
    get_all_tag_stats_batched,
    get_genre_distribution,
    get_library_stats,
    get_tag_value_counts,
    get_unique_names,
    get_year_distribution,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_tag_dataclass import TagRef, TagUsage


def _usage(name: str, value: str | int | float | bool, song_count: int, namespace: str = "") -> TagUsage:
    """Build a domain ``TagUsage`` (typed tag-with-count result)."""
    return TagUsage(identity=TagRef(name=name, value=value, namespace=namespace), song_count=song_count)


def _song(**overrides: object) -> Song:
    base: dict = {
        "song_id": 1,
        "library_id": 1,
        "folder_id": None,
        "path": "/music/song.mp3",
        "normalized_path": "song.mp3",
        "file_size": 100,
        "modified_time": 1000,
        "duration_seconds": None,
        "chromaprint": None,
        "needs_tagging": False,
        "is_valid": True,
        "tagged": False,
        "calibration_hash": None,
        "write_claimed_by": None,
        "last_tagged_at": None,
        "scanned_at": None,
        "created_at": 1000,
    }
    base.update(overrides)
    return Song(**base)


class TestNumericValue:
    """Tests for tag_stats_comp._numeric_value."""

    @pytest.mark.unit
    @pytest.mark.mocked
    @pytest.mark.parametrize(
        ("value", "expected"),
        [(7, 7.0), (3.25, 3.25), (" 42 ", 42.0)],
    )
    def test_returns_float_for_numeric_inputs(self, value: object, expected: float) -> None:
        assert _numeric_value(value) == expected

    @pytest.mark.unit
    @pytest.mark.mocked
    @pytest.mark.parametrize(("value", "expected"), [(True, 1.0), (False, 0.0)])
    def test_returns_float_for_bool_inputs(self, value: object, expected: float) -> None:
        assert _numeric_value(value) == expected

    @pytest.mark.unit
    @pytest.mark.mocked
    @pytest.mark.parametrize("value", ["abc", "", None])
    def test_returns_none_for_non_numeric_inputs(self, value: object) -> None:
        assert _numeric_value(value) is None


class TestCoerceSumValue:
    """Tests for _coerce_sum_value."""

    @pytest.mark.unit
    @pytest.mark.mocked
    @pytest.mark.parametrize(("value", "expected"), [(7, 7.0), (3.5, 3.5)])
    def test_returns_float_for_int_and_float(self, value: object, expected: float) -> None:
        assert _coerce_sum_value(value) == expected

    @pytest.mark.unit
    @pytest.mark.mocked
    @pytest.mark.parametrize("value", [True, False, "7", None])
    def test_returns_zero_for_bool_string_and_none(self, value: object) -> None:
        assert _coerce_sum_value(value) == 0.0


class TestGetUniqueNames:
    """Tests for get_unique_names."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_all_names_when_nomarr_only_is_false(self) -> None:
        mock_db = MagicMock()
        mock_db.library.count_tags.return_value = 3
        mock_db.library.list_all_tag_names.return_value = [
            "genre",
            "nom:mood-tier-1",
            "year",
        ]

        result = get_unique_names(mock_db)

        assert result == ["genre", "nom:mood-tier-1", "year"]
        mock_db.library.list_all_tag_names.assert_called_once_with(limit=3)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_filters_to_nomarr_prefixed_names_when_requested(self) -> None:
        mock_db = MagicMock()
        mock_db.library.count_tags.return_value = 4
        mock_db.library.list_all_tag_names.return_value = [
            "genre",
            "nom:mood-tier-1",
            "year",
            "nom:embedding-cluster",
        ]

        result = get_unique_names(mock_db, nomarr_only=True)

        assert result == ["nom:mood-tier-1", "nom:embedding-cluster"]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_list_when_no_tags_exist(self) -> None:
        mock_db = MagicMock()
        mock_db.library.count_tags.return_value = 0
        mock_db.library.list_all_tag_names.return_value = []

        result = get_unique_names(mock_db)

        assert result == []
        mock_db.library.list_all_tag_names.assert_called_once_with(limit=0)


class TestGetLibraryStats:
    """Tests for get_library_stats."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_stats_when_no_files_exist(self) -> None:
        mock_db = MagicMock()
        mock_db.library.list_libraries.return_value = []

        result = get_library_stats(mock_db)

        assert result == {
            "file_count": 0,
            "total_duration_ms": 0,
            "total_file_size_bytes": 0,
            "avg_track_length_ms": 0,
        }
        mock_db.library.list_libraries.assert_called_once_with()
        mock_db.library.list_songs.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_aggregated_stats_for_files(self) -> None:
        mock_db = MagicMock()
        library = Library(name="main", root_path="/music")
        mock_db.library.list_libraries.return_value = [library]
        mock_db.library.list_songs.return_value = [
            _song(duration_seconds=180.5, file_size=1_000),
            _song(duration_seconds=None, file_size=2_000),
            _song(duration_seconds=59, file_size=500),
        ]

        result = get_library_stats(mock_db)

        assert result == {
            "file_count": 3,
            "total_duration_ms": 239500,
            "total_file_size_bytes": 3500,
            "avg_track_length_ms": pytest.approx(79833.33333333333),
        }
        mock_db.library.list_libraries.assert_called_once_with()
        mock_db.library.list_songs.assert_called_once_with(library, limit=None)


class TestGetTagValueCounts:
    """Tests for get_tag_value_counts."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_value_to_song_count_mapping(self) -> None:
        mock_db = MagicMock()
        mock_db.library.count_tags_filtered.return_value = 3
        mock_db.library.list_tags_with_song_count.return_value = [
            _usage("genre", "Rock", 4),
            _usage("genre", "Jazz", 2),
            _usage("genre", "Skip", 0),
        ]

        result = get_tag_value_counts(mock_db, "genre")

        assert result == {"Rock": 4, "Jazz": 2, "Skip": 0}
        mock_db.library.count_tags_filtered.assert_called_once_with(name="genre")
        mock_db.library.list_tags_with_song_count.assert_called_once_with(name="genre", limit=3, offset=0)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_dict_when_no_tags_exist_for_relation(self) -> None:
        mock_db = MagicMock()
        mock_db.library.count_tags_filtered.return_value = 0

        result = get_tag_value_counts(mock_db, "genre")

        assert result == {}
        mock_db.library.list_tags_with_song_count.assert_not_called()


class TestGetAllTagStatsBatched:
    """Tests for get_all_tag_stats_batched."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_dict_when_no_tags_exist(self) -> None:
        mock_db = MagicMock()
        mock_db.library.count_tags.return_value = 0

        result = get_all_tag_stats_batched(mock_db)

        assert result == {}
        mock_db.library.list_all_tag_names.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_uses_aggregate_counts_for_relation_summaries(self) -> None:
        mock_db = MagicMock()
        mock_db.library.count_tags.return_value = 3
        mock_db.library.list_tags_with_song_count.return_value = [
            _usage("genre", "Rock", 4),
            _usage("genre", "Jazz", 2),
            _usage("year", 1999, 1),
        ]

        result = get_all_tag_stats_batched(mock_db)

        assert result == {
            "genre": {
                "type": "string",
                "is_multivalue": True,
                "summary": "unique=2",
                "total_count": 6,
            },
            "year": {
                "type": "integer",
                "is_multivalue": False,
                "summary": "min=1999, max=1999, unique=1",
                "total_count": 1,
            },
        }
        mock_db.library.list_tags_with_song_count.assert_called_once_with(limit=3, offset=0)


class TestGetYearDistribution:
    """Tests for get_year_distribution."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_list_when_no_tags_exist(self) -> None:
        mock_db = MagicMock()
        mock_db.library.count_tags_filtered.return_value = 0

        result = get_year_distribution(mock_db)

        assert result == []
        mock_db.library.list_tags_with_song_count.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_year_rows_sorted_descending_and_excludes_zero_counts(self) -> None:
        mock_db = MagicMock()
        mock_db.library.count_tags_filtered.return_value = 4
        mock_db.library.list_tags_with_song_count.return_value = [
            _usage("year", 2019, 2),
            _usage("year", 2021, 1),
            _usage("year", "2020", 3),
            _usage("year", 2022, 0),
        ]

        result = get_year_distribution(mock_db)

        assert result == [
            {"year": 2021, "count": 1},
            {"year": "2020", "count": 3},
            {"year": 2019, "count": 2},
        ]
        mock_db.library.count_tags_filtered.assert_called_once_with(name="year")
        mock_db.library.list_tags_with_song_count.assert_called_once_with(name="year", limit=4, offset=0)


class TestGetGenreDistribution:
    """Tests for get_genre_distribution."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_list_when_no_tags_exist(self) -> None:
        mock_db = MagicMock()
        mock_db.library.count_tags_filtered.return_value = 0

        result = get_genre_distribution(mock_db)

        assert result == []
        mock_db.library.list_tags_with_song_count.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_rows_sorted_by_count_desc_then_genre_and_respects_limit(self) -> None:
        mock_db = MagicMock()
        mock_db.library.count_tags_filtered.return_value = 4
        mock_db.library.list_tags_with_song_count.return_value = [
            _usage("genre", "Rock", 2),
            _usage("genre", "Jazz", 5),
            _usage("genre", "Blues", 4),
            _usage("genre", 123, 0),
        ]

        result = get_genre_distribution(mock_db, limit=2)

        assert result == [
            {"genre": "Jazz", "count": 5},
            {"genre": "Blues", "count": 4},
        ]
        mock_db.library.count_tags_filtered.assert_called_once_with(name="genre")
        mock_db.library.list_tags_with_song_count.assert_called_once_with(name="genre", limit=4, offset=0)
