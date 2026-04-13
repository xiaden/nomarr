"""Tests for ``nomarr.components.analytics.analytics_comp``."""

from __future__ import annotations

import json

import pytest

from nomarr.components.analytics.analytics_comp import (
    compute_artist_tag_profile,
    compute_dominant_vibes,
    compute_mood_distribution,
    compute_tag_co_occurrence,
    compute_tag_correlation_matrix,
    compute_tag_frequencies,
)
from nomarr.helpers.dto.analytics_dto import (
    ComputeArtistTagProfileParams,
    ComputeTagCoOccurrenceParams,
    ComputeTagCorrelationMatrixParams,
    ComputeTagFrequenciesParams,
    TagSpec,
)


@pytest.mark.unit
class TestComputeTagFrequencies:
    """Tests for ``compute_tag_frequencies``."""

    def test_passthrough_preserves_nom_tag_rows(self) -> None:
        params = ComputeTagFrequenciesParams(
            namespace_prefix="nom:",
            total_files=5,
            nom_tag_rows=[("nom:mood-strict:happy", 3), ("nom:energy_tier:high", 2)],
            artist_rows=[("Beatles", 4)],
            genre_rows=[("Rock", 5)],
            album_rows=[("Abbey Road", 2)],
        )
        result = compute_tag_frequencies(params)
        assert result.nom_tags == [("nom:mood-strict:happy", 3), ("nom:energy_tier:high", 2)]

    def test_standard_tags_organized_by_category(self) -> None:
        params = ComputeTagFrequenciesParams(
            namespace_prefix="nom:",
            total_files=10,
            nom_tag_rows=[],
            artist_rows=[("Elvis", 7)],
            genre_rows=[("Country", 4)],
            album_rows=[("Blue Hawaii", 3)],
        )
        result = compute_tag_frequencies(params)
        assert result.standard_tags["artists"] == [("Elvis", 7)]
        assert result.standard_tags["genres"] == [("Country", 4)]
        assert result.standard_tags["albums"] == [("Blue Hawaii", 3)]

    def test_total_files_preserved(self) -> None:
        params = ComputeTagFrequenciesParams(
            namespace_prefix="nom:",
            total_files=42,
            nom_tag_rows=[],
            artist_rows=[],
            genre_rows=[],
            album_rows=[],
        )
        result = compute_tag_frequencies(params)
        assert result.total_files == 42

    def test_empty_inputs_produce_empty_results(self) -> None:
        params = ComputeTagFrequenciesParams(
            namespace_prefix="nom:",
            total_files=0,
            nom_tag_rows=[],
            artist_rows=[],
            genre_rows=[],
            album_rows=[],
        )
        result = compute_tag_frequencies(params)
        assert result.nom_tags == []
        assert result.standard_tags == {"artists": [], "genres": [], "albums": []}
        assert result.total_files == 0


@pytest.mark.unit
class TestComputeMoodDistribution:
    """Tests for ``compute_mood_distribution``."""

    def test_returns_empty_tiers_for_empty_input(self) -> None:
        result = compute_mood_distribution([])
        assert result.mood_strict == {}
        assert result.mood_regular == {}
        assert result.mood_loose == {}
        assert result.top_moods == []

    def test_counts_strict_mood_values(self) -> None:
        rows = [
            ("mood-strict", json.dumps(["happy", "energetic"])),
            ("mood-strict", json.dumps(["happy"])),
        ]
        result = compute_mood_distribution(rows)
        assert result.mood_strict["happy"] == 2
        assert result.mood_strict["energetic"] == 1

    def test_distributes_across_all_three_tiers(self) -> None:
        rows = [
            ("mood-strict", json.dumps(["happy"])),
            ("mood-regular", json.dumps(["calm"])),
            ("mood-loose", json.dumps(["dreamy"])),
        ]
        result = compute_mood_distribution(rows)
        assert "happy" in result.mood_strict
        assert "calm" in result.mood_regular
        assert "dreamy" in result.mood_loose

    def test_top_moods_aggregates_across_tiers(self) -> None:
        rows = [
            ("mood-strict", json.dumps(["happy", "happy"])),
            ("mood-regular", json.dumps(["happy"])),
        ]
        result = compute_mood_distribution(rows)
        top_moods_dict = dict(result.top_moods)
        assert top_moods_dict["happy"] == 3

    def test_ignores_unknown_mood_types(self) -> None:
        rows = [("mood-unknown", json.dumps(["mystery"]))]
        result = compute_mood_distribution(rows)
        assert result.mood_strict == {}
        assert result.mood_regular == {}
        assert result.mood_loose == {}

    def test_handles_malformed_json_gracefully(self) -> None:
        rows = [("mood-strict", "not valid json")]
        result = compute_mood_distribution(rows)
        assert result.mood_strict == {}


