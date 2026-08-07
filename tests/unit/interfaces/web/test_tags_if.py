"""Tests for tags interface endpoints.

Covers:
- GET /tag/show (success, invalid path, unexpected error)
- DELETE /tag/remove (success, invalid path, unexpected error)
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web import tags_if
from nomarr.interfaces.api.web.dependencies import get_tagging_service

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def mock_tagging_service() -> MagicMock:
    """Provide a mocked tagging service dependency."""
    return MagicMock()


@pytest.fixture
def app(mock_tagging_service: MagicMock) -> Iterator[FastAPI]:
    """Provide a FastAPI app with mocked dependencies."""
    test_app = FastAPI()
    test_app.include_router(tags_if.router)

    async def allow_session() -> None:
        return None

    test_app.dependency_overrides[verify_session] = allow_session
    test_app.dependency_overrides[get_tagging_service] = lambda: mock_tagging_service

    yield test_app

    test_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Provide a test client for the tags endpoints."""
    return TestClient(app)


@pytest.mark.unit
@pytest.mark.mocked
class TestTagsEndpoints:
    """Test tags interface endpoints."""

    def test_show_tags_returns_response(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """GET /tag/show should return tags from file."""
        mock_tagging_service.namespace = "nomarr"
        mock_tagging_service.read_file_tags.return_value = {
            "genre": "rock",
            "mood": "energetic",
        }

        response = client.get("/tag/show", params={"path": "/music/song.flac"})

        assert response.status_code == 200
        data = response.json()
        assert data["path"] == "/music/song.flac"
        assert data["namespace"] == "nomarr"
        assert data["tags"] == {"genre": "rock", "mood": "energetic"}
        assert data["count"] == 2
        mock_tagging_service.read_file_tags.assert_called_once_with("/music/song.flac", "nomarr")

    def test_show_tags_returns_400_for_invalid_path(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """GET /tag/show should return 400 for invalid file path."""
        mock_tagging_service.namespace = "nomarr"
        mock_tagging_service.read_file_tags.side_effect = ValueError("invalid path")

        response = client.get("/tag/show", params={"path": "/invalid/path"})

        assert response.status_code == 400
        assert response.json() == {"detail": "Invalid file path"}

    def test_show_tags_returns_500_on_unexpected_error(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """GET /tag/show should return 500 on unexpected error."""
        mock_tagging_service.namespace = "nomarr"
        mock_tagging_service.read_file_tags.side_effect = RuntimeError("internal error")

        response = client.get("/tag/show", params={"path": "/music/song.flac"})

        assert response.status_code == 500
        assert "Failed to read tags" in response.json()["detail"]

    def test_remove_tags_returns_response(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """DELETE /tag/remove should remove tags and return count."""
        mock_tagging_service.namespace = "nomarr"
        mock_tagging_service.remove_file_tags.return_value = 5

        response = client.delete("/tag/remove", params={"path": "/music/song.flac"})

        assert response.status_code == 200
        data = response.json()
        assert data["path"] == "/music/song.flac"
        assert data["namespace"] == "nomarr"
        assert data["removed"] == 5
        mock_tagging_service.remove_file_tags.assert_called_once_with("/music/song.flac", "nomarr")

    def test_remove_tags_returns_400_for_invalid_path(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """DELETE /tag/remove should return 400 for invalid file path."""
        mock_tagging_service.namespace = "nomarr"
        mock_tagging_service.remove_file_tags.side_effect = ValueError("invalid path")

        response = client.delete("/tag/remove", params={"path": "/invalid/path"})

        assert response.status_code == 400
        assert response.json() == {"detail": "Invalid file path"}

    def test_remove_tags_returns_500_on_unexpected_error(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """DELETE /tag/remove should return 500 on unexpected error."""
        mock_tagging_service.namespace = "nomarr"
        mock_tagging_service.remove_file_tags.side_effect = RuntimeError("internal error")

        response = client.delete("/tag/remove", params={"path": "/music/song.flac"})

        assert response.status_code == 500
        assert "Failed to remove tags" in response.json()["detail"]
