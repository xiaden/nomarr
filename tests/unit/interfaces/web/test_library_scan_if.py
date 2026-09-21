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
from nomarr.helpers.exceptions import LibraryAlreadyScanningError, LibraryOperationConflict
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
        mock_library_service.start_quick_scan.side_effect = LibraryAlreadyScanningError(
            "Library is already being scanned"
        )

        response = client.post("/api/web/library/Test%20Library/scan/quick")

        assert response.status_code == 409
        assert response.json() == {"detail": "Library is already being scanned"}

    def test_scan_quick_maps_operation_conflict_to_409_with_detail(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        library = make_library()
        conflict = LibraryOperationConflict("scan", scan_state="scanning", tag_write_state="not_written")
        mock_library_service.get_library_by_name.return_value = library
        mock_library_service.start_quick_scan.side_effect = conflict

        response = client.post("/api/web/library/Test%20Library/scan/quick")

        assert response.status_code == 409
        assert response.json() == {"detail": str(conflict)}

    def test_scan_full_maps_operation_conflict_to_409_with_detail(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        library = make_library()
        conflict = LibraryOperationConflict("scan", scan_state="scanning", tag_write_state="not_written")
        mock_library_service.get_library_by_name.return_value = library
        mock_library_service.start_full_scan.side_effect = conflict

        response = client.post("/api/web/library/Test%20Library/scan/full")

        assert response.status_code == 409
        assert response.json() == {"detail": str(conflict)}

    def test_repair_tags_maps_operation_conflict_to_409_with_detail(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        library = make_library()
        conflict = LibraryOperationConflict("scan", scan_state="scanning", tag_write_state="not_written")
        mock_library_service.get_library_by_name.return_value = library
        mock_library_service.repair_library_tags.side_effect = conflict

        response = client.post("/api/web/library/Test%20Library/repair-tags")

        assert response.status_code == 409
        assert response.json() == {"detail": str(conflict)}

    def test_write_tag_maps_operation_conflict_to_409_with_detail(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_tagging_service: MagicMock,
    ) -> None:
        library = make_library()
        conflict = LibraryOperationConflict("tag_write", scan_state="scanning", tag_write_state="not_written")
        mock_library_service.get_library_by_name.return_value = library
        mock_tagging_service.start_write_tags_background.side_effect = conflict

        response = client.post(
            "/api/web/library/Test%20Library/write-tag",
            json={"overwrite": "files"},
        )

        assert response.status_code == 409
        assert response.json() == {
            "detail": {
                "code": "LIBRARY_OPERATION_CONFLICT",
                "operation": "tag_write",
                "scan_state": "scanning",
                "tag_write_state": "not_written",
                "not_hydrated_count": 0,
            }
        }

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

    @pytest.mark.parametrize(
        "payload",
        [
            None,
            {},
            {"overwrite": "none"},
            {"overwrite": "files"},
            {"overwrite": "database"},
        ],
    )
    def test_write_tag_accepts_strict_valid_payloads(
        self,
        payload: dict[str, str] | None,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_tagging_service: MagicMock,
    ) -> None:
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library
        mock_tagging_service.start_write_tags_background.return_value = "task-42"

        response = client.post(
            "/api/web/library/Test%20Library/write-tag",
            **({"json": payload} if payload is not None else {}),
        )

        assert response.status_code == 202
        expected = "none" if not payload else payload["overwrite"]
        assert response.json()["requested_mode"] == expected
        assert mock_tagging_service.start_write_tags_background.call_args.kwargs["requested_mode"] == expected

    @pytest.mark.parametrize(
        "payload",
        [
            [],
            "files",
            1,
            {"overwrite": None},
            {"overwrite": ""},
            {"overwrite": "bogus"},
            {"overwrite": 1},
            {"extra": "x"},
            {"overwrite": "files", "extra": 1},
        ],
    )
    def test_write_tag_rejects_invalid_json_before_library_resolution(
        self,
        payload: object,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_tagging_service: MagicMock,
    ) -> None:
        mock_library_service.get_library_by_name.return_value = make_library()
        response = client.post("/api/web/library/Test%20Library/write-tag", json=payload)
        assert response.status_code == 422
        mock_library_service.get_library_by_name.assert_not_called()
        mock_tagging_service.start_write_tags_background.assert_not_called()

    def test_write_tag_rejects_null_body_before_library_resolution(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_tagging_service: MagicMock,
    ) -> None:
        response = client.post(
            "/api/web/library/Test%20Library/write-tag",
            content=b"null",
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 422
        mock_library_service.get_library_by_name.assert_not_called()
        mock_tagging_service.start_write_tags_background.assert_not_called()

    def test_write_tag_rejects_malformed_json_before_library_resolution(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_tagging_service: MagicMock,
    ) -> None:
        response = client.post(
            "/api/web/library/Test%20Library/write-tag",
            content=b'{"overwrite":',
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 422
        mock_library_service.get_library_by_name.assert_not_called()
        mock_tagging_service.start_write_tags_background.assert_not_called()

    def test_write_tag_rejects_query_only_overwrite_before_library_resolution(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_tagging_service: MagicMock,
    ) -> None:
        response = client.post("/api/web/library/Test%20Library/write-tag?overwrite=files")
        assert response.status_code == 422
        mock_library_service.get_library_by_name.assert_not_called()
        mock_tagging_service.start_write_tags_background.assert_not_called()

    def test_write_tag_rejects_body_query_conflict_before_library_resolution(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_tagging_service: MagicMock,
    ) -> None:
        response = client.post(
            "/api/web/library/Test%20Library/write-tag?overwrite=database",
            json={"overwrite": "files"},
        )
        assert response.status_code == 422
        mock_library_service.get_library_by_name.assert_not_called()
        mock_tagging_service.start_write_tags_background.assert_not_called()

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
        assert response.json() == {
            "status": "started",
            "task_id": "task-42",
            "requested_mode": "none",
            "outcome": "active",
        }
        assert mock_tagging_service.start_write_tags_background.call_args.args[0] is library
        assert mock_tagging_service.start_write_tags_background.call_args.kwargs["requested_mode"] == "none"

    def test_write_tag_rescan_skipped_when_pending_work_remains(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_tagging_service: MagicMock,
        mock_navidrome_service: MagicMock,
    ) -> None:
        """A partial reconcile state must not trigger the Navidrome rescan."""
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library
        mock_tagging_service.start_write_tags_background.return_value = "task-42"
        mock_tagging_service.get_reconcile_status.return_value = {
            "pending_count": 4,
            "failed_count": 4,
            "in_progress": False,
            "outcome": "partial",
        }

        response = client.post("/api/web/library/Test%20Library/write-tag")

        assert response.status_code == 202
        on_complete = mock_tagging_service.start_write_tags_background.call_args.kwargs["on_complete"]
        on_complete()

        mock_tagging_service.get_reconcile_status.assert_called_once_with(library)
        mock_navidrome_service.trigger_rescan.assert_not_called()

    def test_write_tag_rescan_fires_when_drained(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_tagging_service: MagicMock,
        mock_navidrome_service: MagicMock,
    ) -> None:
        """A fully drained reconcile state triggers exactly one Navidrome rescan."""
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library
        mock_tagging_service.start_write_tags_background.return_value = "task-42"
        mock_tagging_service.get_reconcile_status.return_value = {
            "pending_count": 0,
            "failed_count": 0,
            "in_progress": False,
            "outcome": "complete",
        }

        response = client.post("/api/web/library/Test%20Library/write-tag")

        assert response.status_code == 202
        on_complete = mock_tagging_service.start_write_tags_background.call_args.kwargs["on_complete"]
        on_complete()

        mock_navidrome_service.trigger_rescan.assert_called_once()

    def test_write_tag_conflict_returns_structured_409_without_dispatch(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_tagging_service: MagicMock,
        mock_navidrome_service: MagicMock,
    ) -> None:
        library = make_library()
        conflict = LibraryOperationConflict(
            "tag_write", scan_state="scanning", tag_write_state="not_written", not_hydrated_count=3
        )
        mock_library_service.get_library_by_name.return_value = library
        mock_tagging_service.start_write_tags_background.side_effect = conflict

        response = client.post(
            "/api/web/library/Test%20Library/write-tag",
            json={"overwrite": "database"},
        )

        assert response.status_code == 409
        assert response.json()["detail"] == {
            "code": "LIBRARY_OPERATION_CONFLICT",
            "operation": "tag_write",
            "scan_state": "scanning",
            "tag_write_state": "not_written",
            "not_hydrated_count": 3,
        }
        mock_tagging_service.start_write_tags_background.assert_called_once()
        mock_navidrome_service.trigger_rescan.assert_not_called()

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

    def test_write_tag_rescan_skipped_when_reconcile_state_unknown(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_tagging_service: MagicMock,
        mock_navidrome_service: MagicMock,
    ) -> None:
        """An unknown reconcile state (missing pending_count) must not trigger a rescan."""
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library
        mock_tagging_service.start_write_tags_background.return_value = "task-42"
        mock_tagging_service.get_reconcile_status.return_value = {}

        response = client.post("/api/web/library/Test%20Library/write-tag")

        assert response.status_code == 202
        on_complete = mock_tagging_service.start_write_tags_background.call_args.kwargs["on_complete"]
        on_complete()  # unknown state must be handled without raising

        mock_navidrome_service.trigger_rescan.assert_not_called()


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
