"""Unit tests for nomarr.helpers.dto.analytics_dto module.

Tests analytics-related DTOs for proper structure and behavior.
"""

import pytest

from nomarr.helpers.dto.analytics_dto import (
    ArtistTagProfile,
    ComputeArtistTagProfileParams,
    ComputeTagCoOccurrenceParams,
    ComputeTagCorrelationMatrixParams,
    ComputeTagFrequenciesParams,
    ComputeTagFrequenciesResult,
    MoodDistributionData,
    MoodDistributionItem,
    MoodDistributionResult,
    TagCoOccurrenceData,
    TagCorrelationData,
    TagFrequenciesResult,
    TagFrequencyItem,
    TagSpec,
)


class TestTagSpec:
    """Tests for TagSpec dataclass."""

    @pytest.mark.unit
    def test_can_create_tag_spec(self) -> None:
        """Should create a tag specification."""
        spec = TagSpec(key="mood-strict", value="happy")
        assert spec.key == "mood-strict"
        assert spec.value == "happy"

    @pytest.mark.unit
    def test_tag_spec_for_genre(self) -> None:
        """Should work for genre tags."""
        spec = TagSpec(key="genre", value="rock")
        assert spec.key == "genre"
        assert spec.value == "rock"


class TestTagCorrelationData:
    """Tests for TagCorrelationData dataclass."""

    @pytest.mark.unit
    def test_can_create_empty_correlation(self) -> None:
        """Should create empty correlation data."""
        data = TagCorrelationData(
            mood_correlations={},
            mood_tier_correlations={},
        )
        assert data.mood_correlations == {}
        assert data.mood_tier_correlations == {}

    @pytest.mark.unit
    def test_can_create_with_correlations(self) -> None:
        """Should create correlation data with values."""
        data = TagCorrelationData(
            mood_correlations={
                "happy": {"energetic": 0.8, "calm": -0.5},
                "sad": {"calm": 0.6},
            },
            mood_tier_correlations={
                "happy": {"genre": 0.3},
            },
        )
        assert data.mood_correlations["happy"]["energetic"] == 0.8
        assert data.mood_tier_correlations["happy"]["genre"] == 0.3


class TestMoodDistributionData:
    """Tests for MoodDistributionData dataclass."""

    @pytest.mark.unit
    def test_can_create_mood_distribution(self) -> None:
        """Should create mood distribution data."""
        data = MoodDistributionData(
            mood_strict={"happy": 50, "sad": 30},
            mood_regular={"happy": 100, "sad": 80},
            mood_loose={"happy": 200, "sad": 180},
            top_moods=[("happy", 200), ("sad", 180)],
        )
        assert data.mood_strict["happy"] == 50
        assert data.top_moods[0] == ("happy", 200)

    @pytest.mark.unit
    def test_tier_counts_increase(self) -> None:
        """Loose tier should have >= regular >= strict counts."""
        data = MoodDistributionData(
            mood_strict={"happy": 10},
            mood_regular={"happy": 50},
            mood_loose={"happy": 100},
            top_moods=[("happy", 100)],
        )
        # Each broader tier should include the stricter tier's matches
        assert data.mood_loose["happy"] >= data.mood_regular["happy"]
        assert data.mood_regular["happy"] >= data.mood_strict["happy"]


class TestArtistTagProfile:
    """Tests for ArtistTagProfile dataclass."""

    @pytest.mark.unit
    def test_can_create_artist_profile(self) -> None:
        """Should create artist tag profile."""
        profile = ArtistTagProfile(
            artist="The Beatles",
            file_count=200,
            top_tags=[("rock", 180, 0.9), ("pop", 150, 0.75)],
            moods=[("happy", 100), ("energetic", 80)],
            avg_tags_per_file=5.5,
        )
        assert profile.artist == "The Beatles"
        assert profile.file_count == 200
        assert profile.avg_tags_per_file == 5.5

    @pytest.mark.unit
    def test_top_tags_structure(self) -> None:
        """Top tags should contain (tag, count, avg_value) tuples."""
        profile = ArtistTagProfile(
            artist="Artist",
            file_count=10,
            top_tags=[("rock", 8, 0.85)],
            moods=[],
            avg_tags_per_file=1.0,
        )
        tag_name, count, avg_value = profile.top_tags[0]
        assert tag_name == "rock"
        assert count == 8
        assert avg_value == 0.85


class TestTagCoOccurrenceData:
    """Tests for TagCoOccurrenceData dataclass."""

    @pytest.mark.unit
    def test_can_create_empty_co_occurrence(self) -> None:
        """Should create empty co-occurrence data."""
        data = TagCoOccurrenceData(
            x_tags=[],
            y_tags=[],
            matrix=[],
        )
        assert data.x_tags == []
        assert data.matrix == []

    @pytest.mark.unit
    def test_matrix_dimensions_match_tags(self) -> None:
        """Matrix dimensions should match tag lists."""
        x_tags = [TagSpec(key="genre", value="rock"), TagSpec(key="genre", value="pop")]
        y_tags = [TagSpec(key="mood", value="happy")]
        matrix = [[10, 5]]  # 1 y_tag x 2 x_tags

        data = TagCoOccurrenceData(x_tags=x_tags, y_tags=y_tags, matrix=matrix)

        assert len(data.matrix) == len(y_tags)
        assert len(data.matrix[0]) == len(x_tags)


