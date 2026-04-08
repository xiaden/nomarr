from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.helpers.dto.library_dto import LibraryDict, LibraryStatsResult
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import (
    get_config_service,
    get_library_service,
    get_pipeline_service,
    get_vector_maintenance_service,
)
from nomarr.interfaces.api.web.library_if import router as library_router


def make_library(*, auto_write: bool = False, name: str = "Test Library") -> LibraryDict:
    """Build a minimal LibraryDict fixture for interface tests."""
    return LibraryDict(
        _id="libraries/test-lib",
        _key="test-lib",
        _rev="rev-1",
        name=name,
        root_path="D:/Music/Test",
        is_enabled=True,
        created_at="2026-04-06T00:00:00+00:00",
        updated_at="2026-04-06T00:00:00+00:00",
        watch_mode="off",
        file_write_mode="full",
        library_auto_write=auto_write,
        file_count=12,
        folder_count=3,
    )


@pytest.fixture
def mock_library_service() -> MagicMock:
    """Provide a mocked library service dependency."""
    return MagicMock()


@pytest.fixture
def mock_config_service() -> MagicMock:
    """Provide a mocked config service dependency."""
    return MagicMock()


@pytest.fixture
def mock_pipeline_service() -> MagicMock:
    """Provide a mocked pipeline service dependency."""
    return MagicMock()


@pytest.fixture
def mock_vector_maintenance_service() -> MagicMock:
    """Provide a mocked vector maintenance service dependency."""
    return MagicMock()


@pytest.fixture
def app(
    mock_library_service: MagicMock,
    mock_config_service: MagicMock,
    mock_pipeline_service: MagicMock,
    mock_vector_maintenance_service: MagicMock,
) -> Iterator[FastAPI]:
    """Build a minimal FastAPI app for library CRUD endpoints."""
    test_app = FastAPI()
    test_app.include_router(library_router, prefix="/api/web")

    async def allow_session() -> None:
        return None

    test_app.dependency_overrides[verify_session] = allow_session
    test_app.dependency_overrides[get_library_service] = lambda: mock_library_service
    test_app.dependency_overrides[get_config_service] = lambda: mock_config_service
    test_app.dependency_overrides[get_pipeline_service] = lambda: mock_pipeline_service
    test_app.dependency_overrides[get_vector_maintenance_service] = lambda: mock_vector_maintenance_service

    yield test_app

    test_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Create a TestClient for the minimal app."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.unit
