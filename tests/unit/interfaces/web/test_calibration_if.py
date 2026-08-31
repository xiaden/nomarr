"""Tests for the calibration web interface (``nomarr.interfaces.api.web.calibration_if``).

Focus: the flat histogram projection contract (P3-S4 / CONTRACTS L1410) —
``GET /calibration/histogram`` must expose a flat ``CalibrationHistogramItem``
per calibration state with the required fields
(``model_key``/``head_name``/``label``/``histogram_bins``/``p5``/``p95``/``n``/
``histogram_spec``) and must NOT leak the domain ``CalibrationState`` object, a
storage row id, or any storage envelope.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.helpers.dataclasses.calibration_state_dataclass import CalibrationState
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.calibration_if import router as calibration_router
from nomarr.interfaces.api.web.dependencies import get_calibration_service, get_tagging_service

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def mock_calibration_service() -> MagicMock:
    """Provide a mocked calibration service dependency."""
    return MagicMock()


@pytest.fixture
def mock_tagging_service() -> MagicMock:
    """Provide a mocked tagging service dependency."""
    return MagicMock()


@pytest.fixture
def app(
    mock_calibration_service: MagicMock,
    mock_tagging_service: MagicMock,
) -> Iterator[FastAPI]:
    """Build a minimal FastAPI app for calibration endpoints."""
    test_app = FastAPI()
    test_app.include_router(calibration_router, prefix="/api/web")

    async def allow_session() -> None:
        return None

    test_app.dependency_overrides[verify_session] = allow_session
    test_app.dependency_overrides[get_calibration_service] = lambda: mock_calibration_service
    test_app.dependency_overrides[get_tagging_service] = lambda: mock_tagging_service

    yield test_app

    test_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Create a TestClient for the minimal app."""
    with TestClient(app) as test_client:
        yield test_client


def _state(**overrides: object) -> CalibrationState:
    base: dict[str, object] = {
        "model_id": "model-1",
        "head_name": "mood_happy",
        "label": "happy",
        "histogram_bins": [{"val": 0.1, "count": 2}],
        "p5": 0.1,
        "p95": 0.9,
        "sample_count": 12,
        "histogram": {"lo": 0.0, "hi": 1.0, "bins": 10, "bin_width": 0.1},
        "calibration_def_hash": "hash-1",
        "underflow_count": 1,
        "overflow_count": 2,
    }
    base.update(overrides)
    return CalibrationState(**base)  # type: ignore[arg-type]


@pytest.mark.unit
class TestGetAllCalibrationHistograms:
    """``GET /calibration/histogram`` returns the flat histogram contract."""

    def test_projects_flat_histogram_items(self, client: TestClient, mock_calibration_service: MagicMock) -> None:
        state = _state()
        mock_calibration_service.get_all_calibration_states.return_value = [state]

        resp = client.get("/api/web/calibration/histogram")

        assert resp.status_code == 200
        payload = resp.json()["calibrations"]
        assert len(payload) == 1
        item = payload[0]
        # Required flat fields, all present at the top level.
        assert item["model_key"] == "model-1"
        assert item["head_name"] == "mood_happy"
        assert item["label"] == "happy"
        assert item["histogram_bins"] == [{"val": 0.1, "count": 2}]
        assert item["p5"] == 0.1
        assert item["p95"] == 0.9
        assert item["n"] == 12
        assert item["histogram_spec"] == {"lo": 0.0, "hi": 1.0, "bins": 10, "bin_width": 0.1}

    def test_no_nested_state_or_storage_envelope_leak(self, client, mock_calibration_service) -> None:
        mock_calibration_service.get_all_calibration_states.return_value = [_state()]

        resp = client.get("/api/web/calibration/histogram")

        item = resp.json()["calibrations"][0]
        assert "state" not in item
        assert "CalibrationState" not in json_dumps(item)
        assert "model_id" not in item  # projected under ``model_key``, never a nested object
        assert "sample_count" not in item  # exposed as ``n``
        assert "histogram" not in item  # exposed as ``histogram_spec``
        # No row/storage id is ever surfaced.
        assert "id" not in item
        assert "row" not in item

    def test_optional_fields_follow_state(self, client, mock_calibration_service) -> None:
        # ``calibration_def_hash`` is the only interface-level optional that can be
        # None; ``underflow_count``/``overflow_count`` are ints in CalibrationState.
        state = _state(calibration_def_hash=None)
        mock_calibration_service.get_all_calibration_states.return_value = [state]

        resp = client.get("/api/web/calibration/histogram")

        item = resp.json()["calibrations"][0]
        assert item["calibration_def_hash"] is None
        assert item["underflow_count"] == 1
        assert item["overflow_count"] == 2

    def test_histogram_bins_empty_when_none(self, client, mock_calibration_service) -> None:
        state = _state(histogram_bins=None)
        mock_calibration_service.get_all_calibration_states.return_value = [state]

        resp = client.get("/api/web/calibration/histogram")

        assert resp.json()["calibrations"][0]["histogram_bins"] == []


