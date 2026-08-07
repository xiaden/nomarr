"""Tests for config interface endpoints.

Covers:
- GET /config (success, unexpected error)
- POST /config (success, non-editable key, unexpected error)
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.helpers.dto.config_dto import GetInternalInfoResult, WebConfigResult
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web import config_if
from nomarr.interfaces.api.web.dependencies import get_config_service

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def mock_config_service() -> MagicMock:
    """Provide a mocked config service dependency."""
    return MagicMock()


@pytest.fixture
def app(mock_config_service: MagicMock) -> Iterator[FastAPI]:
    """Provide a FastAPI app with mocked dependencies."""
    test_app = FastAPI()
    test_app.include_router(config_if.router)

    async def allow_session() -> None:
        return None

    test_app.dependency_overrides[verify_session] = allow_session
    test_app.dependency_overrides[get_config_service] = lambda: mock_config_service

    yield test_app

    test_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Provide a test client for the config endpoints."""
    return TestClient(app)


@pytest.mark.unit
@pytest.mark.mocked
class TestConfigEndpoints:
    """Test config interface endpoints."""

    def test_get_config_returns_response(
        self,
        client: TestClient,
        mock_config_service: MagicMock,
    ) -> None:
        """GET /config should return config response."""
        web_result = WebConfigResult(
            config={"key1": "value1", "key2": "value2"},
            internal_info=GetInternalInfoResult(
                namespace="nomarr",
                version_tag="v1.0.0",
                min_duration_s=30,
                allow_short=False,
                poll_interval=60,
                library_scan_poll_interval=300,
                worker_enabled=True,
            ),
            worker_enabled=True,
        )
        mock_config_service.get_config_for_web.return_value = web_result

        response = client.get("/config")

        assert response.status_code == 200
        data = response.json()
        assert data["key1"] == "value1"
        assert data["key2"] == "value2"
        assert data["worker_enabled"] is True
        mock_config_service.get_config_for_web.assert_called_once_with(worker_service=None)

    def test_get_config_returns_500_on_unexpected_error(
        self,
        client: TestClient,
        mock_config_service: MagicMock,
    ) -> None:
        """GET /config should return 500 on unexpected error."""
        mock_config_service.get_config_for_web.side_effect = RuntimeError("internal error")

        response = client.get("/config")

        assert response.status_code == 500
        assert "Failed to get configuration" in response.json()["detail"]

    def test_update_config_returns_response(
        self,
        client: TestClient,
        mock_config_service: MagicMock,
    ) -> None:
        """POST /config with editable key should update config."""
        # Patch WEB_EDITABLE_KEYS to include our test key
        with patch.object(config_if, "WEB_EDITABLE_KEYS", frozenset(["editable_key"])):
            response = client.post("/config", json={"key": "editable_key", "value": "new_value"})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "updated" in data["message"]
        mock_config_service.set.assert_called_once_with("editable_key", "new_value")

    def test_update_config_returns_400_for_non_editable_key(
        self,
        client: TestClient,
    ) -> None:
        """POST /config with non-editable key should return 400."""
        # Patch WEB_EDITABLE_KEYS to be empty so any key is non-editable
        with patch.object(config_if, "WEB_EDITABLE_KEYS", frozenset()):
            response = client.post("/config", json={"key": "non_editable_key", "value": "value"})

        assert response.status_code == 400
        assert "cannot be edited" in response.json()["detail"]

    def test_update_config_returns_500_on_unexpected_error(
        self,
        client: TestClient,
        mock_config_service: MagicMock,
    ) -> None:
        """POST /config should return 500 on unexpected error."""
        mock_config_service.set.side_effect = RuntimeError("internal error")

        with patch.object(config_if, "WEB_EDITABLE_KEYS", frozenset(["editable_key"])):
            response = client.post("/config", json={"key": "editable_key", "value": "value"})

        assert response.status_code == 500
        assert "Failed to update configuration" in response.json()["detail"]