@pytest.mark.mocked
class TestLibraryCrudEndpoints:
    """Tests for library CRUD and vector endpoints."""

    def test_get_library_stats_returns_response(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """GET stats should serialize the library statistics DTO."""
        mock_library_service.get_library_stats.return_value = LibraryStatsResult(
            total_files=321,
            total_artists=45,
            total_albums=67,
            total_duration=8901.5,
            total_size=123456,
            needs_tagging_count=8,
        )

        response = client.get("/api/web/library/stats")

        assert response.status_code == 200
        assert response.json() == {
            "total_files": 321,
            "unique_artists": 45,
            "unique_albums": 67,
            "total_duration_seconds": 8901.5,
        }
        mock_library_service.get_library_stats.assert_called_once_with()

    def test_list_libraries_returns_response(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """GET collection should return the wrapped library list response."""
        mock_library_service.list_libraries.return_value = [make_library()]

        response = client.get("/api/web/library")

        assert response.status_code == 200
        assert response.json() == {
            "libraries": [
                {
                    "library_id": "libraries:test-lib",
                    "name": "Test Library",
                    "root_path": "D:/Music/Test",
                    "is_enabled": True,
                    "watch_mode": "off",
                    "file_write_mode": "full",
                    "library_auto_write": False,
                    "created_at": "2026-04-06T00:00:00+00:00",
                    "updated_at": "2026-04-06T00:00:00+00:00",
                    "scan_status": None,
                    "scan_progress": None,
                    "scan_total": None,
                    "scanned_at": None,
                    "scan_error": None,
                    "file_count": 12,
                    "folder_count": 3,
                }
            ]
        }
        mock_library_service.list_libraries.assert_called_once_with(enabled_only=False)

    def test_get_library_returns_response(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """GET item should decode the path ID and serialize the returned library."""
        mock_library_service.get_library.return_value = make_library()

        response = client.get("/api/web/library/libraries:test-lib")

        assert response.status_code == 200
        assert response.json()["library_id"] == "libraries:test-lib"
        assert response.json()["name"] == "Test Library"
        mock_library_service.get_library.assert_called_once_with("libraries/test-lib")

    def test_get_library_returns_404_when_missing(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """Missing libraries should surface as HTTP 404."""
        mock_library_service.get_library.side_effect = ValueError("missing")

        response = client.get("/api/web/library/libraries:test-lib")

        assert response.status_code == 404
        assert response.json() == {"detail": "Library not found"}
        mock_library_service.get_library.assert_called_once_with("libraries/test-lib")

    def test_create_library_returns_response(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """POST should forward the request body to the service and return the created library."""
        mock_library_service.create_library.return_value = make_library(name="Created Library")

        response = client.post(
            "/api/web/library",
            json={
                "name": "Created Library",
                "root_path": "D:/Music/Test",
                "is_enabled": True,
                "watch_mode": "poll",
                "file_write_mode": "minimal",
                "library_auto_write": True,
            },
        )

        assert response.status_code == 200
        assert response.json()["name"] == "Created Library"
        mock_library_service.create_library.assert_called_once_with(
            name="Created Library",
            root_path="D:/Music/Test",
            is_enabled=True,
            watch_mode="poll",
            file_write_mode="minimal",
            library_auto_write=True,
        )

    def test_create_library_returns_400_when_invalid(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """Invalid library configuration errors should map to HTTP 400."""
        mock_library_service.create_library.side_effect = ValueError("bad config")

        response = client.post(
            "/api/web/library",
            json={"root_path": "D:/Music/Test"},
        )

        assert response.status_code == 400
        assert response.json() == {"detail": "Invalid library configuration"}

    def test_delete_library_returns_success_message(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """DELETE should return the success envelope when the service deletes the library."""
        mock_library_service.delete_library.return_value = True

        response = client.delete("/api/web/library/libraries:test-lib")

        assert response.status_code == 200
        assert response.json() == {
            "status": "success",
            "message": "Library libraries/test-lib deleted",
        }
        mock_library_service.delete_library.assert_called_once_with("libraries/test-lib")

    def test_delete_library_returns_404_when_not_found(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """DELETE should return HTTP 404 when the service reports no deletion."""
        mock_library_service.delete_library.return_value = False

        response = client.delete("/api/web/library/libraries:test-lib")

        assert response.status_code == 404
        assert response.json() == {"detail": "Library not found"}
        mock_library_service.delete_library.assert_called_once_with("libraries/test-lib")

    def test_get_library_vector_config_returns_response(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """GET vector config should return the resolved configuration payload."""
        mock_library_service.get_vector_config.return_value = {
            "vector_group_size": 64,
            "vector_search_thoroughness": 200,
            "is_group_size_inherited": False,
            "is_thoroughness_inherited": True,
        }

        response = client.get("/api/web/library/libraries:test-lib/vector-config")

        assert response.status_code == 200
        assert response.json() == {
            "vector_group_size": 64,
            "vector_search_thoroughness": 200,
            "is_group_size_inherited": False,
            "is_thoroughness_inherited": True,
        }
        mock_library_service.get_vector_config.assert_called_once()
        assert mock_library_service.get_vector_config.call_args.args[0] == "libraries/test-lib"

    def test_get_library_vector_config_returns_404_when_missing(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """Missing libraries should surface as HTTP 404 for vector config reads."""
        mock_library_service.get_vector_config.side_effect = ValueError("missing")

        response = client.get("/api/web/library/libraries:test-lib/vector-config")

        assert response.status_code == 404
        assert response.json() == {"detail": "Library not found"}

    def test_update_library_vector_config_returns_updated_response(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """PUT vector config should persist the override and return the effective config."""
        mock_library_service.get_vector_config.return_value = {
            "vector_group_size": 128,
            "vector_search_thoroughness": 400,
            "is_group_size_inherited": False,
            "is_thoroughness_inherited": False,
        }

        response = client.put(
            "/api/web/library/libraries:test-lib/vector-config",
            json={
                "vector_group_size": 128,
                "vector_search_thoroughness": 400,
            },
        )

        assert response.status_code == 200
        assert response.json() == {
            "vector_group_size": 128,
            "vector_search_thoroughness": 400,
            "is_group_size_inherited": False,
            "is_thoroughness_inherited": False,
        }
        mock_library_service.update_vector_config.assert_called_once_with(
            "libraries/test-lib",
            vector_group_size=128,
            vector_search_thoroughness=400,
        )
        mock_library_service.get_vector_config.assert_called_once()
        assert mock_library_service.get_vector_config.call_args.args[0] == "libraries/test-lib"

    def test_update_library_vector_config_returns_400_for_invalid_values(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """Validation failures should preserve the service detail and map to HTTP 400."""
        mock_library_service.update_vector_config.side_effect = ValueError(
            "vector_group_size must be positive",
        )

        response = client.put(
            "/api/web/library/libraries:test-lib/vector-config",
            json={"vector_group_size": 0},
        )

        assert response.status_code == 400
        assert response.json() == {"detail": "vector_group_size must be positive"}

    def test_get_library_vector_stats_returns_response(
        self,
        client: TestClient,
        mock_vector_maintenance_service: MagicMock,
    ) -> None:
        """GET vector stats should map each raw stat row into the API response."""
        mock_vector_maintenance_service.get_library_vector_stats.return_value = [
            {
                "backbone_id": "discogs-effnet",
                "hot_count": 10,
                "cold_count": 2,
                "index_exists": True,
            }
        ]

        response = client.get("/api/web/library/libraries:test-lib/vector-stats")

        assert response.status_code == 200
        assert response.json() == {
            "library_key": "test-lib",
            "stats": [
                {
                    "backbone_id": "discogs-effnet",
                    "hot_count": 10,
                    "cold_count": 2,
                    "index_exists": True,
                }
            ],
        }
        mock_vector_maintenance_service.get_library_vector_stats.assert_called_once_with("libraries/test-lib")

    def test_get_library_vector_stats_returns_404_when_missing(
        self,
        client: TestClient,
        mock_vector_maintenance_service: MagicMock,
    ) -> None:
        """Missing libraries should surface as HTTP 404 for vector stats."""
        mock_vector_maintenance_service.get_library_vector_stats.side_effect = ValueError("missing")

        response = client.get("/api/web/library/libraries:test-lib/vector-stats")

        assert response.status_code == 404
        assert response.json() == {"detail": "Library not found"}
