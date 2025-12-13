"""
Unit tests for nomarr.services.library module.

Tests use REAL fixtures from conftest.py - no redundant mocks.
"""

import pytest

# Mark all tests in this module as unit tests
pytestmark = pytest.mark.unit

from nomarr.helpers.dto.library_dto import LibraryScanStatusResult


class TestLibraryServiceCancelScan:
    """Test LibraryService.cancel_scan() operations."""

    def test_cancel_scan_success(self, real_library_service):
        """Should successfully cancel scan."""
        # Arrange

        # Act
        result = real_library_service.cancel_scan()

        # Assert
        assert isinstance(result, bool)


class TestLibraryServiceGetScanHistory:
    """Test LibraryService.get_scan_history() operations."""

    def test_get_scan_history_success(self, real_library_service):
        """Should successfully get scan history."""
        # Arrange

        # Act
        result = real_library_service.get_scan_history()

        # Assert
        assert isinstance(result, list)
        # TODO: Verify returned data is correct


class TestLibraryServiceGetStatus:
    """Test LibraryService.get_status() operations."""

    def test_get_status_success(self, real_library_service):
        """Should successfully get status."""
        # Arrange

        # Act
        result = real_library_service.get_status()

        # Assert
        assert isinstance(result, LibraryScanStatusResult)
        # TODO: Verify returned data is correct


class TestLibraryServiceIsConfigured:
    """Test LibraryService.is_library_root_configured() operations."""

    def test_is_configured_success(self, real_library_service):
        """Should successfully check if library_root is configured."""
        # Arrange

        # Act
        result = real_library_service.is_library_root_configured()

        # Assert
        assert isinstance(result, bool)


class TestLibraryServiceStartScan:
    """Test LibraryService.start_scan() operations."""

    def test_start_scan_success(self, real_library_service):
        """Should successfully start scan."""
        # Arrange
        from nomarr.helpers.dto.library_dto import StartScanResult

        # Act
        result = real_library_service.start_scan()

        # Assert
        assert isinstance(result, StartScanResult)
        assert result.files_discovered >= 0
        assert result.files_queued >= 0


