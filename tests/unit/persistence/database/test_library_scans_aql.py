"""Unit tests for LibraryScansOperations (library_scans_aql.py).

Verifies AQL queries are structured correctly for scan state operations.
Mock-based — runs without ArangoDB.
"""

from unittest.mock import MagicMock

import pytest

from nomarr.persistence.database.library_scans_aql import LibraryScansOperations


@pytest.fixture
def mock_db() -> MagicMock:
    """Provide mock ArangoDB."""
    db = MagicMock()
    db.name = "test_db"
    return db


@pytest.fixture
def ops(mock_db: MagicMock) -> LibraryScansOperations:
    """Provide LibraryScansOperations instance."""
    return LibraryScansOperations(mock_db)


# ==================================================================
# get_or_create_scan
# ==================================================================


class TestGetOrCreateScan:
    """Test get_or_create_scan() method."""

    @pytest.mark.unit
    def test_executes_upsert_query(self, ops: LibraryScansOperations, mock_db: MagicMock) -> None:
        """Executes UPSERT-style query for lazy scan creation."""
        # Mock cursor to return a scan document
        mock_cursor = MagicMock()
        mock_cursor.__next__ = MagicMock(
            return_value={
                "_key": "lib123",
                "status": "idle",
                "files_processed": 0,
                "files_total": 0,
            }
        )
        mock_db.aql.execute.return_value = mock_cursor

        result = ops.get_or_create_scan("libraries/lib123")

        # Should have executed AQL
        assert mock_db.aql.execute.call_count == 1
        call_args = mock_db.aql.execute.call_args
        query = call_args[0][0]

        # Query should check for existing and insert if missing
        assert "DOCUMENT" in query
        assert "INSERT" in query
        assert "library_scans" in query

        # Bind vars should include library key
        bind_vars = call_args[1]["bind_vars"]
        assert bind_vars["library_key"] == "lib123"
        assert bind_vars["library_id"] == "libraries/lib123"

        # Result should be the scan document
        assert result["_key"] == "lib123"
        assert result["status"] == "idle"

    @pytest.mark.unit
    def test_extracts_key_from_full_id(self, ops: LibraryScansOperations, mock_db: MagicMock) -> None:
        """Correctly extracts _key from full document ID."""
        mock_cursor = MagicMock()
        mock_cursor.__next__ = MagicMock(return_value={"_key": "abc123"})
        mock_db.aql.execute.return_value = mock_cursor

        ops.get_or_create_scan("libraries/abc123")

        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["library_key"] == "abc123"

    @pytest.mark.unit
    def test_returns_default_on_empty_cursor(self, ops: LibraryScansOperations, mock_db: MagicMock) -> None:
        """Returns default scan state if cursor is empty."""
        mock_cursor = MagicMock()
        mock_cursor.__next__ = MagicMock(side_effect=StopIteration)
        mock_db.aql.execute.return_value = mock_cursor

        result = ops.get_or_create_scan("libraries/lib999")

        # Should return default scan state
        assert result["_key"] == "lib999"
        assert result["status"] == "idle"
        assert result["files_processed"] == 0
        assert result["files_total"] == 0

    @pytest.mark.unit
    def test_upserts_edge_in_library_has_scan(self, ops: LibraryScansOperations, mock_db: MagicMock) -> None:
        """Query should upsert edge in library_has_scan collection."""
        mock_cursor = MagicMock()
        mock_cursor.__next__ = MagicMock(return_value={"_key": "lib1"})
        mock_db.aql.execute.return_value = mock_cursor

        ops.get_or_create_scan("libraries/lib1")

        query = mock_db.aql.execute.call_args[0][0]
        assert "library_has_scan" in query
        assert "UPSERT" in query


# ==================================================================
# update_scan
# ==================================================================


class TestUpdateScan:
    """Test update_scan() method."""

    @pytest.mark.unit
    def test_executes_upsert_with_fields(self, ops: LibraryScansOperations, mock_db: MagicMock) -> None:
        """Executes UPSERT query with provided fields."""
        mock_cursor = MagicMock()
        mock_cursor.__next__ = MagicMock(
            return_value={
                "_key": "lib1",
                "status": "scanning",
                "files_processed": 50,
                "files_total": 100,
            }
        )
        mock_db.aql.execute.return_value = mock_cursor

        result = ops.update_scan(
            "libraries/lib1",
            status="scanning",
            files_processed=50,
            files_total=100,
        )

        # Result should contain updated values
        assert result["status"] == "scanning"
        assert mock_db.aql.execute.call_count == 1
        call_args = mock_db.aql.execute.call_args
        query = call_args[0][0]

        assert "UPSERT" in query
        assert "UPDATE" in query
        assert "library_scans" in query

        bind_vars = call_args[1]["bind_vars"]
        assert bind_vars["library_key"] == "lib1"
        assert bind_vars["fields"]["status"] == "scanning"
        assert bind_vars["fields"]["files_processed"] == 50

    @pytest.mark.unit
    def test_partial_update_only_specified_fields(self, ops: LibraryScansOperations, mock_db: MagicMock) -> None:
        """Should only include specified fields in update."""
        mock_cursor = MagicMock()
        mock_cursor.__next__ = MagicMock(return_value={"_key": "lib1"})
        mock_db.aql.execute.return_value = mock_cursor

        ops.update_scan("libraries/lib1", status="complete")

        bind_vars = mock_db.aql.execute.call_args[1]["bind_vars"]
        assert bind_vars["fields"] == {"status": "complete"}


# ==================================================================
# get_scan_state
# ==================================================================


class TestGetScanState:
    """Test get_scan_state() method."""

    @pytest.mark.unit
    def test_retrieves_from_collection(self, ops: LibraryScansOperations, mock_db: MagicMock) -> None:
        """Uses collection.get() to retrieve scan state."""
        mock_collection = MagicMock()
        mock_collection.get.return_value = {
            "_key": "lib1",
            "status": "complete",
            "files_processed": 100,
            "files_total": 100,
            "completed_at": 1700000000000,
        }
        mock_db.collection.return_value = mock_collection

        # Re-create ops to use updated mock
        ops_with_collection = LibraryScansOperations(mock_db)
        result = ops_with_collection.get_scan_state("libraries/lib1")

        mock_collection.get.assert_called_once_with("lib1")
        assert result is not None
        assert result["status"] == "complete"
        assert result["completed_at"] == 1700000000000

    @pytest.mark.unit
    def test_returns_none_when_no_scan(self, ops: LibraryScansOperations, mock_db: MagicMock) -> None:
        """Returns None if no scan document exists."""
        mock_collection = MagicMock()
        mock_collection.get.return_value = None
        mock_db.collection.return_value = mock_collection

        ops_with_collection = LibraryScansOperations(mock_db)
        result = ops_with_collection.get_scan_state("libraries/nonexistent")

        assert result is None
