"""Tests for the clear-data web endpoint (``library_if``).

Covers the guard/error-mapping contract for ``POST /api/web/library/clear-data``:
session-auth enforcement, success -> 200, missing-root ``ValueError`` -> 400,
active-scan ``RuntimeError`` -> 409, and any other ``Exception`` -> 500 with a
sanitized body. Proves the aggregate failure is never reported as a partial
success (2xx) response.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_library_service
from nomarr.interfaces.api.web.library_if import router as library_router

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def mock_library_service() -> MagicMock:
    """Provide a mocked library service dependency."""
    return MagicMock()


@pytest.fixture
def app(mock_library_service: MagicMock) -> Iterator[FastAPI]:
    """Build a minimal FastAPI app for the clear-data endpoint."""
    test_app = FastAPI()
    test_app.include_router(library_router, prefix="/api/web")

    async def allow_session() -> None:
        return None

    test_app.dependency_overrides[verify_session] = allow_session
    test_app.dependency_overrides[get_library_service] = lambda: mock_library_service

    yield test_app

    test_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Create a TestClient for the minimal app."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.unit
@pytest.mark.mocked
class TestClearLibraryDataRoute:
    """Tests for the POST /clear-data route handler and its HTTP mappings."""

    def test_clear_data_success_returns_200(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """A successful clear should return the success envelope (200)."""
        response = client.post("/api/web/library/clear-data")

        assert response.status_code == 200
        assert response.json() == {"status": "success", "message": "Library data cleared"}
        mock_library_service.clear_library_data.assert_called_once_with()

    def test_clear_data_missing_root_maps_to_400(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """An unset library_root (ValueError) should surface as HTTP 400 with the message."""
        mock_library_service.clear_library_data.side_effect = ValueError("Library root not configured")

        response = client.post("/api/web/library/clear-data")

        assert response.status_code == 400
        assert response.json() == {"detail": "Library root not configured"}

    def test_clear_data_active_scan_maps_to_409(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """An active-scan rejection (RuntimeError) should surface as HTTP 409 with the message."""
        mock_library_service.clear_library_data.side_effect = RuntimeError(
            "Cannot clear library while scan jobs are running. Cancel scans first."
        )

        response = client.post("/api/web/library/clear-data")

        assert response.status_code == 409
        assert response.json() == {"detail": "Cannot clear library while scan jobs are running. Cancel scans first."}

    def test_clear_data_generic_failure_maps_to_500_sanitized(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """An aggregate failure must map to 500 with a sanitized body, never a partial success."""
        mock_library_service.clear_library_data.side_effect = Exception("secret internal detail")

        response = client.post("/api/web/library/clear-data")

        assert response.status_code == 500
        assert response.json() == {"detail": "Failed to clear library data"}


@pytest.mark.unit
@pytest.mark.mocked
class TestClearLibraryDataAuth:
    """Tests for session-auth enforcement on the clear-data route."""

    def test_clear_data_requires_session_auth(self) -> None:
        """The clear-data endpoint must reject an unauthenticated request with 401."""
        test_app = FastAPI()
        test_app.include_router(library_router, prefix="/api/web")

        with TestClient(test_app) as test_client:
            response = test_client.post("/api/web/library/clear-data")

        assert response.status_code == 401
        assert response.json() == {"detail": "Missing Authorization header"}
