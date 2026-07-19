"""Tests for auth interface endpoints.

Covers:
- POST /authentication/login (success, wrong password, missing password, missing key service)
- POST /authentication/logout (success)
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web import auth_if


@pytest.fixture
def app() -> Iterator[FastAPI]:
    """Provide a FastAPI app with mocked dependencies."""
    test_app = FastAPI()
    test_app.include_router(auth_if.router)

    async def allow_session() -> None:
        return None

    test_app.dependency_overrides[verify_session] = allow_session

    yield test_app

    test_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Provide a test client for the auth endpoints."""
    return TestClient(app)


@pytest.mark.unit
@pytest.mark.mocked
class TestAuthEndpoints:
    """Test auth interface endpoints."""

    def test_login_returns_session_token(
        self,
        client: TestClient,
    ) -> None:
        """POST /authentication/login with valid password should return session token."""
        with (
            patch.object(auth_if, "get_admin_password_hash", return_value="hashed_password"),
            patch.object(auth_if, "verify_password", return_value=True),
            patch.object(auth_if, "create_session", return_value="test_session_token"),
        ):
            response = client.post("/authentication/login", json={"password": "correct_password"})

        assert response.status_code == 200
        data = response.json()
        assert data["session_token"] == "test_session_token"
        assert data["expires_in"] == 86400

    def test_login_returns_403_when_password_incorrect(
        self,
        client: TestClient,
    ) -> None:
        """POST /authentication/login with wrong password should return 403."""
        with (
            patch.object(auth_if, "get_admin_password_hash", return_value="hashed_password"),
            patch.object(auth_if, "verify_password", return_value=False),
        ):
            response = client.post("/authentication/login", json={"password": "wrong_password"})

        assert response.status_code == 403
        assert response.json() == {"detail": "Invalid password"}

    def test_login_returns_422_when_password_missing(
        self,
        client: TestClient,
    ) -> None:
        """POST /authentication/login without password should return 422."""
        response = client.post("/authentication/login", json={})

        assert response.status_code == 422

    def test_login_returns_500_when_admin_password_not_configured(
        self,
        client: TestClient,
    ) -> None:
        """POST /authentication/login should return 500 when admin password is not initialized."""
        with patch.object(auth_if, "get_admin_password_hash", side_effect=RuntimeError("not configured")):
            response = client.post("/authentication/login", json={"password": "test"})

        assert response.status_code == 500
        assert response.json() == {"detail": "Admin authentication not configured"}

    def test_logout_returns_success(
        self,
        client: TestClient,
        app: FastAPI,
    ) -> None:
        """POST /authentication/logout with valid session should return success."""
        from unittest.mock import MagicMock

        from fastapi import Request

        # Create a mock Request object with Authorization header
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"Authorization": "Bearer test_session"}

        # Override verify_session to return the mock request
        async def mock_verify_session() -> Request:
            return mock_request

        app.dependency_overrides[verify_session] = mock_verify_session

        with patch.object(auth_if, "invalidate_session") as mock_invalidate:
            response = client.post(
                "/authentication/logout",
                headers={"Authorization": "Bearer test_session"},
            )

        assert response.status_code == 200
        assert response.json() == {"status": "logged_out"}
        mock_invalidate.assert_called_once_with("test_session")
