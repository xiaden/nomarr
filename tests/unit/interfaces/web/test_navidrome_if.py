from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.helpers.dto.navidrome_dto import NavidromeGeneratePlaylistsResult, NavidromePersonalPlaylistEntry
from nomarr.helpers.exceptions import MisconfiguredError
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_navidrome_service
from nomarr.interfaces.api.web.navidrome_if import router as navidrome_router


@pytest.mark.unit
@pytest.mark.mocked
class TestNavidromeLegacySyncEndpoint:
    """sync-song endpoint is disabled (410)."""

    def test_sync_song_endpoint_returns_410(self, client: TestClient, mock_navidrome_service: MagicMock) -> None:
        response = client.post("/api/web/navidrome/sync-song")

        assert response.status_code == 410
        assert "removed" in response.json()["detail"]
        mock_navidrome_service.sync_navidrome.assert_not_called()


@pytest.mark.unit
@pytest.mark.mocked
class TestNavidromePushPlaylistEndpoint:
    """playlist/push endpoint resolves file IDs to track descriptors."""

    def test_push_playlist_returns_descriptors(self, client: TestClient, mock_navidrome_service: MagicMock) -> None:
        mock_navidrome_service.resolve_files_to_descriptors.return_value = {
            "library_files/f1": {
                "title": "Song A",
                "artist": "Artist A",
                "album": "Album A",
                "album_artist": "Artist A",
                "duration_ms": 200000,
                "track_number": 1,
                "disc_number": 1,
                "year": 2020,
                "nomarr_file_key": "f1",
            },
            "library_files/f2": {
                "title": "Song B",
                "artist": "Artist B",
                "album": "Album B",
                "album_artist": "Artist B",
                "duration_ms": None,
                "track_number": None,
                "disc_number": None,
                "year": None,
                "nomarr_file_key": "f2",
            },
        }

        response = client.post(
            "/api/web/navidrome/playlist/push",
            json={
                "file_ids": ["library_files:f1", "library_files:f2"],
                "playlist_name": "Test Playlist",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["playlist_name"] == "Test Playlist"
        assert data["track_count"] == 2
        assert len(data["songs"]) == 2
        assert data["songs"][0]["title"] == "Song A"
        assert data["songs"][0]["artist"] == "Artist A"

    def test_push_playlist_empty_when_no_descriptors(
        self, client: TestClient, mock_navidrome_service: MagicMock
    ) -> None:
        mock_navidrome_service.resolve_files_to_descriptors.return_value = {}

        response = client.post(
            "/api/web/navidrome/playlist/push",
            json={"file_ids": ["library_files:f1"], "playlist_name": "Test"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["track_count"] == 0
        assert data["songs"] == []


@pytest.mark.unit
@pytest.mark.mocked
class TestNavidromeGeneratePersonalPlaylistsEndpoint:
    """generate-personal-playlists endpoint returns playlist descriptors."""

    def test_generate_personal_playlists_returns_descriptors(
        self, client: TestClient, mock_navidrome_service: MagicMock
    ) -> None:
        mock_navidrome_service.generate_personal_playlists.return_value = NavidromeGeneratePlaylistsResult(
            status="ok",
            message="",
            playlists=[
                NavidromePersonalPlaylistEntry(
                    playlist_type="top_tracks",
                    playlist_name="Your Top Tracks",
                    file_ids=["library_files/f1"],
                )
            ],
        )
        mock_navidrome_service.resolve_files_to_descriptors.return_value = {
            "library_files/f1": {
                "title": "Top Track",
                "artist": "Some Artist",
                "album": "Some Album",
                "album_artist": "Some Artist",
                "duration_ms": 180000,
                "track_number": 1,
                "disc_number": 1,
                "year": 2021,
                "nomarr_file_key": "f1",
            }
        }

        response = client.post("/api/web/navidrome/generate-personal-playlists")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert len(data["playlists"]) == 1
        assert data["playlists"][0]["playlist_name"] == "Your Top Tracks"
        assert len(data["playlists"][0]["songs"]) == 1
        assert data["playlists"][0]["songs"][0]["title"] == "Top Track"

    def test_generate_personal_playlists_422_when_misconfigured(
        self, client: TestClient, mock_navidrome_service: MagicMock
    ) -> None:
        mock_navidrome_service.generate_personal_playlists.side_effect = MisconfiguredError(
            "navidrome_api_user not configured"
        )

        response = client.post("/api/web/navidrome/generate-personal-playlists")

        assert response.status_code == 422

    def test_generate_personal_playlists_no_data(self, client: TestClient, mock_navidrome_service: MagicMock) -> None:
        mock_navidrome_service.generate_personal_playlists.return_value = NavidromeGeneratePlaylistsResult(
            status="no_data",
            message="Not enough play history",
            playlists=[],
        )

        response = client.post("/api/web/navidrome/generate-personal-playlists")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "no_data"
        assert data["playlists"] == []


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
