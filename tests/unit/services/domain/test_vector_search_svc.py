"""Tests for ``nomarr.services.domain.vector_search_svc``.

Covers the error contract of ``VectorSearchService.search_similar_tracks``:
- ``VectorIndexUnavailableError`` when the cold vector index is unavailable,
  and that this check runs before the seed-vector lookup.
- ``MissingSeedVectorError`` when the source track has no stored vector.
- Successful search, min_score filtering, and propagation of the seed vector.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.services.domain.vector_search_svc import (
    MissingSeedVectorError,
    VectorIndexUnavailableError,
    VectorSearchService,
)

# Module path where the retrieve-component functions are imported into the service.
_MODULE = "nomarr.services.domain.vector_search_svc"


def _make_service(db: MagicMock | None = None) -> VectorSearchService:
    """Build a minimal VectorSearchService for tests."""
    return VectorSearchService(
        db=db or MagicMock(),
        config_svc=MagicMock(),
    )


class TestSearchSimilarTracksIndexCheck:
    """Tests for the cold index availability guard."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_raises_when_index_unavailable(self) -> None:
        """An unavailable cold index should raise VectorIndexUnavailableError."""
        mock_db = MagicMock()
        mock_db.ml.has_vector_index.return_value = False
        service = _make_service(mock_db)

        with pytest.raises(VectorIndexUnavailableError, match="No vector index available"):
            service.search_similar_tracks(file_id=1, backbone_id="effnet", limit=10)

        mock_db.ml.has_vector_index.assert_called_once_with("effnet")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_index_check_runs_before_seed_lookup(self) -> None:
        """Index check should short-circuit before the seed vector lookup."""
        mock_db = MagicMock()
        mock_db.ml.has_vector_index.return_value = False
        service = _make_service(mock_db)

        with (
            patch(f"{_MODULE}.get_cold_track_vector") as mock_get_cold_track_vector,
            pytest.raises(VectorIndexUnavailableError),
        ):
            service.search_similar_tracks(file_id=1, backbone_id="effnet", limit=10)

        mock_get_cold_track_vector.assert_not_called()


class TestSearchSimilarTracksMissingSeed:
    """Tests for the seed-vector lookup guard."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_raises_when_seed_vector_absent(self) -> None:
        """A track with no stored vector should raise MissingSeedVectorError."""
        mock_db = MagicMock()
        mock_db.ml.has_vector_index.return_value = True
        service = _make_service(mock_db)

        with (
            patch(f"{_MODULE}.get_cold_track_vector", return_value=None) as mock_get_cold_track_vector,
            patch(f"{_MODULE}.search_similar_cold_track_vectors") as mock_search,
            pytest.raises(MissingSeedVectorError, match="No vector found for file '1'"),
        ):
            service.search_similar_tracks(file_id=1, backbone_id="effnet", limit=10)

        mock_get_cold_track_vector.assert_called_once_with(mock_db, 1, "effnet")
        mock_search.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_does_not_search_when_seed_vector_absent(self) -> None:
        """ANN search should not run when the seed vector is missing."""
        mock_db = MagicMock()
        mock_db.ml.has_vector_index.return_value = True
        service = _make_service(mock_db)

        with (
            patch(f"{_MODULE}.get_cold_track_vector", return_value=None),
            patch(f"{_MODULE}.search_similar_cold_track_vectors") as mock_search,
            pytest.raises(MissingSeedVectorError),
        ):
            service.search_similar_tracks(file_id=42, backbone_id="yamnet", limit=5)

        mock_search.assert_not_called()


class TestSearchSimilarTracksSuccess:
    """Tests for the successful ANN search path."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_searches_with_seed_vector_and_filters_by_min_score(self) -> None:
        """Results below min_score should be filtered out."""
        mock_db = MagicMock()
        mock_db.ml.has_vector_index.return_value = True
        service = _make_service(mock_db)

        seed_vector = [0.1, 0.2, 0.3]
        # Deliberately NOT pre-sorted by score so the final exact-list assertion
        # pins the service's descending sort (0.9 before 0.7).
        raw_results = [
            {"file_id": 3, "score": 0.7, "vector": [0.7, 0.3]},
            {"file_id": 1, "score": 0.9, "vector": [0.9, 0.1]},
            {"file_id": 2, "score": 0.4, "vector": [0.4, 0.6]},
        ]

        with (
            patch(
                f"{_MODULE}.get_cold_track_vector",
                return_value={"vector_n": seed_vector},
            ),
            patch(
                f"{_MODULE}.search_similar_cold_track_vectors",
                return_value=raw_results,
            ) as mock_search,
        ):
            result = service.search_similar_tracks(
                file_id=7,
                backbone_id="effnet",
                limit=10,
                min_score=0.6,
            )

        assert result == [
            {"file_id": 1, "score": 0.9, "vector": [0.9, 0.1]},
            {"file_id": 3, "score": 0.7, "vector": [0.7, 0.3]},
        ]
        mock_search.assert_called_once_with(
            db=mock_db,
            backbone_id="effnet",
            seed_vector=seed_vector,
            result_limit=10,
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_default_min_score_retains_zero_similarity(self) -> None:
        mock_db = MagicMock()
        mock_db.ml.has_vector_index.return_value = True
        service = _make_service(mock_db)
        raw_results = [
            {"file_id": 1, "score": 0.0, "vector": [0.0]},
            {"file_id": 2, "score": -0.1, "vector": [0.1]},
        ]

        with (
            patch(f"{_MODULE}.get_cold_track_vector", return_value={"vector_n": [0.0]}),
            patch(f"{_MODULE}.search_similar_cold_track_vectors", return_value=raw_results),
        ):
            result = service.search_similar_tracks(file_id=7, backbone_id="effnet", limit=10)

        assert result == [{"file_id": 1, "score": 0.0, "vector": [0.0]}]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_when_all_results_below_min_score(self) -> None:
        """An empty result list is acceptable when every result is filtered out."""
        mock_db = MagicMock()
        mock_db.ml.has_vector_index.return_value = True
        service = _make_service(mock_db)

        raw_results = [{"file_id": 1, "score": 0.1, "vector": [0.1, 0.1]}]

        with (
            patch(f"{_MODULE}.get_cold_track_vector", return_value={"vector_n": [0.0, 0.0]}),
            patch(f"{_MODULE}.search_similar_cold_track_vectors", return_value=raw_results),
        ):
            result = service.search_similar_tracks(
                file_id=7,
                backbone_id="effnet",
                limit=10,
                min_score=0.9,
            )

        assert result == []
