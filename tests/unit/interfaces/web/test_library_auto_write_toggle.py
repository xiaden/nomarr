from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.helpers.dto.library_dto import LibraryDict
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_library_service, get_pipeline_service
from nomarr.interfaces.api.web.library_if import router as library_router


def make_library(*, auto_write: bool, name: str = "Test Library") -> LibraryDict:
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
    )


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
    """Build a minimal FastAPI app for the library update endpoint."""
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
class TestLibraryAutoWriteToggle:
    """Tests for reactive pipeline behavior when library_auto_write changes."""

    def test_enabling_auto_write_dispatches_write_when_write_ready(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_pipeline_service: MagicMock,
    ) -> None:
        """Enabling auto-write should start writing immediately from write_ready."""
        old_library = make_library(auto_write=False)
        new_library = make_library(auto_write=True)
        mock_library_service.get_library.return_value = old_library
        mock_library_service.update_library.return_value = new_library
        mock_pipeline_service.get_pipeline_status.return_value = MagicMock(state="write_ready")

        response = client.patch(
            "/api/web/library/libraries:test-lib",
            json={"library_auto_write": True},
        )

        assert response.status_code == 200
        mock_library_service.get_library.assert_called_once_with("libraries/test-lib")
        mock_pipeline_service.get_pipeline_status.assert_called_once_with("libraries/test-lib")
        mock_pipeline_service.handle_auto_write_enabled.assert_called_once_with("libraries/test-lib")
        mock_pipeline_service.handle_auto_write_disabled.assert_not_called()

    def test_disabling_auto_write_stops_write_when_currently_writing(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_pipeline_service: MagicMock,
    ) -> None:
        """Disabling auto-write mid-write should request cancellation."""
        old_library = make_library(auto_write=True)
        new_library = make_library(auto_write=False)
        mock_library_service.get_library.return_value = old_library
        mock_library_service.update_library.return_value = new_library
        mock_pipeline_service.get_pipeline_status.return_value = MagicMock(state="writing")

        response = client.patch(
            "/api/web/library/libraries:test-lib",
            json={"library_auto_write": False},
        )

        assert response.status_code == 200
        mock_pipeline_service.get_pipeline_status.assert_called_once_with("libraries/test-lib")
        mock_pipeline_service.handle_auto_write_disabled.assert_called_once_with("libraries/test-lib")
        mock_pipeline_service.handle_auto_write_enabled.assert_not_called()

    def test_updating_other_library_fields_does_not_trigger_pipeline_calls(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_pipeline_service: MagicMock,
    ) -> None:
        """PATCH requests that do not touch auto-write should not trigger pipeline behavior."""
        mock_library_service.update_library.return_value = make_library(auto_write=False, name="Renamed Library")

        response = client.patch(
            "/api/web/library/libraries:test-lib",
            json={"name": "Renamed Library"},
        )

        assert response.status_code == 200
        mock_library_service.get_library.assert_not_called()
        mock_pipeline_service.get_pipeline_status.assert_not_called()
        mock_pipeline_service.handle_auto_write_enabled.assert_not_called()
        mock_pipeline_service.handle_auto_write_disabled.assert_not_called()