@pytest.mark.unit
class TestComputeTagCorrelationMatrix:
    """Tests for ``compute_tag_correlation_matrix``."""

    def test_returns_empty_when_no_mood_rows(self) -> None:
        params = ComputeTagCorrelationMatrixParams(
            namespace="nom:",
            top_n=10,
            mood_tag_rows=[],
            tier_tag_keys=[],
            tier_tag_rows={},
        )
        result = compute_tag_correlation_matrix(params)
        assert result.mood_correlations == {}
        assert result.mood_tier_correlations == {}

    def test_two_moods_compute_mutual_correlation(self) -> None:
        # file_id=1 has "happy", file_id=2 has both "happy" and "calm"
        params = ComputeTagCorrelationMatrixParams(
            namespace="nom:",
            top_n=10,
            mood_tag_rows=[
                (1, json.dumps(["happy"])),
                (2, json.dumps(["happy", "calm"])),
                (3, json.dumps(["calm"])),
            ],
            tier_tag_keys=[],
            tier_tag_rows={},
        )
        result = compute_tag_correlation_matrix(params)
        # happy appears in files 1,2 (2 files); calm appears in files 2,3 (2 files)
        # happy->calm: intersection(1,2)&(2,3)={2} = 1 / 2 = 0.5
        assert "happy" in result.mood_correlations
        assert result.mood_correlations["happy"]["calm"] == 0.5

    def test_respects_top_n_limit(self) -> None:
        rows = [(i, json.dumps([f"mood_{i}"])) for i in range(20)]
        params = ComputeTagCorrelationMatrixParams(
            namespace="nom:",
            top_n=5,
            mood_tag_rows=rows,
            tier_tag_keys=[],
            tier_tag_rows={},
        )
        result = compute_tag_correlation_matrix(params)
        assert len(result.mood_correlations) <= 5

    def test_handles_malformed_json_rows_gracefully(self) -> None:
        params = ComputeTagCorrelationMatrixParams(
            namespace="nom:",
            top_n=10,
            mood_tag_rows=[(1, "bad json"), (2, json.dumps(["happy"]))],
            tier_tag_keys=[],
            tier_tag_rows={},
        )
        result = compute_tag_correlation_matrix(params)
        # Should not raise; just skip malformed rows
        assert isinstance(result.mood_correlations, dict)


@pytest.mark.unit
class TestComputeArtistTagProfile:
    """Tests for ``compute_artist_tag_profile``."""

    def test_returns_empty_profile_when_file_count_is_zero(self) -> None:
        params = ComputeArtistTagProfileParams(
            artist="The Beatles",
            file_count=0,
            namespace_prefix="nom:",
            tag_rows=[],
            limit=10,
        )
        result = compute_artist_tag_profile(params)
        assert result.artist == "The Beatles"
        assert result.file_count == 0
        assert result.top_tags == []
        assert result.moods == []
        assert result.avg_tags_per_file == 0.0

    def test_counts_tags_and_computes_averages(self) -> None:
        params = ComputeArtistTagProfileParams(
            artist="Bowie",
            file_count=2,
            namespace_prefix="nom:",
            tag_rows=[
                ("nom:energy_tier", json.dumps(["high"])),
                ("nom:energy_tier", json.dumps(["medium"])),
                ("nom:bpm", json.dumps([120.0])),
            ],
            limit=10,
        )
        result = compute_artist_tag_profile(params)
        assert result.file_count == 2
        tag_names = [t[0] for t in result.top_tags]
        assert "energy_tier" in tag_names
        assert "bpm" in tag_names

    def test_separates_mood_tags_from_regular_tags(self) -> None:
        params = ComputeArtistTagProfileParams(
            artist="Imagine Dragons",
            file_count=1,
            namespace_prefix="nom:",
            tag_rows=[
                ("nom:mood-strict", json.dumps(["energetic", "fierce"])),
                ("nom:energy_tier", json.dumps(["high"])),
            ],
            limit=10,
        )
        result = compute_artist_tag_profile(params)
        mood_names = [m[0] for m in result.moods]
        assert "energetic" in mood_names
        assert "fierce" in mood_names
        tag_names = [t[0] for t in result.top_tags]
        assert "mood-strict" not in tag_names

    def test_avg_tags_per_file_calculated_correctly(self) -> None:
        params = ComputeArtistTagProfileParams(
            artist="Artist",
            file_count=4,
            namespace_prefix="nom:",
            tag_rows=[
                ("nom:energy_tier", json.dumps(["high"])),
                ("nom:energy_tier", json.dumps(["low"])),
            ],
            limit=10,
        )
        result = compute_artist_tag_profile(params)
        # 2 non-mood tag occurrences over 4 files
        assert result.avg_tags_per_file == 0.5