class TestComputeTagCorrelationMatrixParams:
    """Tests for ComputeTagCorrelationMatrixParams dataclass."""

    @pytest.mark.unit
    def test_can_create_params(self) -> None:
        """Should create correlation params."""
        params = ComputeTagCorrelationMatrixParams(
            namespace="nom-music",
            top_n=10,
            mood_tag_rows=[(1, '["happy", "energetic"]')],
            tier_tag_keys=["mood-strict", "mood-regular"],
            tier_tag_rows={"mood-strict": [(1, '["happy"]')]},
        )
        assert params.namespace == "nom-music"
        assert params.top_n == 10


class TestComputeTagFrequenciesParams:
    """Tests for ComputeTagFrequenciesParams dataclass."""

    @pytest.mark.unit
    def test_can_create_params(self) -> None:
        """Should create frequency params."""
        params = ComputeTagFrequenciesParams(
            namespace_prefix="nom-music:",
            total_files=1000,
            nom_tag_rows=[("rock", 500), ("pop", 300)],
            artist_rows=[("Beatles", 50)],
            genre_rows=[("Rock", 500)],
            album_rows=[("Abbey Road", 12)],
        )
        assert params.total_files == 1000
        assert len(params.nom_tag_rows) == 2


class TestComputeArtistTagProfileParams:
    """Tests for ComputeArtistTagProfileParams dataclass."""

    @pytest.mark.unit
    def test_can_create_params(self) -> None:
        """Should create artist profile params."""
        params = ComputeArtistTagProfileParams(
            artist="The Beatles",
            file_count=200,
            namespace_prefix="nom-music:",
            tag_rows=[("mood-strict", '["happy"]')],
            limit=10,
        )
        assert params.artist == "The Beatles"
        assert params.limit == 10


class TestComputeTagCoOccurrenceParams:
    """Tests for ComputeTagCoOccurrenceParams dataclass."""

    @pytest.mark.unit
    def test_can_create_params(self) -> None:
        """Should create co-occurrence params."""
        params = ComputeTagCoOccurrenceParams(
            x_tags=[TagSpec(key="genre", value="rock")],
            y_tags=[TagSpec(key="mood", value="happy")],
            tag_data={("genre", "rock"): {"files/1", "files/2"}},
        )
        assert len(params.x_tags) == 1
        assert ("genre", "rock") in params.tag_data


class TestComputeTagFrequenciesResult:
    """Tests for ComputeTagFrequenciesResult dataclass."""

    @pytest.mark.unit
    def test_can_create_result(self) -> None:
        """Should create frequencies result."""
        result = ComputeTagFrequenciesResult(
            nom_tags=[("rock", 500), ("pop", 300)],
            standard_tags={"genre": [("Rock", 500)], "artist": [("Beatles", 50)]},
            total_files=1000,
        )
        assert result.total_files == 1000
        assert len(result.nom_tags) == 2


class TestTagFrequencyItem:
    """Tests for TagFrequencyItem dataclass."""

    @pytest.mark.unit
    def test_can_create_item(self) -> None:
        """Should create frequency item."""
        item = TagFrequencyItem(
            tag_key="mood-strict",
            total_count=500,
            unique_values=10,
        )
        assert item.tag_key == "mood-strict"
        assert item.total_count == 500


class TestMoodDistributionItem:
    """Tests for MoodDistributionItem dataclass."""

    @pytest.mark.unit
    def test_can_create_item(self) -> None:
        """Should create distribution item."""
        item = MoodDistributionItem(
            mood="happy",
            count=100,
            percentage=25.5,
        )
        assert item.mood == "happy"
        assert item.percentage == 25.5


class TestTagFrequenciesResult:
    """Tests for TagFrequenciesResult dataclass."""

    @pytest.mark.unit
    def test_can_create_result(self) -> None:
        """Should create wrapper result."""
        item = TagFrequencyItem(tag_key="mood", total_count=100, unique_values=5)
        result = TagFrequenciesResult(tag_frequencies=[item])
        assert len(result.tag_frequencies) == 1


class TestMoodDistributionResult:
    """Tests for MoodDistributionResult dataclass."""

    @pytest.mark.unit
    def test_can_create_result(self) -> None:
        """Should create wrapper result."""
        item = MoodDistributionItem(mood="happy", count=50, percentage=50.0)
        result = MoodDistributionResult(mood_distribution=[item])
        assert len(result.mood_distribution) == 1
