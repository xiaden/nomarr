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
from nomarr.interfaces.api.web.dependencies import get_calibration_service

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def mock_calibration_service() -> MagicMock:
    """Provide a mocked calibration service dependency."""
    return MagicMock()


@pytest.fixture
def app(mock_calibration_service: MagicMock) -> Iterator[FastAPI]:
    """Build a minimal FastAPI app for calibration endpoints."""
    test_app = FastAPI()
    test_app.include_router(calibration_router, prefix="/api/web")

    async def allow_session() -> None:
        return None

    test_app.dependency_overrides[verify_session] = allow_session
    test_app.dependency_overrides[get_calibration_service] = lambda: mock_calibration_service

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
