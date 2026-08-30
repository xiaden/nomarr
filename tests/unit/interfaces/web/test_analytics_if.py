"""Unit tests for the analytics web interface (mechanism-A library scoping).

Verifies that the optional ``library_id`` query parameter is treated as a
URL-encoded natural library name (decoded and resolved via
``get_library_by_name``), that the resolved domain ``Library`` is forwarded to
the analytics service, and that absent/unknown scopes fall back to global
(``library=None``) analytics.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.analytics_if import router as analytics_router
from nomarr.interfaces.api.web.dependencies import get_analytics_service, get_library_service

if TYPE_CHECKING:
    from collections.abc import Iterator


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


@pytest.fixture
def mock_library_service() -> MagicMock:
    """Provide a mocked library service dependency."""
    return MagicMock()


@pytest.fixture
def mock_analytics_service() -> MagicMock:
    """Provide a mocked analytics service dependency."""
    return MagicMock()


@pytest.fixture
def app(
    mock_library_service: MagicMock,
    mock_analytics_service: MagicMock,
) -> Iterator[FastAPI]:
    """Build a minimal FastAPI app for analytics endpoints."""
    test_app = FastAPI()
    test_app.include_router(analytics_router, prefix="/api/web")

    async def allow_session() -> None:
        return None

    test_app.dependency_overrides[verify_session] = allow_session
    test_app.dependency_overrides[get_library_service] = lambda: mock_library_service
    test_app.dependency_overrides[get_analytics_service] = lambda: mock_analytics_service

    yield test_app

    test_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Create a TestClient for the minimal app."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.unit
@pytest.mark.mocked
class TestAnalyticsLibraryScoping:
    """Tests for natural-name library scoping of analytics endpoints."""

    def test_mood_distribution_scopes_to_library_by_name(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_analytics_service: MagicMock,
    ) -> None:
        """A ``library_id`` query param should be decoded and forwarded as the domain Library."""
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library
        mock_analytics_service.get_mood_distribution_with_result.return_value = SimpleNamespace(
            mood_distribution=[SimpleNamespace(mood="happy", count=5, percentage=20.0)]
        )

        response = client.get("/api/web/analytics/mood-distribution", params={"library_id": "Test%20Library"})

        assert response.status_code == 200
        assert response.json() == {"mood_distribution": [{"mood": "happy", "count": 5, "percentage": 20.0}]}
        # Mechanism A: the wire identity is the decoded natural name, never an int PK.
        mock_library_service.get_library_by_name.assert_called_once_with("Test Library")
        assert isinstance(mock_library_service.get_library_by_name.call_args.args[0], str)
        mock_analytics_service.get_mood_distribution_with_result.assert_called_once_with(library=library)

    def test_mood_distribution_global_when_no_library_param(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_analytics_service: MagicMock,
    ) -> None:
        """Omitting ``library_id`` should run global analytics (library=None)."""
        mock_analytics_service.get_mood_distribution_with_result.return_value = SimpleNamespace(mood_distribution=[])

        response = client.get("/api/web/analytics/mood-distribution")

        assert response.status_code == 200
        mock_library_service.get_library_by_name.assert_not_called()
        mock_analytics_service.get_mood_distribution_with_result.assert_called_once_with(library=None)

    def test_mood_distribution_falls_back_to_global_when_library_missing(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_analytics_service: MagicMock,
    ) -> None:
        """An unknown library name should fall back to global analytics (not 404)."""
        mock_library_service.get_library_by_name.return_value = None
        mock_analytics_service.get_mood_distribution_with_result.return_value = SimpleNamespace(mood_distribution=[])

        response = client.get(
            "/api/web/analytics/mood-distribution",
            params={"library_id": "Missing%20Library"},
        )

        assert response.status_code == 200
        mock_library_service.get_library_by_name.assert_called_once_with("Missing Library")
        mock_analytics_service.get_mood_distribution_with_result.assert_called_once_with(library=None)

    def test_tag_frequencies_passes_limit(self, client: TestClient, mock_analytics_service: MagicMock) -> None:
        """GET tag-frequencies should forward the ``limit`` query parameter."""
        mock_analytics_service.get_tag_frequencies_with_result.return_value = SimpleNamespace(
            tag_frequencies=[SimpleNamespace(tag_key="nom:mood_happy", total_count=10, unique_values=2)]
        )

        response = client.get("/api/web/analytics/tag-frequencies", params={"limit": 100})

        assert response.status_code == 200
        assert response.json() == {
            "tag_frequencies": [{"tag_key": "nom:mood_happy", "total_count": 10, "unique_values": 2}]
        }
        mock_analytics_service.get_tag_frequencies_with_result.assert_called_once_with(limit=100)

    def test_tag_co_occurrences_scopes_to_library(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_analytics_service: MagicMock,
    ) -> None:
        """POST tag-co-occurrences should forward the resolved Library scope."""
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library
        mock_analytics_service.get_tag_co_occurrence.return_value = SimpleNamespace(
            x_tags=[SimpleNamespace(key="genre", value="rock")],
            y_tags=[SimpleNamespace(key="mood", value="happy")],
            matrix=[[1]],
        )

        response = client.post(
            "/api/web/analytics/tag-co-occurrences",
            params={"library_id": "Test%20Library"},
            json={"x": [{"key": "genre", "value": "rock"}], "y": [{"key": "mood", "value": "happy"}]},
        )

        assert response.status_code == 200
        mock_library_service.get_library_by_name.assert_called_once_with("Test Library")
        mock_analytics_service.get_tag_co_occurrence.assert_called_once_with(
            x_tags=[("genre", "rock")],
            y_tags=[("mood", "happy")],
            library=library,
        )

    def test_collection_overview_scopes_to_library(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_analytics_service: MagicMock,
    ) -> None:
        """GET collection-overview should forward the resolved Library scope."""
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library
        mock_analytics_service.get_collection_overview.return_value = {
            "stats": {
                "file_count": 10,
                "total_duration_ms": 1000,
                "total_file_size_bytes": 100000,
                "avg_track_length_ms": 100.0,
            },
            "year_distribution": [{"year": 2020, "count": 3}],
            "genre_distribution": [{"genre": "Rock", "count": 4}],
        }

        response = client.get(
            "/api/web/analytics/collection-overview",
            params={"library_id": "Test%20Library"},
        )

        assert response.status_code == 200
        mock_library_service.get_library_by_name.assert_called_once_with("Test Library")
        mock_analytics_service.get_collection_overview.assert_called_once_with(library=library)

    def test_analytics_error_maps_to_500(self, client: TestClient, mock_analytics_service: MagicMock) -> None:
        """Service errors should surface as HTTP 500 with a sanitized message."""
        mock_analytics_service.get_tag_frequencies_with_result.side_effect = RuntimeError("internal error")

        response = client.get("/api/web/analytics/tag-frequencies")

        assert response.status_code == 500
