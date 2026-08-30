"""Tests for ``nomarr.components.analytics.mood_analysis_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.analytics.mood_analysis_comp import (
    _get_tag_edge_rows,
    get_mood_and_tier_tags_for_correlation,
    get_mood_balance,
    get_mood_coverage,
    get_mood_distribution_data,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_tag_dataclass import TagRef


def _song(song_id: int, **overrides: object) -> Song:
    base: dict = {
        "song_id": song_id,
        "library_id": 1,
        "folder_id": None,
        "path": f"/music/{song_id}.mp3",
        "normalized_path": f"{song_id}.mp3",
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


def _identity(name: str, value: str | int | float | bool) -> TagRef:
    """Build a domain ``TagRef`` for the sealed tag facade."""
    return TagRef(name=name, value=value)


class TestGetMoodCoverage:
    """Tests for ``get_mood_coverage``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_coverage_when_no_files(self) -> None:
        """Zero files should produce zero coverage for every tier."""
        mock_db = MagicMock()

        with patch(
            "nomarr.components.analytics.mood_analysis_comp.get_library_stats",
            return_value={"total_files": 0},
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
        mock_db.library.list_tags.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_percentage_for_each_tier(self) -> None:
        """Tier counts should be converted into rounded percentages."""
        mock_db = MagicMock()
        with (
            patch(
                "nomarr.components.analytics.mood_analysis_comp._get_tag_edge_rows",
                side_effect=[
                    [(1, "happy"), (2, "calm"), (1, "happy")],
                    [(3, "warm"), (4, "bright"), (3, "warm")],
                    [(5, "dreamy")],
                ],
            ) as get_tag_edge_rows_mock,
            patch(
                "nomarr.components.analytics.mood_analysis_comp.get_library_stats",
                return_value={"total_files": 10},
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
                [(1, "happy"), (2, "happy")],
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
            side_effect=[[(1, "(happy,sad)")], [], []],
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
                    [(1, "happy")],
                    [(2, "calm")],
                    [],
                    [(1, "high")],
                    [(2, "fast")],
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
                (1, "happy"),
                (2, "calm"),
            ],
            "tier_tag_keys": ["nom:energy_tier", "nom:tempo_tier"],
            "tier_tag_rows": {
                "nom:energy_tier": [(1, "high")],
                "nom:tempo_tier": [(2, "fast")],
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
                [(1, "happy")],
                [(2, "calm")],
                [(3, "dreamy")],
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
    def test_passes_library_when_filtering_distribution(self) -> None:
        """The natural ``Library`` scope is forwarded to the edge-row query."""
        mock_db = MagicMock()
        library = Library(name="main", root_path="/music")
        with patch(
            "nomarr.components.analytics.mood_analysis_comp._get_tag_edge_rows",
            side_effect=[[], [(2, "warm")], []],
        ) as get_tag_edge_rows_mock:
            result = get_mood_distribution_data(mock_db, library=library)

        assert result == [("nom:mood-regular", "warm")]
        for call in get_tag_edge_rows_mock.call_args_list:
            assert call.args[2] == library


class TestGetTagEdgeRows:
    """Tests for ``_get_tag_edge_rows``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_resolves_identities_and_searches_songs_per_value(self) -> None:
        mock_db = MagicMock()
        mock_db.library.list_tags.side_effect = [
            [
                _identity("nom:mood-strict", "happy"),
                _identity("nom:mood-strict", "calm"),
            ],
            [],
        ]

        def find_songs_side_effect(identity: TagRef, *, limit: int | None) -> tuple[Song, ...]:
            assert limit is None
            return {"happy": (_song(1),), "calm": (_song(2),)}[str(identity.value)]

        mock_db.library.find_songs_with_tag.side_effect = find_songs_side_effect

        result = _get_tag_edge_rows(mock_db, "nom:mood-strict")

        assert result == [
            (1, "happy"),
            (2, "calm"),
        ]
        mock_db.library.list_tags.assert_any_call(name="nom:mood-strict", limit=1000, offset=0)
        mock_db.library.find_songs_with_tag.assert_any_call(_identity("nom:mood-strict", "happy"), limit=None)
        mock_db.library.find_songs_with_tag.assert_any_call(_identity("nom:mood-strict", "calm"), limit=None)
        assert mock_db.library.find_songs_with_tag.call_count == 2
