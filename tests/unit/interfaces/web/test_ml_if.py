from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.helpers.dto.info_dto import WorkStatusResult
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_library_service, get_ml_service
from nomarr.interfaces.api.web.ml_if import router as ml_router


@pytest.fixture
def mock_library_service() -> MagicMock:
    """Provide a mocked library service dependency."""
    return MagicMock()


@pytest.fixture
def mock_ml_service() -> MagicMock:
    """Provide a mocked ML service dependency."""
    return MagicMock()


@pytest.fixture
def app(
    mock_library_service: MagicMock,
    mock_ml_service: MagicMock,
) -> Iterator[FastAPI]:
    """Build a minimal FastAPI app for ML endpoints."""
    test_app = FastAPI()
    test_app.include_router(ml_router, prefix="/api/web")

    async def allow_session() -> None:
        return None

    test_app.dependency_overrides[verify_session] = allow_session
    test_app.dependency_overrides[get_library_service] = lambda: mock_library_service
    test_app.dependency_overrides[get_ml_service] = lambda: mock_ml_service

    yield test_app

    test_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Create a TestClient for the minimal app."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.unit
@pytest.mark.mocked
class TestMlIfRoutes:
    """Tests for the renamed machine-learning routes."""

    def test_work_status_is_reachable_at_machine_learning_prefix(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """The work-status endpoint should be reachable under /machine-learning."""
        mock_library_service.get_work_status.return_value = WorkStatusResult(
            is_scanning=False,
            scanning_libraries=[],
            pipeline_libraries=[],
            is_processing=False,
            pending_files=0,
            processed_files=0,
            total_files=0,
            files_per_minute=0.0,
            estimated_minutes_remaining=None,
            is_busy=False,
        )

        response = client.get("/api/web/machine-learning/work-status")

        assert response.status_code == 200
        assert response.json() == {
            "is_scanning": False,
            "scanning_libraries": [],
            "pipeline_libraries": [],
            "is_processing": False,
            "pending_files": 0,
            "processed_files": 0,
            "total_files": 0,
            "files_per_minute": 0.0,
            "estimated_minutes_remaining": None,
            "is_busy": False,
        }
        mock_library_service.get_work_status.assert_called_once_with()

    def test_recent_activity_is_reachable_at_machine_learning_prefix(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """The recent-activity endpoint should be reachable under /machine-learning."""
        mock_library_service.get_recently_processed.return_value = [
            {
                "file_id": "library_files/1",
                "path": "Music/Test Song.flac",
                "title": "Test Song",
                "artist": "Test Artist",
                "album": "Test Album",
                "scanned_at": 1_712_345_678,
            },
        ]

        response = client.get("/api/web/machine-learning/recent-activity")

        assert response.status_code == 200
        assert response.json() == {
            "files": [
                {
                    "file_id": "library_files/1",
                    "path": "Music/Test Song.flac",
                    "title": "Test Song",
                    "artist": "Test Artist",
                    "album": "Test Album",
                    "scanned_at": 1_712_345_678,
                },
            ],
        }
        mock_library_service.get_recently_processed.assert_called_once_with(limit=20, library_id=None)

    def test_list_models_is_reachable_at_machine_learning_prefix(
        self,
        client: TestClient,
        mock_ml_service: MagicMock,
    ) -> None:
        """The model listing endpoint should be reachable under /machine-learning."""
        mock_ml_service.list_all_models.return_value = []

        response = client.get("/api/web/machine-learning/model")

        assert response.status_code == 200
        assert response.json() == []
        mock_ml_service.list_all_models.assert_called_once_with()