@pytest.mark.unit
class TestComputeTagCoOccurrence:
    """Tests for ``compute_tag_co_occurrence``."""

    def test_empty_tags_produce_empty_matrix(self) -> None:
        params = ComputeTagCoOccurrenceParams(x_tags=[], y_tags=[], tag_data={})
        result = compute_tag_co_occurrence(params)
        assert result.matrix == []
        assert result.x_tags == []
        assert result.y_tags == []

    def test_intersection_count_in_matrix(self) -> None:
        x_tags = [TagSpec(key="mood-strict", value="happy")]
        y_tags = [TagSpec(key="mood-strict", value="calm")]
        tag_data = {
            ("mood-strict", "happy"): {"file_1", "file_2", "file_3"},
            ("mood-strict", "calm"): {"file_2", "file_3", "file_4"},
        }
        params = ComputeTagCoOccurrenceParams(x_tags=x_tags, y_tags=y_tags, tag_data=tag_data)
        result = compute_tag_co_occurrence(params)
        # matrix[0][0] = intersection of calm&happy = {file_2, file_3} = 2
        assert result.matrix[0][0] == 2

    def test_zero_intersection_when_no_shared_files(self) -> None:
        x_tags = [TagSpec(key="genre", value="rock")]
        y_tags = [TagSpec(key="genre", value="jazz")]
        tag_data = {
            ("genre", "rock"): {"file_1", "file_2"},
            ("genre", "jazz"): {"file_3", "file_4"},
        }
        params = ComputeTagCoOccurrenceParams(x_tags=x_tags, y_tags=y_tags, tag_data=tag_data)
        result = compute_tag_co_occurrence(params)
        assert result.matrix[0][0] == 0

    def test_missing_tag_in_data_treated_as_empty_set(self) -> None:
        x_tags = [TagSpec(key="genre", value="country")]
        y_tags = [TagSpec(key="mood-strict", value="happy")]
        tag_data: dict[tuple[str, str], set[str]] = {}  # no entries
        params = ComputeTagCoOccurrenceParams(x_tags=x_tags, y_tags=y_tags, tag_data=tag_data)
        result = compute_tag_co_occurrence(params)
        assert result.matrix[0][0] == 0


@pytest.mark.unit
class TestComputeDominantVibes:
    """Tests for ``compute_dominant_vibes``."""

    def test_returns_empty_for_empty_balance(self) -> None:
        result = compute_dominant_vibes({})
        assert result == []

    def test_returns_empty_when_all_tiers_empty(self) -> None:
        result = compute_dominant_vibes({"strict": [], "regular": [], "loose": []})
        assert result == []

    def test_returns_top_5_moods(self) -> None:
        balance = {
            "strict": [
                {"mood": "a", "count": 10},
                {"mood": "b", "count": 8},
                {"mood": "c", "count": 6},
                {"mood": "d", "count": 4},
                {"mood": "e", "count": 2},
                {"mood": "f", "count": 1},
            ]
        }
        result = compute_dominant_vibes(balance)
        assert len(result) == 5
        assert result[0]["mood"] == "a"

    def test_aggregates_counts_across_tiers(self) -> None:
        balance = {
            "strict": [{"mood": "happy", "count": 3}],
            "regular": [{"mood": "happy", "count": 5}],
            "loose": [{"mood": "happy", "count": 2}],
        }
        result = compute_dominant_vibes(balance)
        assert len(result) == 1
        assert result[0]["mood"] == "happy"
        # total = 10, percentage = 100%
        assert result[0]["percentage"] == 100.0

    def test_percentage_sums_correctly(self) -> None:
        balance = {
            "strict": [
                {"mood": "happy", "count": 7},
                {"mood": "sad", "count": 3},
            ]
        }
        result = compute_dominant_vibes(balance)
        assert len(result) == 2
        percentages = [r["percentage"] for r in result]
        assert abs(sum(percentages) - 100.0) < 0.1

    def test_sorts_by_frequency_descending(self) -> None:
        balance = {
            "strict": [
                {"mood": "calm", "count": 2},
                {"mood": "energetic", "count": 8},
                {"mood": "happy", "count": 5},
            ]
        }
        result = compute_dominant_vibes(balance)
        assert result[0]["mood"] == "energetic"
        assert result[1]["mood"] == "happy"
        assert result[2]["mood"] == "calm"
