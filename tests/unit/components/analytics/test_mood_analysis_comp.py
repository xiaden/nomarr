"""Tests for ``nomarr.components.analytics.mood_analysis_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.analytics.mood_analysis_comp import (
    get_mood_and_tier_tags_for_correlation,
    get_mood_balance,
    get_mood_coverage,
    get_mood_distribution_data,
)


class TestGetMoodCoverage:
    """Tests for ``get_mood_coverage``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_coverage_when_no_files(self) -> None:
        """Zero files should produce zero coverage for every tier."""
        mock_db = MagicMock()

        with patch(
            "nomarr.components.analytics.mood_analysis_comp.get_library_stats",
            return_value={"file_count": 0},
        ) as get_library_stats_mock:
            result = get_mood_coverage(mock_db)

        assert result == {
            "total_files": 0,
            "tiers": {
                "strict": {"tagged": 0, "percentage": 0.0},
                "regular": {"tagged": 0, "percentage": 0.0},
                "loose": {"tagged": 0, "percentage": 0.0},
            },
        }
        get_library_stats_mock.assert_called_once_with(mock_db, None)
        mock_db.tags.rel.get.many.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_percentage_for_each_tier(self) -> None:
        """Tier counts should be converted into rounded percentages."""
        mock_db = MagicMock()
        with (
            patch(
                "nomarr.components.analytics.mood_analysis_comp._get_tag_edge_rows",
                side_effect=[
                    [("library_files/1", "happy"), ("library_files/2", "calm"), ("library_files/1", "happy")],
                    [("library_files/3", "warm"), ("library_files/4", "bright"), ("library_files/3", "warm")],
                    [("library_files/5", "dreamy")],
                ],
            ) as get_tag_edge_rows_mock,
            patch(
                "nomarr.components.analytics.mood_analysis_comp.get_library_stats",
                return_value={"file_count": 10},
            ) as get_library_stats_mock,
        ):
            result = get_mood_coverage(mock_db)

        assert result == {
            "total_files": 10,
            "tiers": {
                "strict": {"tagged": 2, "percentage": 20.0},
                "regular": {"tagged": 2, "percentage": 20.0},
                "loose": {"tagged": 1, "percentage": 10.0},
            },
        }
        get_library_stats_mock.assert_called_once_with(mock_db, None)
        assert get_tag_edge_rows_mock.call_count == 3


class TestGetMoodBalance:
    """Tests for ``get_mood_balance``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_tiers_when_no_data(self) -> None:
        """Each tier should return an empty list when the query yields no rows."""
        mock_db = MagicMock()
        with patch(
            "nomarr.components.analytics.mood_analysis_comp._get_tag_edge_rows",
            side_effect=[[], [], []],
        ) as get_tag_edge_rows_mock:
            result = get_mood_balance(mock_db)

        assert result == {"strict": [], "regular": [], "loose": []}
        assert get_tag_edge_rows_mock.call_count == 3

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_counts_plain_mood_values(self) -> None:
        """Repeated plain mood values should be counted within their tier."""
        mock_db = MagicMock()
        with patch(
            "nomarr.components.analytics.mood_analysis_comp._get_tag_edge_rows",
            side_effect=[
                [("library_files/1", "happy"), ("library_files/2", "happy")],
                [],
                [],
            ],
        ):
            result = get_mood_balance(mock_db)

        assert result == {
            "strict": [{"mood": "happy", "count": 2}],
            "regular": [],
            "loose": [],
        }

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_splits_parenthetical_compound_values(self) -> None:
        """Compound mood tuples should increment each cleaned mood separately."""
        mock_db = MagicMock()
        with patch(
            "nomarr.components.analytics.mood_analysis_comp._get_tag_edge_rows",
            side_effect=[[("library_files/1", "(happy,sad)")], [], []],
        ):
            result = get_mood_balance(mock_db)

        assert result == {
            "strict": [
                {"mood": "happy", "count": 1},
                {"mood": "sad", "count": 1},
            ],
            "regular": [],
            "loose": [],
        }


class TestGetMoodAndTierTagsForCorrelation:
    """Tests for ``get_mood_and_tier_tags_for_correlation``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_mood_rows_tier_keys_and_tier_rows(self) -> None:
        """Collects rows from the three mood relations plus discovered tier tags."""
        mock_db = MagicMock()
        with (
            patch(
                "nomarr.components.analytics.mood_analysis_comp._get_tag_edge_rows",
                side_effect=[
                    [("library_files/1", "happy")],
                    [("library_files/2", "calm")],
                    [],
                    [("library_files/1", "high")],
                    [("library_files/2", "fast")],
                ],
            ) as get_tag_edge_rows_mock,
            patch(
                "nomarr.components.analytics.mood_analysis_comp._get_tier_tag_keys",
                return_value=["nom:energy_tier", "nom:tempo_tier"],
            ) as get_tier_tag_keys_mock,
        ):
            result = get_mood_and_tier_tags_for_correlation(mock_db)

        assert result == {
            "mood_tag_rows": [
                ("library_files/1", "happy"),
                ("library_files/2", "calm"),
            ],
            "tier_tag_keys": ["nom:energy_tier", "nom:tempo_tier"],
            "tier_tag_rows": {
                "nom:energy_tier": [("library_files/1", "high")],
                "nom:tempo_tier": [("library_files/2", "fast")],
            },
        }
        get_tier_tag_keys_mock.assert_called_once_with(mock_db)
        assert get_tag_edge_rows_mock.call_count == 5


class TestGetMoodDistributionData:
    """Tests for ``get_mood_distribution_data``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_flattened_rows_for_each_mood_tier(self) -> None:
        mock_db = MagicMock()
        with patch(
            "nomarr.components.analytics.mood_analysis_comp._get_tag_edge_rows",
            side_effect=[
                [("library_files/1", "happy")],
                [("library_files/2", "calm")],
                [("library_files/3", "dreamy")],
            ],
        ) as get_tag_edge_rows_mock:
            result = get_mood_distribution_data(mock_db)

        assert result == [
            ("nom:mood-strict", "happy"),
            ("nom:mood-regular", "calm"),
            ("nom:mood-loose", "dreamy"),
        ]
        assert get_tag_edge_rows_mock.call_count == 3

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_passes_library_id_when_filtering_distribution(self) -> None:
        mock_db = MagicMock()
        with patch(
            "nomarr.components.analytics.mood_analysis_comp._get_tag_edge_rows",
            side_effect=[[], [("library_files/2", "warm")], []],
        ) as get_tag_edge_rows_mock:
            result = get_mood_distribution_data(mock_db, library_id="libraries/1")

        assert result == [("nom:mood-regular", "warm")]
        for call in get_tag_edge_rows_mock.call_args_list:
            assert call.args[2] == "libraries/1"
