"""Tests for the vector search interface endpoints.

Covers ``POST /vector/search`` error-to-HTTP mapping for the changed
vector search contract:
- ``MissingSeedVectorError`` maps to 404 with guidance (track not processed).
- ``VectorIndexUnavailableError`` maps to 503.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.vector_dataclass import SongVector
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_vector_search_service
from nomarr.interfaces.api.web.vectors_if import router as vectors_router
from nomarr.services.domain.vector_search_svc import (
    MissingSeedVectorError,
    VectorIndexUnavailableError,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def mock_vector_search_service() -> MagicMock:
    """Provide a mocked vector search service dependency."""
    return MagicMock()


@pytest.fixture
def app(mock_vector_search_service: MagicMock) -> Iterator[FastAPI]:
    """Build a minimal FastAPI app for the vector endpoints."""
    test_app = FastAPI()
    test_app.include_router(vectors_router)

    async def allow_session() -> None:
        return None

    test_app.dependency_overrides[verify_session] = allow_session
    test_app.dependency_overrides[get_vector_search_service] = lambda: mock_vector_search_service

    yield test_app

    test_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create a TestClient for the minimal app."""
    return TestClient(app)


_SEARCH_BODY = {
    "file_id": "1",
    "backbone_id": "effnet",
    "limit": 10,
    "min_score": 0.0,
}


@pytest.mark.unit
@pytest.mark.mocked
class TestVectorSearchContract:
    """Tests for the vector search error-to-HTTP mapping."""

    def test_missing_seed_vector_maps_to_404_with_guidance(
        self,
        client: TestClient,
        mock_vector_search_service: MagicMock,
    ) -> None:
        """A missing seed vector should map to 404 with process-guidance detail."""
        mock_vector_search_service.search_similar_tracks.side_effect = MissingSeedVectorError(
            "No vector found for file '1' with backbone 'effnet'. Track may not have been processed yet."
        )

        response = client.post("/vector/search", json=_SEARCH_BODY)

        assert response.status_code == 404
        assert "No vector found for file '1'" in response.json()["detail"]
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

    def test_success_maps_results(
        self,
        client: TestClient,
        mock_vector_search_service: MagicMock,
    ) -> None:
        """A successful search should return mapped result items."""
        mock_vector_search_service.search_similar_tracks.return_value = [
            {"file_id": 1, "score": 0.9, "vector": [0.9, 0.1]},
        ]

        response = client.post("/vector/search", json=_SEARCH_BODY)

        assert response.status_code == 200
        assert response.json() == {
            "results": [
                {"file_id": 1, "score": 0.9, "vector": [0.9, 0.1]},
            ]
        }


@pytest.mark.unit
@pytest.mark.mocked
class TestGetTrackVectorContract:
    """Tests for the GET /vector/track endpoint over a typed SongVector result."""

    def _song_vector(self, vector: tuple[float, ...]) -> SongVector:
        song = SongIdentity(
            library=LibraryIdentity(name="Music", root_path="/music"),
            normalized_path="songs/1.mp3",
        )
        return SongVector(
            song=song,
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

        response = client.get("/vector/track", params={"backbone_id": "effnet", "file_id": "1"})

        assert response.status_code == 200
        assert response.json() == {
            "file_id": 1,
            "backbone_id": "effnet",
            "vector": [0.9, 0.1, 0.5],
        }
        assert response.json().keys() == {"file_id", "backbone_id", "vector"}

    def test_missing_vector_maps_to_404(
        self,
        client: TestClient,
        mock_vector_search_service: MagicMock,
    ) -> None:
        """A None SongVector result maps to 404 with the file/backbone detail."""
        mock_vector_search_service.get_track_vector.return_value = None

        response = client.get("/vector/track", params={"backbone_id": "effnet", "file_id": "1"})

        assert response.status_code == 404
        assert "No vector found for file '1'" in response.json()["detail"]