def json_dumps(obj: object) -> str:
    import json

    return json.dumps(obj)


@pytest.mark.unit
@pytest.mark.mocked
class TestApplyCalibrationStatus:
    """``GET /calibration/apply/status`` nullable apply lifecycle snapshot."""

    def test_returns_running_with_nullable_result_and_current_file(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """A running apply projects nullable ``result``/``error``/``current_file``."""
        mock_tagging_service.get_apply_combined_status.return_value = {
            "status": "running",
            "result": None,
            "error": None,
            "total_files": 10,
            "completed_files": 3,
            "current_file": None,
            "is_running": True,
        }

        resp = client.get("/api/web/calibration/apply/status")

        assert resp.status_code == 200
        assert resp.json() == {
            "status": "running",
            "result": None,
            "error": None,
            "total_files": 10,
            "completed_files": 3,
            "current_file": None,
            "is_running": True,
        }
        mock_tagging_service.get_apply_combined_status.assert_called_once_with()

    def test_completed_apply_projects_structured_result(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """A completed apply projects the typed result envelope, not a raw blob."""
        mock_tagging_service.get_apply_combined_status.return_value = {
            "status": "completed",
            "result": {"processed": 5, "failed": 1, "total": 6, "message": "done"},
            "error": None,
            "total_files": 6,
            "completed_files": 6,
            "current_file": None,
            "is_running": False,
        }

        resp = client.get("/api/web/calibration/apply/status")

        assert resp.status_code == 200
        assert resp.json()["result"] == {"processed": 5, "failed": 1, "total": 6, "message": "done"}

    def test_failed_apply_projects_error_without_result(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """A failed apply projects ``error`` while ``result`` stays null."""
        mock_tagging_service.get_apply_combined_status.return_value = {
            "status": "failed",
            "result": None,
            "error": "boom",
            "total_files": 0,
            "completed_files": 0,
            "current_file": None,
            "is_running": False,
        }

        resp = client.get("/api/web/calibration/apply/status")

        assert resp.json()["status"] == "failed"
        assert resp.json()["error"] == "boom"
        assert resp.json()["result"] is None


@pytest.mark.unit
@pytest.mark.mocked
class TestCalibrationStatus:
    """``GET /calibration/status`` nullable global version/last run."""

    def test_returns_nullable_global_fields_with_empty_libraries(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """A never-run calibration projects null ``global_version``/``last_run``."""
        mock_tagging_service.get_calibration_status.return_value = {
            "global_version": None,
            "last_run": None,
            "libraries": [],
        }

        resp = client.get("/api/web/calibration/status")

        assert resp.status_code == 200
        assert resp.json() == {"global_version": None, "last_run": None, "libraries": []}

    def test_returns_per_library_breakdown(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """The per-library breakdown projects the typed status envelope."""
        mock_tagging_service.get_calibration_status.return_value = {
            "global_version": "cal-v1",
            "last_run": 1_712_345_678,
            "libraries": [
                {
                    "library_id": "Test Library",
                    "library_name": "Test Library",
                    "total_files": 10,
                    "current_count": 6,
                    "outdated_count": 4,
                    "percentage": 60.0,
                }
            ],
        }

        resp = client.get("/api/web/calibration/status")

        assert resp.status_code == 200
        assert resp.json()["global_version"] == "cal-v1"
        assert resp.json()["last_run"] == 1_712_345_678
        assert resp.json()["libraries"] == [
            {
                "library_id": "Test Library",
                "library_name": "Test Library",
                "total_files": 10,
                "current_count": 6,
                "outdated_count": 4,
                "percentage": 60.0,
            }
        ]


@pytest.mark.unit
@pytest.mark.mocked
class TestHistogramGenerationStatus:
    """``GET /calibration/histogram/status`` nullable generation lifecycle."""

    def test_returns_running_with_nullable_fields(
        self,
        client: TestClient,
        mock_calibration_service: MagicMock,
    ) -> None:
        """A running generation projects nullable ``error``/``result``/head fields."""
        mock_calibration_service.get_generation_combined_status.return_value = {
            "running": True,
            "completed": False,
            "error": None,
            "result": None,
            "current_head": None,
            "current_head_index": None,
            "total_heads": 22,
            "completed_heads": 4,
            "remaining_heads": 18,
            "last_updated": None,
            "is_running": True,
        }

        resp = client.get("/api/web/calibration/histogram/status")

        assert resp.status_code == 200
        assert resp.json() == {
            "running": True,
            "completed": False,
            "error": None,
            "result": None,
            "current_head": None,
            "current_head_index": None,
            "total_heads": 22,
            "completed_heads": 4,
            "remaining_heads": 18,
            "last_updated": None,
            "is_running": True,
        }
        mock_calibration_service.get_generation_combined_status.assert_called_once_with()

    def test_completed_generation_projects_typed_fields(
        self,
        client: TestClient,
        mock_calibration_service: MagicMock,
    ) -> None:
        """A completed generation projects its result and head identity fields."""
        mock_calibration_service.get_generation_combined_status.return_value = {
            "running": False,
            "completed": True,
            "error": None,
            "result": {"heads": 22},
            "current_head": "mood_happy",
            "current_head_index": 21,
            "total_heads": 22,
            "completed_heads": 22,
            "remaining_heads": 0,
            "last_updated": 1_712_345_678,
            "is_running": False,
        }

        resp = client.get("/api/web/calibration/histogram/status")

        assert resp.json()["completed"] is True
        assert resp.json()["result"] == {"heads": 22}
        assert resp.json()["current_head"] == "mood_happy"
        assert resp.json()["current_head_index"] == 21
        assert resp.json()["last_updated"] == 1_712_345_678


@pytest.mark.unit
@pytest.mark.mocked
class TestCalibrationBackgroundStart:
    """``POST /calibration/apply/start`` and ``/histogram/start``."""

    def test_apply_start_returns_started(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """POST apply/start returns the background-start envelope."""
        mock_tagging_service.is_apply_running.return_value = False

        resp = client.post("/api/web/calibration/apply/start")

        assert resp.status_code == 200
        assert resp.json() == {"status": "started", "message": "Calibration apply started in background"}
        mock_tagging_service.start_apply_calibration_background.assert_called_once_with()

    def test_apply_start_returns_already_running(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """A running apply returns the already_running envelope without a second start."""
        mock_tagging_service.is_apply_running.return_value = True

        resp = client.post("/api/web/calibration/apply/start")

        assert resp.status_code == 200
        assert resp.json() == {"status": "already_running", "message": "Calibration apply already in progress"}
        mock_tagging_service.start_apply_calibration_background.assert_not_called()

    def test_histogram_start_returns_started(
        self,
        client: TestClient,
        mock_calibration_service: MagicMock,
    ) -> None:
        """POST histogram/start returns the background-start envelope."""
        mock_calibration_service.is_generation_running.return_value = False

        resp = client.post("/api/web/calibration/histogram/start")

        assert resp.status_code == 200
        assert resp.json() == {"status": "started", "message": "Calibration generation started in background"}
        mock_calibration_service.start_histogram_calibration_background.assert_called_once_with()
