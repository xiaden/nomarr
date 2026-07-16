"""Tests for nomarr.components.tagging.tag_stats_comp module."""

from __future__ import annotations

from unittest.mock import AsyncMock

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
    async def test_returns_all_names_when_nomarr_only_is_false(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.count_tags.return_value = 3
        mock_db.library.list_all_tag_names.return_value = [
            "genre",
            "nom:mood-tier-1",
            "year",
        ]

        result = await get_unique_names(mock_db)

        assert result == ["genre", "nom:mood-tier-1", "year"]
        mock_db.library.list_all_tag_names.assert_called_once_with(limit=3)

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_filters_to_nomarr_prefixed_names_when_requested(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.count_tags.return_value = 4
        mock_db.library.list_all_tag_names.return_value = [
            "genre",
            "nom:mood-tier-1",
            "year",
            "nom:embedding-cluster",
        ]

        result = await get_unique_names(mock_db, nomarr_only=True)

        assert result == ["nom:mood-tier-1", "nom:embedding-cluster"]

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_returns_empty_list_when_no_tags_exist(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.count_tags.return_value = 0
        mock_db.library.list_all_tag_names.return_value = []

        result = await get_unique_names(mock_db)

        assert result == []
        mock_db.library.list_all_tag_names.assert_called_once_with(limit=0)


class TestGetLibraryStats:
    """Tests for get_library_stats."""

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_returns_zero_stats_when_no_files_exist(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.count_files.return_value = 0

        result = await get_library_stats(mock_db)

        assert result == {
            "file_count": 0,
            "total_duration_ms": 0,
            "total_file_size_bytes": 0,
            "avg_track_length_ms": 0,
        }
        mock_db.library.count_files.assert_called_once_with()
        mock_db.library.list_files.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_returns_aggregated_stats_for_files(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.count_files.return_value = 3
        mock_db.library.list_files.return_value = [
            {"duration_seconds": 180.5, "file_size": 1_000},
            {"duration_seconds": None, "file_size": 2_000},
            {"duration_seconds": 59, "file_size": 500},
        ]

        result = await get_library_stats(mock_db)

        assert result == {
            "file_count": 3,
            "total_duration_ms": 239500,
            "total_file_size_bytes": 3500,
            "avg_track_length_ms": pytest.approx(79833.33333333333),
        }
        mock_db.library.count_files.assert_called_once_with()
        mock_db.library.list_files.assert_called_once_with(limit=3)


class TestGetTagValueCounts:
    """Tests for get_tag_value_counts."""

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_returns_value_to_song_count_mapping(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.count_tags.return_value = 3
        mock_db.library.list_tags.return_value = [
            {"id": 1, "value": "Rock"},
            {"id": 2, "value": "Jazz"},
            {"id": 3, "value": "Skip"},
        ]

        mock_db.library.file_tag_repo.get_file_tag_edges_for_tags.return_value = [
            {"tag_id": 1},
            {"tag_id": 1},
            {"tag_id": 1},
            {"tag_id": 1},
            {"tag_id": 2},
            {"tag_id": 2},
        ]

        result = await get_tag_value_counts(mock_db, "genre")

        assert result == {"Rock": 4, "Jazz": 2, "Skip": 0}
        mock_db.library.list_tags.assert_called_once_with(name="genre", limit=3)
        mock_db.library.file_tag_repo.get_file_tag_edges_for_tags.assert_called_once_with([1, 2, 3])

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_returns_empty_dict_when_no_tags_exist_for_relation(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.count_tags.return_value = 0

        result = await get_tag_value_counts(mock_db, "genre")

        assert result == {}
        mock_db.library.list_tags.assert_not_called()
        mock_db.library.file_tag_repo.get_file_tag_edges_for_tags.assert_not_called()


class TestGetAllTagStatsBatched:
    """Tests for get_all_tag_stats_batched."""

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_returns_empty_dict_when_no_tags_exist(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.count_tags.return_value = 0

        result = await get_all_tag_stats_batched(mock_db)

        assert result == {}
        mock_db.library.list_all_tag_names.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_uses_aggregate_counts_for_relation_summaries(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.count_tags.return_value = 3
        mock_db.library.list_all_tag_names.return_value = ["genre", "year"]
        mock_db.library.list_tags.return_value = [
            {"id": 1, "name": "genre", "value": "Rock"},
            {"id": 2, "name": "genre", "value": "Jazz"},
            {"id": 3, "name": "year", "value": 1999},
        ]
        mock_db.library.file_tag_repo.get_file_tag_edges_for_tags.return_value = [
            {"tag_id": 1},
            {"tag_id": 1},
            {"tag_id": 1},
            {"tag_id": 1},
            {"tag_id": 2},
            {"tag_id": 2},
            {"tag_id": 3},
        ]

        result = await get_all_tag_stats_batched(mock_db)

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
        mock_db.library.list_tags.assert_called_once_with(limit=3)
        mock_db.library.file_tag_repo.get_file_tag_edges_for_tags.assert_called_once_with([1, 2, 3])


class TestGetYearDistribution:
    """Tests for get_year_distribution."""

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_returns_empty_list_when_no_tags_exist(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.count_tags.return_value = 0

        result = await get_year_distribution(mock_db)

        assert result == []

    @pytest.mark.unit
    @pytest.mark.mocked
    @pytest.mark.xfail(reason="Source uses PostgreSQL junction patterns; test mock data uses ArangoDB graph edges")
    async def test_returns_year_rows_sorted_descending_and_excludes_zero_counts(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.count_tags.return_value = 4
        mock_db.library.list_tags.return_value = [
            {"id": "tags/2019", "value": 2019},
            {"id": "tags/2021", "value": 2021},
            {"id": "tags/2020", "value": "2020"},
            {"id": "tags/zero", "value": 2022},
        ]
        mock_db.library.file_tag_repo.get_file_tag_edges_for_tags.return_value = [
            {"tag_id": 2019},
            {"tag_id": 2019},
            {"tag_id": 2021},
            {"tag_id": 2020},
            {"tag_id": 2020},
            {"tag_id": 2020},
        ]

        result = await get_year_distribution(mock_db)

        assert result == [
            {"year": 2021, "count": 1},
            {"year": "2020", "count": 3},
            {"year": 2019, "count": 2},
        ]
        mock_db.library.list_tags.assert_called_once_with(name="year", limit=4)
        mock_db.library.file_tag_repo.get_file_tag_edges_for_tags.assert_called_once_with(
            ["tags/2019", "tags/2021", "tags/2020", "tags/zero"]
        )


class TestGetGenreDistribution:
    """Tests for get_genre_distribution."""

    @pytest.mark.unit
    @pytest.mark.mocked
    async def test_returns_empty_list_when_no_tags_exist(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.count_tags.return_value = 0

        result = await get_genre_distribution(mock_db)

        assert result == []

    @pytest.mark.unit
    @pytest.mark.mocked
    @pytest.mark.xfail(reason="Source uses PostgreSQL junction patterns; test mock data uses ArangoDB graph edges")
    async def test_returns_rows_sorted_by_count_desc_then_genre_and_respects_limit(self) -> None:
        mock_db = AsyncMock()
        mock_db.library.count_tags.return_value = 4
        mock_db.library.list_tags.return_value = [
            {"id": "tags/rock", "value": "Rock"},
            {"id": "tags/jazz", "value": "Jazz"},
            {"id": "tags/blues", "value": "Blues"},
            {"id": "tags/skip", "value": 123},
        ]
        mock_db.library.file_tag_repo.get_file_tag_edges_for_tags.return_value = [
            {"_to": "tags/rock", "_from": 1},
            {"_to": "tags/rock", "_from": 2},
            {"_to": "tags/jazz", "_from": 3},
            {"_to": "tags/jazz", "_from": 4},
            {"_to": "tags/jazz", "_from": 5},
            {"_to": "tags/jazz", "_from": 6},
            {"_to": "tags/jazz", "_from": 7},
            {"_to": "tags/blues", "_from": 8},
            {"_to": "tags/blues", "_from": 9},
            {"_to": "tags/blues", "_from": 10},
            {"_to": "tags/blues", "_from": 11},
            {"_to": "tags/blues", "_from": 12},
        ]

        result = await get_genre_distribution(mock_db, limit=2)

        assert result == [
            {"genre": "Blues", "count": 5},
            {"genre": "Jazz", "count": 5},
        ]
        mock_db.library.list_tags.assert_called_once_with(name="genre", limit=4)
        mock_db.library.file_tag_repo.get_file_tag_edges_for_tags.assert_called_once_with(["tags/rock", "tags/jazz", "tags/blues"])
