"""Unit tests for MlDb facade vector index management methods."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.persistence.api.ml import MlDb


def _make_ml_db() -> MlDb:
    """Build an MlDb with mocked repos for unit testing."""
    mock_vector_repo = MagicMock()
    mock_vector_repo._session = MagicMock()
    mock_model_repo = MagicMock()
    mock_calibration_repo = MagicMock()
    return MlDb(
        session=MagicMock(),
        vector_repo=mock_vector_repo,
        model_repo=mock_model_repo,
        calibration_repo=mock_calibration_repo,
    )


@pytest.mark.unit
@pytest.mark.mocked
class TestMlDbVectorIndexMethods:
    """Tests for MlDb vector index management methods added in Phase 3."""

    def test_has_vector_index_returns_true_when_index_exists(self) -> None:
        """has_vector_index should return True when pg_indexes has the index."""
        ml_db = _make_ml_db()
        mock_result = MagicMock()
        mock_result.scalar.return_value = True
        ml_db._vector_repo._session.execute = MagicMock(return_value=mock_result)

        result = ml_db.has_vector_index("ast")

        assert result is True
        ml_db._vector_repo._session.execute.assert_called_once()

    def test_has_vector_index_returns_false_when_index_missing(self) -> None:
        """has_vector_index should return False when pg_indexes lacks the index."""
        ml_db = _make_ml_db()
        mock_result = MagicMock()
        mock_result.scalar.return_value = False
        ml_db._vector_repo._session.execute = MagicMock(return_value=mock_result)

        result = ml_db.has_vector_index("ast")

        assert result is False

    def test_build_vector_index_is_noop(self) -> None:
        """build_vector_index should be a no-op (logs message, no SQL executed)."""
        ml_db = _make_ml_db()
        ml_db._vector_repo._session.execute = MagicMock()

        ml_db.build_vector_index(1280)

        # No SQL should be executed — build_vector_index just logs
        ml_db._vector_repo._session.execute.assert_not_called()

    def test_drop_vector_index_is_noop(self) -> None:
        """drop_vector_index should be a no-op (logs message, no SQL executed)."""
        ml_db = _make_ml_db()
        ml_db._vector_repo._session.execute = MagicMock()

        ml_db.drop_vector_index()

        # No SQL should be executed — drop_vector_index just logs
        ml_db._vector_repo._session.execute.assert_not_called()

    def test_rebuild_vector_index_executes_reindex_sql(self) -> None:
        """rebuild_vector_index should execute REINDEX INDEX CONCURRENTLY SQL."""
        ml_db = _make_ml_db()
        mock_result = MagicMock()
        ml_db._vector_repo._session.execute = MagicMock(return_value=mock_result)

        ml_db.rebuild_vector_index(1280)

        ml_db._vector_repo._session.execute.assert_called_once()
        # Verify the SQL contains REINDEX
        call_args = ml_db._vector_repo._session.execute.call_args
        sql_text = str(call_args.args[0])
        assert "REINDEX" in sql_text.upper()

    def test_backfill_genres_returns_count(self) -> None:
        """backfill_genres should return the count of embeddings with NULL genres."""
        ml_db = _make_ml_db()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 42
        ml_db._vector_repo._session.execute = MagicMock(return_value=mock_result)

        count = ml_db.backfill_genres("ast")

        assert count == 42
        ml_db._vector_repo._session.execute.assert_called_once()
        # Verify the SQL contains SELECT COUNT and backbone_id parameter
        call_args = ml_db._vector_repo._session.execute.call_args
        sql_text = str(call_args.args[0])
        assert "COUNT" in sql_text.upper()
        params = call_args.args[1]
        assert params["backbone_id"] == "ast"

    def test_backfill_genres_returns_zero_when_no_null_genres(self) -> None:
        """backfill_genres should return 0 when all embeddings have genres."""
        ml_db = _make_ml_db()
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        ml_db._vector_repo._session.execute = MagicMock(return_value=mock_result)

        count = ml_db.backfill_genres("ast")

        assert count == 0
