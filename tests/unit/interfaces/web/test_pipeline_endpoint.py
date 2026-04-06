from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.helpers.dto import LibraryPipelineStatusDTO
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_pipeline_service
from nomarr.interfaces.api.web.library_if import router as library_router


@pytest.fixture
def mock_pipeline_service() -> MagicMock:
    """Provide a mocked pipeline service dependency."""
    return MagicMock()


@pytest.fixture
def app(mock_pipeline_service: MagicMock) -> Iterator[FastAPI]:
    """Build a minimal FastAPI app for the library pipeline endpoint."""
    test_app = FastAPI()
    test_app.include_router(library_router, prefix="/api/web")

    async def allow_session() -> None:
        return None

    test_app.dependency_overrides[verify_session] = allow_session
    test_app.dependency_overrides[get_pipeline_service] = lambda: mock_pipeline_service

    yield test_app

    test_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Create a TestClient for the minimal app."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.unit
@pytest.mark.mocked
class TestPipelineEndpoint:
    """Tests for the GET library pipeline endpoint."""

    def test_get_pipeline_status_happy_path(
        self,
        client: TestClient,
        mock_pipeline_service: MagicMock,
    ) -> None:
        """The endpoint should serialize a pipeline DTO into the response body."""
        mock_pipeline_service.get_pipeline_status.return_value = LibraryPipelineStatusDTO(
            library_id="libraries/test-lib",
            state="write_ready",
            untagged_count=None,
            uncalibrated_count=None,
            pending_write_count=17,
            library_auto_write=False,
            file_write_mode="full",
        )

        response = client.get("/api/web/library/libraries:test-lib/pipeline")

        assert response.status_code == 200
        assert response.json() == {
            "library_id": "libraries/test-lib",
            "state": "write_ready",
            "untagged_count": None,
            "uncalibrated_count": None,
            "pending_write_count": 17,
            "library_auto_write": False,
            "file_write_mode": "full",
        }
        mock_pipeline_service.get_pipeline_status.assert_called_once_with("libraries/test-lib")

    def test_get_pipeline_status_returns_404_when_library_missing(
        self,
        client: TestClient,
        mock_pipeline_service: MagicMock,
    ) -> None:
        """Missing libraries should surface as HTTP 404."""
        mock_pipeline_service.get_pipeline_status.return_value = None

        response = client.get("/api/web/library/libraries:test-lib/pipeline")

        assert response.status_code == 404
        assert response.json() == {"detail": "Library not found"}
        mock_pipeline_service.get_pipeline_status.assert_called_once_with("libraries/test-lib")
