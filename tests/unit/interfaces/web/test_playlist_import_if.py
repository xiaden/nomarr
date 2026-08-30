"""Unit tests for the playlist-import web interface (mechanism-A library scoping).

Verifies that ``ConvertPlaylistRequest.library_id`` is a natural library name
resolved to a domain ``Library`` (or None for global scope), that an unknown
name maps to HTTP 422, and that credential/error handling is correct.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.exceptions import PlaylistConversionError
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_library_service, get_playlist_import_service
from nomarr.interfaces.api.web.playlist_import_if import router as playlist_import_router

if TYPE_CHECKING:
    from collections.abc import Iterator

SPOTIFY_URL = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"


def make_library(*, name: str = "Test Library") -> Library:
    """Build a domain ``Library`` fixture (natural identity)."""
    return Library(
        name=name,
        root_path="D:/Music/Test",
        is_enabled=True,
        watch_mode="off",
        file_write_mode="full",
        library_auto_write=False,
    )


def _conversion_result() -> SimpleNamespace:
    """Build a playlist-conversion result matching ``ConvertPlaylistResponse.from_dto``."""
    return SimpleNamespace(
        playlist_metadata=SimpleNamespace(
            name="My Playlist",
            description=None,
            track_count=2,
            source_platform="spotify",
            source_url=SPOTIFY_URL,
        ),
        m3u_content="#EXTM3U\n",
        total_tracks=2,
        matched_count=2,
        exact_matches=1,
        fuzzy_matches=1,
        ambiguous_count=0,
        not_found_count=0,
        match_rate=1.0,
        get_unmatched=list,
        get_ambiguous=list,
        match_results=[],
    )


@pytest.fixture
def mock_library_service() -> MagicMock:
    """Provide a mocked library service dependency."""
    return MagicMock()


@pytest.fixture
def mock_playlist_service() -> MagicMock:
    """Provide a mocked playlist-import service dependency."""
    return MagicMock()


@pytest.fixture
def app(
    mock_library_service: MagicMock,
    mock_playlist_service: MagicMock,
) -> Iterator[FastAPI]:
    """Build a minimal FastAPI app for playlist-import endpoints."""
    test_app = FastAPI()
    test_app.include_router(playlist_import_router, prefix="/api/web")

    async def allow_session() -> None:
        return None

    test_app.dependency_overrides[verify_session] = allow_session
    test_app.dependency_overrides[get_library_service] = lambda: mock_library_service
    test_app.dependency_overrides[get_playlist_import_service] = lambda: mock_playlist_service

    yield test_app

    test_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Create a TestClient for the minimal app."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.unit
@pytest.mark.mocked
class TestPlaylistConvertLibraryScoping:
    """Tests for natural-name library scoping of playlist conversion."""

    def test_convert_scopes_to_library_by_name(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_playlist_service: MagicMock,
    ) -> None:
        """``library_id`` should be resolved to a domain ``Library`` and forwarded."""
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library
        mock_playlist_service.convert_playlist.return_value = _conversion_result()

        response = client.post(
            "/api/web/playlist-import/convert",
            json={"playlist_url": SPOTIFY_URL, "library_id": "Test Library"},
        )

        assert response.status_code == 200
        assert response.json()["total_tracks"] == 2
        mock_library_service.get_library_by_name.assert_called_once_with("Test Library")
        assert isinstance(mock_library_service.get_library_by_name.call_args.args[0], str)
        mock_playlist_service.convert_playlist.assert_called_once_with(
            playlist_url=SPOTIFY_URL,
            library=library,
        )

    def test_convert_global_when_no_library_id(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_playlist_service: MagicMock,
    ) -> None:
        """Omitting ``library_id`` should run conversion with a global (None) scope."""
        mock_playlist_service.convert_playlist.return_value = _conversion_result()

        response = client.post(
            "/api/web/playlist-import/convert",
            json={"playlist_url": SPOTIFY_URL},
        )

        assert response.status_code == 200
        mock_library_service.get_library_by_name.assert_not_called()
        mock_playlist_service.convert_playlist.assert_called_once_with(
            playlist_url=SPOTIFY_URL,
            library=None,
        )

    def test_convert_returns_422_when_library_missing(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_playlist_service: MagicMock,
    ) -> None:
        """An unknown library name should map to HTTP 422 and skip conversion."""
        mock_library_service.get_library_by_name.return_value = None

        response = client.post(
            "/api/web/playlist-import/convert",
            json={"playlist_url": SPOTIFY_URL, "library_id": "Missing Library"},
        )

        assert response.status_code == 422
        assert response.json() == {"detail": "Unknown library"}
        mock_library_service.get_library_by_name.assert_called_once_with("Missing Library")
        mock_playlist_service.convert_playlist.assert_not_called()

    def test_convert_returns_400_on_conversion_error(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_playlist_service: MagicMock,
    ) -> None:
        """PlaylistConversionError should surface as HTTP 400 with the raw message."""
        mock_playlist_service.convert_playlist.side_effect = PlaylistConversionError("bad url")

        response = client.post(
            "/api/web/playlist-import/convert",
            json={"playlist_url": "https://example.com/bad"},
        )

        assert response.status_code == 400
        assert response.json() == {"detail": "bad url"}

    def test_convert_returns_500_on_generic_error(
        self,
        client: TestClient,
        mock_playlist_service: MagicMock,
    ) -> None:
        """Unexpected service errors should surface as HTTP 500."""
        mock_playlist_service.convert_playlist.side_effect = RuntimeError("internal error")

        response = client.post(
            "/api/web/playlist-import/convert",
            json={"playlist_url": SPOTIFY_URL},
        )

        assert response.status_code == 500

    def test_spotify_status_when_configured(self, client: TestClient, mock_playlist_service: MagicMock) -> None:
        """GET spotify-status should report configured credentials."""
        mock_playlist_service.has_spotify_credentials.return_value = True

        response = client.get("/api/web/playlist-import/spotify-status")

        assert response.status_code == 200
        assert response.json()["configured"] is True

    def test_spotify_status_when_not_configured(self, client: TestClient, mock_playlist_service: MagicMock) -> None:
        """GET spotify-status should report missing credentials."""
        mock_playlist_service.has_spotify_credentials.return_value = False

        response = client.get("/api/web/playlist-import/spotify-status")

        assert response.status_code == 200
        assert response.json()["configured"] is False
        assert "not configured" in response.json()["message"]
