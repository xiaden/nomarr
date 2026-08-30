"""API-level regression tests for natural metadata entity identities."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, call

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_metadata_service
from nomarr.interfaces.api.web.metadata_if import router

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def metadata_service() -> MagicMock:
    """Provide a metadata service double for endpoint tests."""
    return MagicMock()


@pytest.fixture
def client(metadata_service: MagicMock) -> Iterator[TestClient]:
    """Build a client with authentication and metadata dependencies overridden."""
    app = FastAPI()
    app.include_router(router, prefix="/api/web")

    async def allow_session() -> None:
        return None

    app.dependency_overrides[verify_session] = allow_session
    app.dependency_overrides[get_metadata_service] = lambda: metadata_service
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.unit
@pytest.mark.mocked
def test_artist_to_albums_to_tracks_round_trips_natural_ids(
    client: TestClient,
    metadata_service: MagicMock,
) -> None:
    """Non-numeric artist and album values must survive the complete browse journey."""
    metadata_service.get_entity.side_effect = lambda _collection, entity_id: {
        "id": entity_id,
        "display_name": entity_id,
        "song_count": 1,
    }
    metadata_service.list_albums_for_artist.return_value = [
        {"id": "Master of Puppets", "display_name": "Master of Puppets", "song_count": 1}
    ]
    metadata_service.list_songs_for_entity.return_value = {
        "song_ids": [42],
        "total": 1,
        "limit": 100,
        "offset": 0,
    }

    entity_response = client.get("/api/web/metadata/artist/Metallica")
    numeric_entity_response = client.get("/api/web/metadata/artist/1999")
    albums_response = client.get("/api/web/metadata/artist/Metallica/album")
    tracks_response = client.get(
        "/api/web/metadata/album/Master%20of%20Puppets/song",
        params={"name": "album"},
    )

    assert entity_response.status_code == 200
    assert entity_response.json()["entity_id"] == "Metallica"
    assert numeric_entity_response.status_code == 200
    assert numeric_entity_response.json()["entity_id"] == "1999"
    assert albums_response.status_code == 200
    assert albums_response.json()[0]["entity_id"] == "Master of Puppets"
    assert tracks_response.status_code == 200
    assert tracks_response.json()["song_ids"] == [42]
    metadata_service.list_albums_for_artist.assert_called_once_with("Metallica", limit=100)
    metadata_service.list_artists_for_album.assert_not_called()
    metadata_service.list_songs_for_entity.assert_called_once_with(
        "album", "Master of Puppets", "album", limit=100, offset=0
    )
    assert metadata_service.get_entity.call_args_list == [
        call("artist", "Metallica"),
        call("artist", "1999"),
    ]