class TestSublibraryOverlapDetection:
    """Test library overlap detection business rules."""

    def test_create_sublibrary_disjoint_roots_succeeds(self, real_library_service, tmp_path):
        """Should allow creating libraries with disjoint roots."""
        # Arrange - create two separate directory trees
        lib1_path = tmp_path / "library1"
        lib1_path.mkdir()
        lib2_path = tmp_path / "library2"
        lib2_path.mkdir()

        # Mock library_root to be tmp_path
        real_library_service.cfg.library_root = str(tmp_path)

        # Mock the database responses
        real_library_service.db.libraries.list_libraries = lambda enabled_only=False: [
            {"id": 1, "name": "Library 1", "root_path": str(lib1_path)}
        ]
        real_library_service.db.libraries.get_library_by_name = lambda name: None
        real_library_service.db.libraries.create_library = lambda **kwargs: 2
        real_library_service.db.libraries.get_library = lambda id: {
            "id": id,
            "name": "Library 2",
            "root_path": str(lib2_path),
            "is_enabled": True,
            "is_default": False,
            "created_at": "2025-01-01T00:00:00",
            "updated_at": "2025-01-01T00:00:00",
        }

        # Act - create second library with disjoint root
        result = real_library_service.create_library(name="Library 2", root_path=str(lib2_path))

        # Assert
        assert result.name == "Library 2"

    def test_create_sublibrary_nested_inside_existing_fails(self, real_library_service, tmp_path):
        """Should reject creating a library nested inside an existing one."""
        # Arrange - create parent and child directories
        parent_path = tmp_path / "parent"
        parent_path.mkdir()
        child_path = parent_path / "child"
        child_path.mkdir()

        # Mock library_root to be tmp_path
        real_library_service.cfg.library_root = str(tmp_path)

        # Mock the database to return existing parent library
        real_library_service.db.libraries.list_libraries = lambda enabled_only=False: [
            {"id": 1, "name": "Parent Library", "root_path": str(parent_path)}
        ]
        real_library_service.db.libraries.get_library_by_name = lambda name: None

        # Act & Assert - attempt to create child library should fail
        with pytest.raises(ValueError, match="is nested inside existing library"):
            real_library_service.create_library(name="Child Library", root_path=str(child_path))

    def test_create_sublibrary_containing_existing_fails(self, real_library_service, tmp_path):
        """Should reject creating a library that would contain an existing one."""
        # Arrange - create child and parent directories
        parent_path = tmp_path / "parent"
        parent_path.mkdir()
        child_path = parent_path / "child"
        child_path.mkdir()

        # Mock library_root to be tmp_path
        real_library_service.cfg.library_root = str(tmp_path)

        # Mock the database to return existing child library
        real_library_service.db.libraries.list_libraries = lambda enabled_only=False: [
            {"id": 1, "name": "Child Library", "root_path": str(child_path)}
        ]
        real_library_service.db.libraries.get_library_by_name = lambda name: None

        # Act & Assert - attempt to create parent library should fail
        with pytest.raises(ValueError, match="is nested inside new library root"):
            real_library_service.create_library(name="Parent Library", root_path=str(parent_path))

    def test_update_sublibrary_to_disjoint_root_succeeds(self, real_library_service, tmp_path):
        """Should allow updating a library to a disjoint root."""
        # Arrange
        lib1_path = tmp_path / "library1"
        lib1_path.mkdir()
        lib2_path = tmp_path / "library2"
        lib2_path.mkdir()
        new_path = tmp_path / "library1_new"
        new_path.mkdir()

        # Mock library_root to be tmp_path
        real_library_service.cfg.library_root = str(tmp_path)

        # Mock database responses
        real_library_service.db.libraries.get_library = lambda id: {
            "id": 1,
            "name": "Library 1",
            "root_path": str(lib1_path),
            "is_enabled": True,
            "is_default": False,
            "created_at": "2025-01-01T00:00:00",
            "updated_at": "2025-01-01T00:00:00",
        }
        real_library_service.db.libraries.list_libraries = lambda enabled_only=False: [
            {"id": 1, "name": "Library 1", "root_path": str(lib1_path)},
            {"id": 2, "name": "Library 2", "root_path": str(lib2_path)},
        ]
        real_library_service.db.libraries.update_library = lambda id, **kwargs: True

        # Act
        result = real_library_service.update_library_root(library_id=1, root_path=str(new_path))

        # Assert
        assert result is not None

    def test_update_sublibrary_to_nested_root_fails(self, real_library_service, tmp_path):
        """Should reject updating a library to a nested root."""
        # Arrange
        lib1_path = tmp_path / "library1"
        lib1_path.mkdir()
        lib2_path = tmp_path / "library2"
        lib2_path.mkdir()
        nested_path = lib2_path / "nested"
        nested_path.mkdir()

        # Mock library_root to be tmp_path
        real_library_service.cfg.library_root = str(tmp_path)

        # Mock database responses
        real_library_service.db.libraries.get_library = lambda id: {
            "id": 1,
            "name": "Library 1",
            "root_path": str(lib1_path),
            "is_enabled": True,
            "is_default": False,
            "created_at": "2025-01-01T00:00:00",
            "updated_at": "2025-01-01T00:00:00",
        }
        real_library_service.db.libraries.list_libraries = lambda enabled_only=False: [
            {"id": 1, "name": "Library 1", "root_path": str(lib1_path)},
            {"id": 2, "name": "Library 2", "root_path": str(lib2_path)},
        ]

        # Act & Assert - attempt to move lib1 inside lib2 should fail
        with pytest.raises(ValueError, match="is nested inside existing library"):
            real_library_service.update_library_root(library_id=1, root_path=str(nested_path))

    def test_update_sublibrary_to_same_root_succeeds(self, real_library_service, tmp_path):
        """Should allow updating a library to its own root (no-op update)."""
        # Arrange
        lib1_path = tmp_path / "library1"
        lib1_path.mkdir()

        # Mock library_root to be tmp_path
        real_library_service.cfg.library_root = str(tmp_path)

        # Mock database responses
        real_library_service.db.libraries.get_library = lambda id: {
            "id": 1,
            "name": "Library 1",
            "root_path": str(lib1_path),
            "is_enabled": True,
            "is_default": False,
            "created_at": "2025-01-01T00:00:00",
            "updated_at": "2025-01-01T00:00:00",
        }
        real_library_service.db.libraries.list_libraries = lambda enabled_only=False: [
            {"id": 1, "name": "Library 1", "root_path": str(lib1_path)},
        ]
        real_library_service.db.libraries.update_library = lambda id, **kwargs: True

        # Act - update to same path should succeed (ignore_id filters out self)
        result = real_library_service.update_library_root(library_id=1, root_path=str(lib1_path))

        # Assert
        assert result is not None
