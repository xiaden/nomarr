"""Unit tests for MlDb facade vector index management methods."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.persistence.api.ml import MlDb


def _make_ml_db() -> MlDb:
    """Build an MlDb with mocked repos for unit testing."""
    mock_vector_repo = MagicMock()
    mock_model_repo = MagicMock()
    mock_calibration_repo = MagicMock()
    return MlDb(
        session=MagicMock(),
        vector_repo=mock_vector_repo,
        model_repo=mock_model_repo,
        calibration_repo=mock_calibration_repo,
        ml_inference_repo=MagicMock(),
    )


@pytest.mark.unit
@pytest.mark.mocked
class TestMlDbVectorIndexMethods:
    """Tests for MlDb vector index management methods added in Phase 3."""

    def test_has_vector_index_returns_true_when_index_exists(self) -> None:
        """has_vector_index should return True when pg_indexes has the index."""
        ml_db = _make_ml_db()
        ml_db._vector_repo.has_cold_hnsw_index.return_value = True

        result = ml_db.has_vector_index("ast")

        assert result is True
        ml_db._vector_repo.has_cold_hnsw_index.assert_called_once_with()

    def test_has_vector_index_returns_false_when_index_missing(self) -> None:
        """has_vector_index should return False when pg_indexes lacks the index."""
        ml_db = _make_ml_db()
        ml_db._vector_repo.has_cold_hnsw_index.return_value = False

        result = ml_db.has_vector_index("ast")

        assert result is False

    def test_build_vector_index_is_noop(self) -> None:
        """build_vector_index should be a no-op (logs message, no SQL executed)."""
        ml_db = _make_ml_db()
        ml_db.build_vector_index(1280)

    def test_drop_vector_index_is_noop(self) -> None:
        """drop_vector_index should be a no-op (logs message, no SQL executed)."""
        ml_db = _make_ml_db()
        ml_db.drop_vector_index()

    def test_rebuild_vector_index_executes_reindex_sql(self) -> None:
        """rebuild_vector_index should execute REINDEX INDEX CONCURRENTLY SQL."""
        ml_db = _make_ml_db()
        ml_db.rebuild_vector_index(1280)
        ml_db._vector_repo.rebuild_cold_hnsw_index.assert_called_once_with()

    def test_backfill_genres_returns_updated_count(self) -> None:
        """backfill_genres should return the number of updated embeddings."""
        ml_db = _make_ml_db()
        ml_db._vector_repo.backfill_genres.return_value = 42

        count = ml_db.backfill_genres("ast")

        assert count == 42
        ml_db._vector_repo.backfill_genres.assert_called_once_with("ast")

    def test_backfill_genres_returns_zero_when_no_null_genres(self) -> None:
        """backfill_genres should return 0 when all embeddings have genres."""
        ml_db = _make_ml_db()
        ml_db._vector_repo.backfill_genres.return_value = 0

        count = ml_db.backfill_genres("ast")

        assert count == 0


@pytest.mark.unit
def test_facade_aggregate_intent_without_transaction_api() -> None:
    """MlDb exposes the single aggregate intent and no facade transaction API."""
    ml_db = _make_ml_db()

    assert hasattr(ml_db, "replace_song_inference_results")
    assert not hasattr(ml_db, "replace_output_streams_for_song")
    assert not hasattr(ml_db, "replace_song_vectors")
    assert not hasattr(ml_db, "transaction")
    assert not hasattr(ml_db, "_require_transaction")
