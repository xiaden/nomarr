"""Tests for the API key web interface (``nomarr.interfaces.api.web.api_key_if``).

Focus: the clean-break wire contract for ``/api/web/api-key`` —
``ApiKeyResponse{api_key}`` on GET (``""``) and POST (``/regenerate``), the
session-auth requirement on both routes, and the delegation of each to the
key service.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.interfaces.api.auth import get_key_service, verify_session
from nomarr.interfaces.api.web.api_key_if import router as api_key_router

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def mock_key_service() -> MagicMock:
    """Provide a mocked key-management service dependency."""
    return MagicMock()


@pytest.fixture
def app(mock_key_service: MagicMock) -> Iterator[FastAPI]:
    """Build a minimal FastAPI app for API key endpoints."""
    test_app = FastAPI()
    test_app.include_router(api_key_router, prefix="/api/web")

    async def allow_session() -> None:
        return None

    test_app.dependency_overrides[verify_session] = allow_session
    test_app.dependency_overrides[get_key_service] = lambda: mock_key_service

    yield test_app

    test_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Create a TestClient for the minimal app."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.unit
@pytest.mark.mocked
class TestApiKeyRoutes:
    """Tests for the API key web routes."""

    def test_get_api_key_returns_current_key(
        self,
        client: TestClient,
        mock_key_service: MagicMock,
    ) -> None:
        """GET /api-key should return the current key in the flat envelope."""
        mock_key_service.get_or_create_api_key.return_value = "secret-key-123"

        response = client.get("/api/web/api-key")

        assert response.status_code == 200
        assert response.json() == {"api_key": "secret-key-123"}
        mock_key_service.get_or_create_api_key.assert_called_once_with()

    def test_regenerate_api_key_returns_new_key(
        self,
        client: TestClient,
        mock_key_service: MagicMock,
    ) -> None:
        """POST /api-key/regenerate should return the regenerated key."""
        mock_key_service.regenerate_api_key.return_value = "regenerated-key"

        response = client.post("/api/web/api-key/regenerate")

        assert response.status_code == 200
        assert response.json() == {"api_key": "regenerated-key"}
        mock_key_service.regenerate_api_key.assert_called_once_with()

    def test_requires_session_auth_without_override(self) -> None:
        """Both routes must reject an unauthenticated request with 401."""
        test_app = FastAPI()
        test_app.include_router(api_key_router, prefix="/api/web")

        with TestClient(test_app) as test_client:
            get_response = test_client.get("/api/web/api-key")
            post_response = test_client.post("/api/web/api-key/regenerate")

        assert get_response.status_code == 401
        assert get_response.json() == {"detail": "Missing Authorization header"}
        assert post_response.status_code == 401
        assert post_response.json() == {"detail": "Missing Authorization header"}
