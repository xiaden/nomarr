from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.helpers.dto import NavidromeGeneratePlaylistsResult
from nomarr.helpers.exceptions import MisconfiguredError
from nomarr.interfaces.api.auth import verify_key
from nomarr.interfaces.api.v1.navidrome_v1_if import router as navidrome_router
from nomarr.interfaces.api.web.dependencies import get_navidrome_service


@pytest.fixture
def mock_navidrome_service() -> MagicMock:
    return MagicMock()


@pytest.fixture
def app(mock_navidrome_service: MagicMock) -> Iterator[FastAPI]:
    test_app = FastAPI()
    test_app.include_router(navidrome_router, prefix="/api")

    async def allow_key() -> None:
        return None

    test_app.dependency_overrides[verify_key] = allow_key
    test_app.dependency_overrides[get_navidrome_service] = lambda: mock_navidrome_service

    yield test_app

    test_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.integration
@pytest.mark.mocked
class TestSimilarTracksEndpoint:
    def test_success_returns_descriptor_payload(
        self,
        client: TestClient,
        mock_navidrome_service: MagicMock,
    ) -> None:
        mock_navidrome_service.get_similar_tracks.return_value = [
            {
                "title": "Song A",
                "artist": "Artist A",
                "album": "Album A",
                "album_artist": "Album Artist A",
                "duration_ms": 201000,
                "track_number": 4,
                "disc_number": 1,
                "year": 2024,
                "musicbrainz_track_id": "mb-track",
                "musicbrainz_recording_id": "mb-recording",
                "nomarr_file_key": "abc123",
                "score": 0.91,
            }
        ]

        response = client.post(
            "/api/v1/navidrome/similar-track",
            json={
                "seed": {
                    "title": "Seed",
                    "artist": "Artist",
                    "album": "Album",
                },
                "count": 10,
            },
        )

        assert response.status_code == 200
        assert response.json() == {
            "songs": [
                {
                    "title": "Song A",
                    "artist": "Artist A",
                    "album": "Album A",
                    "album_artist": "Album Artist A",
                    "duration_ms": 201000,
                    "track_number": 4,
                    "disc_number": 1,
                    "year": 2024,
                    "musicbrainz_track_id": "mb-track",
                    "musicbrainz_recording_id": "mb-recording",
                    "nomarr_file_key": "abc123",
                    "score": 0.91,
                }
            ]
        }
        mock_navidrome_service.get_similar_tracks.assert_called_once_with(
            seed_descriptor={
                "title": "Seed",
                "artist": "Artist",
                "album": "Album",
                "album_artist": "",
                "duration_ms": None,
                "track_number": None,
                "disc_number": None,
                "year": None,
                "musicbrainz_track_id": None,
                "musicbrainz_recording_id": None,
                "nomarr_file_key": None,
            },
            count=10,
            backbone_id="effnet",
        )

    def test_seed_unresolved_returns_404(
        self,
        client: TestClient,
        mock_navidrome_service: MagicMock,
    ) -> None:
        mock_navidrome_service.get_similar_tracks.side_effect = ValueError("Seed descriptor could not be resolved")

        response = client.post(
            "/api/v1/navidrome/similar-track",
            json={
                "seed": {
                    "title": "Seed",
                    "artist": "Artist",
                }
            },
        )

        assert response.status_code == 404
        assert response.json() == {"detail": "Seed descriptor could not be resolved"}


@pytest.mark.integration
@pytest.mark.mocked
class TestGeneratePlaylistsEndpoint:
    def test_misconfigured_error_returns_422(
        self,
        client: TestClient,
        mock_navidrome_service: MagicMock,
    ) -> None:
        mock_navidrome_service.generate_playlists.side_effect = MisconfiguredError(
            "library_key not configured",
        )

        response = client.post(
            "/api/v1/navidrome/playlist/generate",
            json={"user_id": "user-1"},
        )

        assert response.status_code == 422
        assert response.json() == {
            "detail": {
                "status": "misconfigured",
                "message": "library_key not configured",
            },
        }

    def test_no_data_result_returns_200_with_empty_playlists(
        self,
        client: TestClient,
        mock_navidrome_service: MagicMock,
    ) -> None:
        mock_navidrome_service.generate_playlists.return_value = NavidromeGeneratePlaylistsResult(
            status="no_data",
            message="No taste profile or no playlists generated",
            playlists=[],
        )

        response = client.post(
            "/api/v1/navidrome/playlist/generate",
            json={"user_id": "user-1"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "status": "no_data",
            "message": "No taste profile or no playlists generated",
            "playlists": [],
        }

    def test_success_returns_playlists_with_nd_ids(
        self,
        client: TestClient,
        mock_navidrome_service: MagicMock,
    ) -> None:
        mock_navidrome_service.generate_playlists.return_value = NavidromeGeneratePlaylistsResult(
            status="ok",
            message="",
            playlists=[
                {
                    "playlist_type": "familiar",
                    "playlist_name": "Familiar Favorites",
                    "file_ids": ["library_files/track-1"],
                },
            ],
        )
        mock_navidrome_service.resolve_files_to_nd.return_value = {
            "library_files/track-1": "nd-abc",
        }

        response = client.post(
            "/api/v1/navidrome/playlist/generate",
            json={"user_id": "user-1"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "message": "",
            "playlists": [
                {
                    "playlist_type": "familiar",
                    "playlist_name": "Familiar Favorites",
                    "track_nd_ids": ["nd-abc"],
                    "track_count": 1,
                },
            ],
        }
        mock_navidrome_service.resolve_files_to_nd.assert_called_once_with(
            ["library_files/track-1"],
        )

    def test_misconfigured_status_on_result_returns_422(
        self,
        client: TestClient,
        mock_navidrome_service: MagicMock,
    ) -> None:
        mock_navidrome_service.generate_playlists.return_value = NavidromeGeneratePlaylistsResult(
            status="misconfigured",
            message="some config error",
            playlists=[],
        )

        response = client.post(
            "/api/v1/navidrome/playlist/generate",
            json={"user_id": "user-1"},
        )

        assert response.status_code == 422
        assert response.json() == {
            "detail": {
                "status": "misconfigured",
                "message": "some config error",
            },
        }
