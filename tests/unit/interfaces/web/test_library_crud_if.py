from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dto.library_dto import LibraryStatsResult
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import (
    get_config_service,
    get_library_service,
    get_pipeline_service,
    get_vector_maintenance_service,
)
from nomarr.interfaces.api.web.library_if import router as library_router

if TYPE_CHECKING:
    from collections.abc import Iterator


def make_library(*, auto_write: bool = False, name: str = "Test Library") -> Library:
    """Build a domain ``Library`` fixture for interface tests (natural identity)."""
    return Library(
        name=name,
        root_path="D:/Music/Test",
        is_enabled=True,
        watch_mode="off",
        file_write_mode="full",
        library_auto_write=auto_write,
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
        """GET collection should return the wrapped library list with natural-name ids."""
        mock_library_service.list_libraries.return_value = [make_library()]
        # The interface adapter builds the name-keyed counts and per-library scan
        # status; a missing status projects to None.
        mock_library_service.get_status.return_value = None
        with patch(
            "nomarr.interfaces.api.web.library_if.get_library_counts",
            return_value={"Test Library": {"file_count": 12, "folder_count": 3}},
        ):
            response = client.get("/api/web/library")

        assert response.status_code == 200
        assert response.json() == {
            "libraries": [
                {
                    "library_id": "Test Library",
                    "name": "Test Library",
                    "root_path": "D:/Music/Test",
                    "is_enabled": True,
                    "watch_mode": "off",
                    "file_write_mode": "full",
                    "library_auto_write": False,
                    "created_at": "",
                    "updated_at": "",
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
        """GET item should decode the URL-encoded natural name and serialize the library."""
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library

        response = client.get("/api/web/library/Test%20Library")

        assert response.status_code == 200
        assert response.json()["library_id"] == "Test Library"
        assert response.json()["name"] == "Test Library"
        # Mechanism A: the wire identity is the decoded natural name, never an int PK.
        mock_library_service.get_library_by_name.assert_called_once_with("Test Library")
        assert isinstance(mock_library_service.get_library_by_name.call_args.args[0], str)

    def test_get_library_returns_404_when_missing(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """Missing libraries should surface as HTTP 404."""
        mock_library_service.get_library_by_name.return_value = None

        response = client.get("/api/web/library/Test%20Library")

        assert response.status_code == 404
        assert response.json() == {"detail": "Library not found"}
        mock_library_service.get_library_by_name.assert_called_once_with("Test Library")

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
        """DELETE should return the success envelope with the natural library name."""
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library
        mock_library_service.delete_library.return_value = True

        response = client.delete("/api/web/library/Test%20Library")

        assert response.status_code == 200
        assert response.json() == {
            "status": "success",
            "message": "Library Test Library deleted",
        }
        mock_library_service.delete_library.assert_called_once_with(library)

    def test_delete_library_returns_404_when_not_found(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """DELETE should return HTTP 404 when the service reports no deletion."""
        mock_library_service.get_library_by_name.return_value = make_library()
        mock_library_service.delete_library.return_value = False

        response = client.delete("/api/web/library/Test%20Library")

        assert response.status_code == 404
        assert response.json() == {"detail": "Library not found"}
        mock_library_service.delete_library.assert_called_once_with(make_library())

    # Per-library vector config endpoints removed per ADR-036/037
    # vector_group_size is now global-only, managed via general config

    def test_get_library_vector_stats_returns_response(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_vector_maintenance_service: MagicMock,
    ) -> None:
        """GET vector stats should scope per-backbone stats to the resolved Library."""
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library
        mock_vector_maintenance_service.get_backbone_vector_stats = MagicMock(
            return_value=[
                {
                    "backbone_id": "discogs-effnet",
                    "hot_count": 10,
                    "cold_count": 2,
                    "index_exists": True,
                }
            ]
        )

        response = client.get("/api/web/library/Test%20Library/vector-stats")

        assert response.status_code == 200
        assert response.json() == {
            "stats": [
                {
                    "backbone_id": "discogs-effnet",
                    "hot_count": 10,
                    "cold_count": 2,
                    "index_exists": True,
                }
            ],
        }
        mock_vector_maintenance_service.get_backbone_vector_stats.assert_called_once_with(library)

    def test_get_library_vector_stats_handles_service_error(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_vector_maintenance_service: MagicMock,
    ) -> None:
        """Service errors should map to HTTP 500 with sanitized message."""
        mock_library_service.get_library_by_name.return_value = make_library()
        mock_vector_maintenance_service.get_backbone_vector_stats = MagicMock(
            side_effect=RuntimeError("internal error")
        )

        response = client.get("/api/web/library/Test%20Library/vector-stats")

        assert response.status_code == 500
