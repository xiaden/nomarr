"""Integration tests for the write-tag web endpoint."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import (
    get_navidrome_service,
    get_tagging_service,
)
from nomarr.interfaces.api.web.library_scan_if import router as library_router


@pytest.fixture
def mock_tagging_service() -> MagicMock:
    """Create a mock TaggingService for endpoint tests."""
    return MagicMock()


@pytest.fixture
def mock_navidrome_service() -> MagicMock:
    """Create a mock NavidromeService for endpoint tests."""
    return MagicMock()


@pytest.fixture
def app(
    mock_tagging_service: MagicMock,
    mock_navidrome_service: MagicMock,
) -> Iterator[FastAPI]:
    """Build a minimal FastAPI app with dependency overrides for library routes."""
    test_app = FastAPI()
    test_app.include_router(library_router, prefix="/api/web")

    async def allow_session() -> None:
        return None

    test_app.dependency_overrides[verify_session] = allow_session
    test_app.dependency_overrides[get_tagging_service] = lambda: mock_tagging_service
    test_app.dependency_overrides[get_navidrome_service] = lambda: mock_navidrome_service

    yield test_app

    test_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Create a TestClient for the minimal web app."""
    with TestClient(app) as test_client:
        yield test_client


class TestReconcileEndpoints:
    """Tests for write-tag dispatch endpoint behavior."""

    @pytest.mark.integration
    @pytest.mark.mocked
    def test_post_reconcile_tags_returns_202(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """POST should start the background task and return task metadata."""
        mock_tagging_service.start_write_tags_background.return_value = "write_tags:test_lib"

        response = client.post("/api/web/library/libraries:test_lib/write-tag")

        assert response.status_code == 202
        assert response.json() == {
            "status": "started",
            "task_id": "write_tags:test_lib",
        }
        mock_tagging_service.start_write_tags_background.assert_called_once()

    @pytest.mark.integration
    @pytest.mark.mocked
    def test_post_reconcile_tags_returns_404_for_unknown_library(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """POST should translate missing-library service errors into HTTP 404."""
        mock_tagging_service.start_write_tags_background.side_effect = ValueError(
            "Library not found",
        )

        response = client.post("/api/web/library/libraries:test_lib/write-tag")

        assert response.status_code == 404
        assert response.json() == {"detail": "Library not found"}
