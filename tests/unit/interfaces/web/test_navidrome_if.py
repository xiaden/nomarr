from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_navidrome_service
from nomarr.interfaces.api.web.navidrome_if import router as navidrome_router


@pytest.fixture
def mock_navidrome_service() -> MagicMock:
    """Provide a mocked NavidromeService dependency."""
    return MagicMock()


@pytest.fixture
def app(mock_navidrome_service: MagicMock) -> Iterator[FastAPI]:
    """Build a minimal FastAPI app for Navidrome web endpoints."""
    test_app = FastAPI()
    test_app.include_router(navidrome_router, prefix="/api/web")

    async def allow_session() -> None:
        return None

    test_app.dependency_overrides[verify_session] = allow_session
    test_app.dependency_overrides[get_navidrome_service] = lambda: mock_navidrome_service

    yield test_app

    test_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Create a TestClient for the minimal app."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.unit
@pytest.mark.mocked
class TestNavidromeLegacyPushEndpoints:
    """Legacy backend push/sync endpoints should be disabled."""

    def test_playlist_push_endpoint_returns_410(self, client: TestClient, mock_navidrome_service: MagicMock) -> None:
        response = client.post(
            "/api/web/navidrome/playlist/push",
            json={"file_ids": ["file-1"], "playlist_name": "Test"},
        )

        assert response.status_code == 410
        assert "removed" in response.json()["detail"]
        mock_navidrome_service.push_static_playlist.assert_not_called()

    def test_sync_song_endpoint_returns_410(self, client: TestClient, mock_navidrome_service: MagicMock) -> None:
        response = client.post("/api/web/navidrome/sync-song")

        assert response.status_code == 410
        assert "removed" in response.json()["detail"]
        mock_navidrome_service.sync_navidrome.assert_not_called()

    def test_personal_playlist_trigger_endpoint_returns_410(
        self,
        client: TestClient,
        mock_navidrome_service: MagicMock,
    ) -> None:
        response = client.post("/api/web/navidrome/generate-personal-playlists")

        assert response.status_code == 410
        assert "removed" in response.json()["detail"]
        mock_navidrome_service.trigger_personal_playlists.assert_not_called()
