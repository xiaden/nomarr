"""Tests for the library scan/pipeline web interface (``library_scan_if``).

Covers the clean-break wire contract for the scan, repair, reconcile, write-tag,
write-mode, and validate-tag endpoints. The ``GET /{library_name}/pipeline``
endpoint is intentionally NOT duplicated here — it is covered by
``test_pipeline_endpoint.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dto.library_dto import StartScanResult
from nomarr.helpers.exceptions import LibraryAlreadyScanningError
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import (
    get_library_service,
    get_navidrome_service,
    get_pipeline_service,
    get_tagging_service,
)
from nomarr.interfaces.api.web.library_scan_if import router as library_scan_router

if TYPE_CHECKING:
    from collections.abc import Iterator


def make_library(name: str = "Test Library") -> Library:
    """Build a domain ``Library`` fixture (natural identity)."""
    return Library(
        name=name,
        root_path="D:/Music/Test",
        is_enabled=True,
        watch_mode="off",
        file_write_mode="full",
        library_auto_write=False,
    )


def _scan_result(*, files_queued: int = 8) -> StartScanResult:
    return StartScanResult(
        files_discovered=10,
        files_queued=files_queued,
        files_skipped=2,
        files_removed=0,
        job_ids=["job-1"],
    )


@pytest.fixture
def mock_library_service() -> MagicMock:
    """Provide a mocked library service dependency."""
    return MagicMock()


@pytest.fixture
def mock_tagging_service() -> MagicMock:
    """Provide a mocked tagging service dependency."""
    return MagicMock()


@pytest.fixture
def mock_pipeline_service() -> MagicMock:
    """Provide a mocked pipeline service dependency."""
    return MagicMock()


@pytest.fixture
def mock_navidrome_service() -> MagicMock:
    """Provide a mocked navidrome service dependency."""
    return MagicMock()


@pytest.fixture
def app(
    mock_library_service: MagicMock,
    mock_tagging_service: MagicMock,
    mock_pipeline_service: MagicMock,
    mock_navidrome_service: MagicMock,
) -> Iterator[FastAPI]:
    """Build a minimal FastAPI app for library scan endpoints."""
    test_app = FastAPI()
    test_app.include_router(library_scan_router, prefix="/api/web")

    async def allow_session() -> None:
        return None

    test_app.dependency_overrides[verify_session] = allow_session
    test_app.dependency_overrides[get_library_service] = lambda: mock_library_service
    test_app.dependency_overrides[get_tagging_service] = lambda: mock_tagging_service
    test_app.dependency_overrides[get_pipeline_service] = lambda: mock_pipeline_service
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
class TestLibraryScanRoutes:
    """Tests for scan start/cancel and repair endpoints."""

    def test_scan_quick_returns_started_response(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """POST scan/quick should serialize the scan stats under the status wrapper."""
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library
        mock_library_service.start_quick_scan.return_value = _scan_result()

        response = client.post("/api/web/library/Test%20Library/scan/quick")

        assert response.status_code == 200
        assert response.json() == {
            "status": "started",
            "message": "Scan started for library Test Library: 8 files discovered",
            "stats": {
                "files_discovered": 10,
                "files_queued": 8,
                "files_skipped": 2,
                "files_removed": 0,
                "job_ids": ["job-1"],
            },
        }
        mock_library_service.get_library_by_name.assert_called_once_with("Test Library")
        mock_library_service.start_quick_scan.assert_called_once_with(library)

    def test_scan_quick_returns_404_when_library_missing(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """A missing library should surface as HTTP 404."""
        mock_library_service.get_library_by_name.return_value = None

        response = client.post("/api/web/library/Test%20Library/scan/quick")

        assert response.status_code == 404
        assert response.json() == {"detail": "Library not found"}
        mock_library_service.start_quick_scan.assert_not_called()

    def test_scan_quick_returns_409_when_already_scanning(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """A concurrent scan should surface as HTTP 409."""
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library
        mock_library_service.start_quick_scan.side_effect = LibraryAlreadyScanningError()

        response = client.post("/api/web/library/Test%20Library/scan/quick")

        assert response.status_code == 409
        assert response.json() == {"detail": "Library is already being scanned"}

    def test_scan_full_returns_started_response(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """POST scan/full should share the StartScanWithStatusResponse shape."""
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library
        mock_library_service.start_full_scan.return_value = _scan_result(files_queued=12)

        response = client.post("/api/web/library/Test%20Library/scan/full")

        assert response.status_code == 200
        assert response.json()["stats"]["files_queued"] == 12
        mock_library_service.start_full_scan.assert_called_once_with(library)

    def test_scan_cancel_returns_cancelled_flag(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """POST scan/cancel should return the boolean cancellation flag."""
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library
        mock_library_service.cancel_scan.return_value = True

        response = client.post("/api/web/library/Test%20Library/scan/cancel")

        assert response.status_code == 200
        assert response.json() == {"cancelled": True}
        mock_library_service.cancel_scan.assert_called_once_with(library)

    def test_repair_tags_returns_started_response(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """POST repair-tags should serialize the scan stats wrapper."""
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library
        mock_library_service.repair_library_tags.return_value = _scan_result(files_queued=3)

        response = client.post("/api/web/library/Test%20Library/repair-tags")

        assert response.status_code == 200
        assert response.json()["stats"]["files_queued"] == 3
        mock_library_service.repair_library_tags.assert_called_once_with(library)


@pytest.mark.unit
@pytest.mark.mocked
class TestLibraryReconcile:
    """Tests for the reconcile endpoint."""

    def test_reconcile_returns_counts_with_defaults(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """POST reconcile should project the full counts envelope with default policy."""
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library
        mock_library_service.reconcile_library_paths.return_value = {
            "total_files": 10,
            "valid_files": 7,
            "invalid_config": 1,
            "not_found": 2,
            "unknown_status": 0,
            "deleted_files": 0,
            "errors": 0,
        }

        response = client.post("/api/web/library/Test%20Library/reconcile")

        assert response.status_code == 200
        assert response.json() == {
            "total_files": 10,
            "valid_files": 7,
            "invalid_config": 1,
            "not_found": 2,
            "unknown_status": 0,
            "deleted_files": 0,
            "errors": 0,
        }
        mock_library_service.reconcile_library_paths.assert_called_once_with(
            library,
            policy="mark_invalid",
            batch_size=1000,
        )

    def test_reconcile_returns_400_for_invalid_policy(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """A policy rejection should surface as HTTP 400."""
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library
        mock_library_service.reconcile_library_paths.side_effect = ValueError("bad policy value")

        response = client.post("/api/web/library/Test%20Library/reconcile")

        assert response.status_code == 400
        assert response.json() == {"detail": "Invalid reconciliation policy"}


@pytest.mark.unit
@pytest.mark.mocked
class TestLibraryWriteTag:
    """Tests for the write-tag endpoint."""

    def test_write_tag_returns_task_id(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_tagging_service: MagicMock,
    ) -> None:
        """POST write-tag should return the started status and task id (202)."""
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library
        mock_tagging_service.start_write_tags_background.return_value = "task-42"

        response = client.post("/api/web/library/Test%20Library/write-tag")

        assert response.status_code == 202
        assert response.json() == {"status": "started", "task_id": "task-42"}
        assert mock_tagging_service.start_write_tags_background.call_args.args[0] is library

    def test_write_tag_returns_404_when_library_missing(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_tagging_service: MagicMock,
    ) -> None:
        """A ValueError from the tagging service should surface as HTTP 404."""
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library
        mock_tagging_service.start_write_tags_background.side_effect = ValueError("no such library")

        response = client.post("/api/web/library/Test%20Library/write-tag")

        assert response.status_code == 404
        assert response.json() == {"detail": "Library not found"}


@pytest.mark.unit
@pytest.mark.mocked
class TestLibraryWriteMode:
    """Tests for the write-mode endpoint."""

    def test_update_write_mode_returns_reconciliation_status(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_tagging_service: MagicMock,
    ) -> None:
        """PATCH write-mode should project the pending-count reconciliation state."""
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library
        mock_tagging_service.get_reconcile_status.return_value = {"pending_count": 5}

        response = client.patch("/api/web/library/Test%20Library/write-mode", params={"file_write_mode": "minimal"})

        assert response.status_code == 200
        assert response.json() == {
            "file_write_mode": "minimal",
            "requires_reconciliation": True,
            "affected_file_count": 5,
        }
        mock_library_service.update_library.assert_called_once_with(library, file_write_mode="minimal")
        mock_tagging_service.mark_tags_not_fresh.assert_called_once_with(library)
        mock_tagging_service.get_reconcile_status.assert_called_once_with(library)

    def test_update_write_mode_returns_400_for_invalid_mode(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """An unsupported write mode should surface as HTTP 400."""
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library

        response = client.patch("/api/web/library/Test%20Library/write-mode", params={"file_write_mode": "ultra"})

        assert response.status_code == 400
        assert response.json()["detail"] == "file_write_mode must be 'none', 'minimal', or 'full'"
        mock_library_service.update_library.assert_not_called()


@pytest.mark.unit
@pytest.mark.mocked
class TestLibraryValidateTag:
    """Tests for the validate-tag endpoint."""

    def test_validate_tag_returns_counts(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """POST validate-tag should project the validation counts envelope."""
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library
        mock_library_service.validate_library_tags.return_value = {
            "files_checked": 10,
            "complete_files": 6,
            "incomplete_files": 4,
            "files_repaired": 2,
            "expected_heads": 3,
            "missing_names_summary": {"artist": 1, "title": 3},
        }

        response = client.post("/api/web/library/Test%20Library/validate-tag")

        assert response.status_code == 200
        assert response.json() == {
            "files_checked": 10,
            "complete_files": 6,
            "incomplete_files": 4,
            "files_repaired": 2,
            "expected_heads": 3,
            "missing_names_summary": {"artist": 1, "title": 3},
        }
        mock_library_service.validate_library_tags.assert_called_once_with(library, auto_repair=True)


@pytest.mark.unit
@pytest.mark.mocked
class TestLibraryScanAuth:
    """Tests for session-auth enforcement on the scan router."""

    def test_requires_session_auth_without_override(self) -> None:
        """The scan endpoints must reject an unauthenticated request with 401."""
        test_app = FastAPI()
        test_app.include_router(library_scan_router, prefix="/api/web")

        with TestClient(test_app) as test_client:
            response = test_client.post("/api/web/library/Test%20Library/scan/quick")

        assert response.status_code == 401
        assert response.json() == {"detail": "Missing Authorization header"}
