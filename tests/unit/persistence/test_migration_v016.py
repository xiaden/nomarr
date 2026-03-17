"""Unit tests for V016_add_file_state_edges migration.

Verifies idempotency: upgrade() handles both fresh-DB and already-exists scenarios
without errors.
"""

from unittest.mock import MagicMock

import pytest

from nomarr.migrations.V016_add_file_state_edges import _STATE_KEYS, upgrade


@pytest.fixture
def mock_db():
    """Provide mock ArangoDB that simulates a fresh database."""
    db = MagicMock()
    db.name = "test_db"
    db.has_collection.return_value = False
    # Mock collection objects
    states_coll = MagicMock()
    edge_coll = MagicMock()
    db.collection.side_effect = lambda name: states_coll if name == "file_states" else edge_coll
    # Mock AQL cursor for population queries
    db.aql.execute.return_value = iter([0])
    return db


class TestMigrationFreshDB:
    """Test upgrade() on a fresh database with no existing collections."""

    @pytest.mark.unit
    def test_creates_file_states_collection(self, mock_db):
        """file_states vertex collection is created when absent."""
        upgrade(mock_db)
        mock_db.create_collection.assert_any_call("file_states")

    @pytest.mark.unit
    def test_creates_file_has_state_edge_collection(self, mock_db):
        """file_has_state edge collection is created when absent."""
        upgrade(mock_db)
        mock_db.create_collection.assert_any_call("file_has_state", edge=True)

    @pytest.mark.unit
    def test_inserts_all_state_vertices(self, mock_db):
        """All three state documents (ml_tagged, calibrated, reconciled) are inserted."""
        upgrade(mock_db)
        coll = mock_db.collection("file_states")
        inserted_keys = [c.args[0]["_key"] for c in coll.insert.call_args_list]
        assert set(inserted_keys) == set(_STATE_KEYS)

    @pytest.mark.unit
    def test_creates_unique_from_to_index(self, mock_db):
        """Unique persistent index on (_from, _to) is created."""
        upgrade(mock_db)
        edge_coll = mock_db.collection("file_has_state")
        index_calls = edge_coll.add_persistent_index.call_args_list
        unique_call = [c for c in index_calls if c.kwargs.get("unique") is True]
        assert len(unique_call) == 1
        assert unique_call[0].kwargs["fields"] == ["_from", "_to"]

    @pytest.mark.unit
    def test_creates_to_lookup_index(self, mock_db):
        """Non-unique persistent index on _to is created."""
        upgrade(mock_db)
        edge_coll = mock_db.collection("file_has_state")
        index_calls = edge_coll.add_persistent_index.call_args_list
        nonunique_call = [c for c in index_calls if c.kwargs.get("unique") is False]
        assert len(nonunique_call) == 1
        assert nonunique_call[0].kwargs["fields"] == ["_to"]

    @pytest.mark.unit
    def test_runs_population_queries(self, mock_db):
        """Three AQL population queries are executed (ml_tagged, calibrated, reconciled)."""
        upgrade(mock_db)
        aql_calls = mock_db.aql.execute.call_args_list
        # 3 population queries for ml_tagged, calibrated, reconciled
        assert len(aql_calls) == 3
        queries = [c.args[0] for c in aql_calls]
        assert any("file_states/ml_tagged" in q for q in queries)
        assert any("file_states/calibrated" in q for q in queries)
        assert any("file_states/reconciled" in q for q in queries)


class TestMigrationIdempotent:
    """Test upgrade() handles already-exists scenarios gracefully."""

    @pytest.mark.unit
    def test_skips_collection_creation_when_exists(self, mock_db):
        """When collections exist, create_collection is not called."""
        mock_db.has_collection.return_value = True
        upgrade(mock_db)
        # create_collection is wrapped in contextlib.suppress, but
        # has_collection=True means we skip the create_collection call entirely
        mock_db.create_collection.assert_not_called()

    @pytest.mark.unit
    def test_handles_duplicate_state_docs(self, mock_db):
        """DocumentInsertError(409) for existing state docs is silently caught."""
        from arango.exceptions import DocumentInsertError

        mock_db.has_collection.return_value = True
        coll = mock_db.collection("file_states")
        exc = DocumentInsertError(MagicMock(status_code=409, method="POST", url="test"), MagicMock())
        exc.http_code = 409
        coll.insert.side_effect = exc

        # Should not raise
        upgrade(mock_db)

    @pytest.mark.unit
    def test_handles_duplicate_indexes(self, mock_db):
        """IndexCreateError(409) for existing indexes is silently caught."""
        from arango.exceptions import IndexCreateError

        mock_db.has_collection.return_value = True
        edge_coll = mock_db.collection("file_has_state")
        exc = IndexCreateError(MagicMock(status_code=409, method="POST", url="test"), MagicMock())
        exc.http_code = 409
        edge_coll.add_persistent_index.side_effect = exc

        # Should not raise
        upgrade(mock_db)

    @pytest.mark.unit
    def test_population_uses_ignore_errors(self, mock_db):
        """Population AQL queries use OPTIONS { ignoreErrors: true } for idempotency."""
        upgrade(mock_db)
        aql_calls = mock_db.aql.execute.call_args_list
        for aql_call in aql_calls:
            query = aql_call.args[0]
            assert "ignoreErrors: true" in query, f"Missing ignoreErrors in: {query[:80]}"


class TestPopulationQueries:
    """Test that population queries read correct flat fields."""

    @pytest.mark.unit
    def test_ml_tagged_reads_correct_fields(self, mock_db):
        """ml_tagged population reads tagged, tagged_version, last_tagged_at."""
        upgrade(mock_db)
        ml_query = next(c.args[0] for c in mock_db.aql.execute.call_args_list if "ml_tagged" in c.args[0])
        assert "file.tagged == true" in ml_query
        assert "file.tagged_version" in ml_query
        assert "file.last_tagged_at" in ml_query

    @pytest.mark.unit
    def test_calibrated_reads_correct_fields(self, mock_db):
        """calibrated population reads calibration_hash."""
        upgrade(mock_db)
        cal_query = next(c.args[0] for c in mock_db.aql.execute.call_args_list if "file_states/calibrated" in c.args[0])
        assert "file.calibration_hash != null" in cal_query
        assert "file.calibration_hash" in cal_query

    @pytest.mark.unit
    def test_reconciled_reads_correct_fields(self, mock_db):
        """reconciled population reads last_written_mode and related fields."""
        upgrade(mock_db)
        rec_query = next(c.args[0] for c in mock_db.aql.execute.call_args_list if "file_states/reconciled" in c.args[0])
        assert "file.last_written_mode != null" in rec_query
        assert "file.last_written_mode" in rec_query
        assert "file.last_written_calibration_hash" in rec_query
        assert "file.last_written_at" in rec_query
        assert "file.has_nomarr_namespace" in rec_query
