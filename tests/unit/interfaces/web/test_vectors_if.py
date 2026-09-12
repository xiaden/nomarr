"""Tests for the vector search interface endpoints.

Covers the opaque ``nom1`` SongLocator wire contract:
- ``MissingSeedVectorError`` maps to 404 with guidance (track not processed).
- ``VectorIndexUnavailableError`` maps to 503.
- Successful searches echo opaque locator tokens, never generated ids.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.vector_dataclass import SongVector, VectorMatch
from nomarr.helpers.song_locator_codec import encode_song_locator
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_library_service, get_vector_search_service
from nomarr.interfaces.api.web.vectors_if import router as vectors_router
from nomarr.services.domain.vector_search_svc import (
    MissingSeedVectorError,
    VectorIndexUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_LIBRARY = LibraryIdentity(
    library_uuid="6313b0d3-d270-47a8-9e0d-21e8255107e3",
    name="Music",
    root_path="/music",
)
_SEED = SongIdentity(library=_LIBRARY, normalized_path="songs/seed.mp3")
_SEED_TOKEN = encode_song_locator(_SEED)
_TARGET = SongIdentity(library=_LIBRARY, normalized_path="songs/target.mp3")
_TARGET_TOKEN = encode_song_locator(_TARGET)


@pytest.fixture
def mock_vector_search_service() -> MagicMock:
    """Provide a mocked vector search service dependency."""
    return MagicMock()


@pytest.fixture
def mock_library_service() -> MagicMock:
    """Provide a mocked library service that resolves tokens to the seed locator."""
    service = MagicMock()
    service.build_song_locator.return_value = _SEED
    return service


@pytest.fixture
def app(
    mock_vector_search_service: MagicMock,
    mock_library_service: MagicMock,
) -> Iterator[FastAPI]:
    """Build a minimal FastAPI app for the vector endpoints."""
    test_app = FastAPI()
    test_app.include_router(vectors_router)

    async def allow_session() -> None:
        return None

    test_app.dependency_overrides[verify_session] = allow_session
    test_app.dependency_overrides[get_vector_search_service] = lambda: mock_vector_search_service
    test_app.dependency_overrides[get_library_service] = lambda: mock_library_service

    yield test_app

    test_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create a TestClient for the minimal app."""
    return TestClient(app)


_SEARCH_BODY = {
    "file_id": _SEED_TOKEN,
    "backbone_id": "effnet",
    "limit": 10,
    "min_score": 0.0,
}


@pytest.mark.unit
@pytest.mark.mocked
class TestVectorSearchContract:
    """Tests for the vector search error-to-HTTP mapping and opaque wire echo."""

    def test_missing_seed_vector_maps_to_404_with_guidance(
        self,
        client: TestClient,
        mock_vector_search_service: MagicMock,
    ) -> None:
        """A missing seed vector should map to 404 with process-guidance detail."""
        mock_vector_search_service.search_similar_tracks.side_effect = MissingSeedVectorError(
            "No vector found for backbone 'effnet'. Track may not have been processed yet."
        )

        response = client.post("/vector/search", json=_SEARCH_BODY)

        assert response.status_code == 404
        assert "No vector found for backbone 'effnet'" in response.json()["detail"]
        assert "not have been processed yet" in response.json()["detail"]

    def test_index_unavailable_maps_to_503(
        self,
        client: TestClient,
        mock_vector_search_service: MagicMock,
    ) -> None:
        """An unavailable vector index should map to 503."""
        mock_vector_search_service.search_similar_tracks.side_effect = VectorIndexUnavailableError(
            "No vector index available for backbone 'effnet'."
        )

        response = client.post("/vector/search", json=_SEARCH_BODY)

        assert response.status_code == 503
        assert "No vector index available" in response.json()["detail"]

    def test_success_maps_results_to_opaque_locators(
        self,
        client: TestClient,
        mock_vector_search_service: MagicMock,
    ) -> None:
        """A successful search should echo opaque locator tokens, not integer ids."""
        mock_vector_search_service.search_similar_tracks.return_value = [
            VectorMatch(song=_TARGET, backbone="effnet", score=0.9, vector=(0.9, 0.1)),
        ]

        response = client.post("/vector/search", json=_SEARCH_BODY)

        assert response.status_code == 200
        assert response.json() == {
            "results": [
                {"file_id": _TARGET_TOKEN, "score": 0.9, "vector": [0.9, 0.1]},
            ]
        }

    def test_none_vector_matches_are_excluded(
        self,
        client: TestClient,
        mock_vector_search_service: MagicMock,
    ) -> None:
        """Matches with ``vector=None`` are skipped under the current filtering contract."""
        mock_vector_search_service.search_similar_tracks.return_value = [
            VectorMatch(song=_TARGET, backbone="effnet", score=0.9, vector=(0.9, 0.1)),
            VectorMatch(song=_SEED, backbone="effnet", score=0.7, vector=None),
        ]

        response = client.post("/vector/search", json=_SEARCH_BODY)

        assert response.status_code == 200
        assert response.json() == {
            "results": [
                {"file_id": _TARGET_TOKEN, "score": 0.9, "vector": [0.9, 0.1]},
            ]
        }

    def test_search_passes_the_resolved_locator_to_the_service(
        self,
        client: TestClient,
        mock_vector_search_service: MagicMock,
    ) -> None:
        """The service must receive the semantic locator, never an integer handle."""
        mock_vector_search_service.search_similar_tracks.return_value = []

        response = client.post("/vector/search", json=_SEARCH_BODY)

        assert response.status_code == 200
        assert mock_vector_search_service.search_similar_tracks.call_args.kwargs["song"] == _SEED


@pytest.mark.unit
@pytest.mark.mocked
class TestGetTrackVectorContract:
    """Tests for the GET /vector/track endpoint over a typed SongVector result."""

    def _song_vector(self, vector: tuple[float, ...]) -> SongVector:
        return SongVector(
            song=_SEED,
            backbone="effnet",
            vector=vector,
            model_suite_hash="suite",
            num_segments=1,
            segmentation_hash=None,
            genres=None,
        )

    def test_success_adapts_song_vector_to_wire_shape(
        self,
        client: TestClient,
        mock_vector_search_service: MagicMock,
    ) -> None:
        """A domain SongVector is adapted to exactly {file_id, backbone_id, vector}."""
        mock_vector_search_service.get_track_vector.return_value = self._song_vector((0.9, 0.1, 0.5))

        response = client.get("/vector/track", params={"backbone_id": "effnet", "file_id": _SEED_TOKEN})

        assert response.status_code == 200
        assert response.json() == {
            "file_id": _SEED_TOKEN,
            "backbone_id": "effnet",
            "vector": [0.9, 0.1, 0.5],
        }
        assert response.json().keys() == {"file_id", "backbone_id", "vector"}
        assert mock_vector_search_service.get_track_vector.call_args.args[1] == _SEED

    def test_missing_vector_maps_to_404(
        self,
        client: TestClient,
        mock_vector_search_service: MagicMock,
    ) -> None:
        """A None SongVector result maps to 404 with the locator/backbone detail."""
        mock_vector_search_service.get_track_vector.return_value = None

        response = client.get("/vector/track", params={"backbone_id": "effnet", "file_id": _SEED_TOKEN})

        assert response.status_code == 404
        assert _SEED_TOKEN in response.json()["detail"]
        assert "effnet" in response.json()["detail"]
