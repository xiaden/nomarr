"""Integration tests for renamed library web endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.helpers.dto.library_dto import TagCleanupResult
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_library_service, get_tagging_service
from nomarr.interfaces.api.web.library_if import router as library_router


@pytest.fixture
def mock_tagging_service() -> MagicMock:
    """Create a mock TaggingService for endpoint tests."""
    return MagicMock()


@pytest.fixture
def mock_library_service() -> MagicMock:
    """Create a mock LibraryService for endpoint tests."""
    return MagicMock()


@pytest.fixture
def app(
    mock_tagging_service: MagicMock,
    mock_library_service: MagicMock,
) -> Iterator[FastAPI]:
    """Build a minimal FastAPI app with dependency overrides for library routes."""
    test_app = FastAPI()
    test_app.include_router(library_router, prefix="/api/web")

    async def allow_session() -> None:
        return None

    test_app.dependency_overrides[verify_session] = allow_session
    test_app.dependency_overrides[get_tagging_service] = lambda: mock_tagging_service
    test_app.dependency_overrides[get_library_service] = lambda: mock_library_service

    yield test_app

    test_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Create a TestClient for the minimal web app."""
    with TestClient(app) as test_client:
        yield test_client


class TestLibraryEndpoints:
    """Tests for renamed singular library endpoints."""

    @pytest.mark.integration
    @pytest.mark.mocked
    def test_post_cleanup_tag_returns_200(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """POST cleanup-tag should return the cleanup result."""
        mock_tagging_service.cleanup_orphaned_tags.return_value = TagCleanupResult(
            orphaned_count=0,
            deleted_count=0,
        )

        response = client.post("/api/web/library/cleanup-tag")

        assert response.status_code == 200
        assert response.json() == {"orphaned_count": 0, "deleted_count": 0}
        mock_tagging_service.cleanup_orphaned_tags.assert_called_once_with(dry_run=False)

    @pytest.mark.integration
    @pytest.mark.mocked
    def test_post_validate_tag_returns_200(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """POST validate-tag should return the validation summary."""
        mock_library_service.validate_library_tags.return_value = {
            "files_checked": 0,
            "complete_files": 0,
            "incomplete_files": 0,
            "files_repaired": 0,
            "expected_heads": 0,
            "missing_rels_summary": {},
        }

        response = client.post("/api/web/library/libraries:test_lib/validate-tag")

        assert response.status_code == 200
        assert response.json() == {
            "files_checked": 0,
            "complete_files": 0,
            "incomplete_files": 0,
            "files_repaired": 0,
            "expected_heads": 0,
            "missing_rels_summary": {},
        }
        mock_library_service.validate_library_tags.assert_called_once_with(
            library_id="libraries/test_lib",
            auto_repair=True,
        )

    @pytest.mark.integration
    @pytest.mark.mocked
    def test_get_errored_file_returns_200(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """GET errored-file should return the errored files payload."""
        mock_library_service.get_errored_files.return_value = {"files": [], "total": 0}

        response = client.get("/api/web/library/libraries:test_lib/errored-file")

        assert response.status_code == 200
        assert response.json() == {"files": [], "total": 0}
        mock_library_service.get_errored_files.assert_called_once_with(
            library_id="libraries/test_lib",
        )
