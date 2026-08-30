from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dto import LibraryPipelineStatusDTO
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_library_service, get_pipeline_service
from nomarr.interfaces.api.web.library_scan_if import router as library_router

if TYPE_CHECKING:
    from collections.abc import Iterator


def make_library() -> Library:
    """Build a domain ``Library`` fixture (natural identity)."""
    return Library(name="Test Library", root_path="D:/Music/Test")


@pytest.fixture
def mock_library_service() -> MagicMock:
    """Provide a mocked library service dependency."""
    return MagicMock()


@pytest.fixture
def mock_pipeline_service() -> MagicMock:
    """Provide a mocked pipeline service dependency."""
    return MagicMock()


@pytest.fixture
def app(
    mock_library_service: MagicMock,
    mock_pipeline_service: MagicMock,
) -> Iterator[FastAPI]:
    """Build a minimal FastAPI app for the library pipeline endpoint."""
    test_app = FastAPI()
    test_app.include_router(library_router, prefix="/api/web")

    async def allow_session() -> None:
        return None

    test_app.dependency_overrides[verify_session] = allow_session
    test_app.dependency_overrides[get_library_service] = lambda: mock_library_service
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
        mock_library_service: MagicMock,
        mock_pipeline_service: MagicMock,
    ) -> None:
        """The endpoint should serialize a pipeline DTO into the response body."""
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library
        mock_pipeline_service.get_pipeline_status.return_value = LibraryPipelineStatusDTO(
            library_id="Test Library",
            scan_state="scanned",
            ml_state="ML_processed",
            calibration_state="not_calibrated",
            tag_write_state="not_written",
            untagged_count=None,
            uncalibrated_count=None,
            pending_write_count=17,
            library_auto_write=False,
            file_write_mode="full",
        )

        response = client.get("/api/web/library/Test%20Library/pipeline")

        assert response.status_code == 200
        assert response.json() == {
            "library_id": "Test Library",
            "scan_state": "scanned",
            "ml_state": "ML_processed",
            "calibration_state": "not_calibrated",
            "tag_write_state": "not_written",
            "untagged_count": None,
            "uncalibrated_count": None,
            "pending_write_count": 17,
            "library_auto_write": False,
            "file_write_mode": "full",
        }
        mock_library_service.get_library_by_name.assert_called_once_with("Test Library")
        mock_pipeline_service.get_pipeline_status.assert_called_once_with(library)

    def test_get_pipeline_status_returns_404_when_name_missing(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_pipeline_service: MagicMock,
    ) -> None:
        """A library name that resolves to nothing should surface as HTTP 404."""
        mock_library_service.get_library_by_name.return_value = None

        response = client.get("/api/web/library/Test%20Library/pipeline")

        assert response.status_code == 404
        assert response.json() == {"detail": "Library not found"}
        mock_library_service.get_library_by_name.assert_called_once_with("Test Library")
        mock_pipeline_service.get_pipeline_status.assert_not_called()

    def test_get_pipeline_status_returns_404_when_no_pipeline_state(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_pipeline_service: MagicMock,
    ) -> None:
        """A resolved library with no pipeline state should surface as HTTP 404."""
        mock_library_service.get_library_by_name.return_value = make_library()
        mock_pipeline_service.get_pipeline_status.return_value = None

        response = client.get("/api/web/library/Test%20Library/pipeline")

        assert response.status_code == 404
        assert response.json() == {"detail": "Library not found"}
        mock_pipeline_service.get_pipeline_status.assert_called_once_with(make_library())
