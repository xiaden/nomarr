"""Tests for the info/health web interface (``nomarr.interfaces.api.web.info_if``).

Focus: the clean-break wire contract for ``/api/web/info``, ``/health``, and
``/health/gpu`` — the exact response field sets, the GPU degraded/available
fallback, and session-auth enforcement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.helpers.dto.info_dto import GPUHealthResult, HealthStatusResult, SystemInfoResult
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_info_service
from nomarr.interfaces.api.web.info_if import router as info_router

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def mock_info_service() -> MagicMock:
    """Provide a mocked info service dependency."""
    return MagicMock()


@pytest.fixture
def app(mock_info_service: MagicMock) -> Iterator[FastAPI]:
    """Build a minimal FastAPI app for info/health endpoints."""
    test_app = FastAPI()
    test_app.include_router(info_router, prefix="/api/web")

    async def allow_session() -> None:
        return None

    test_app.dependency_overrides[verify_session] = allow_session
    test_app.dependency_overrides[get_info_service] = lambda: mock_info_service

    yield test_app

    test_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Create a TestClient for the minimal app."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.unit
@pytest.mark.mocked
class TestInfoRoutes:
    """Tests for the system-info routes."""

    def test_get_info_returns_system_info(
        self,
        client: TestClient,
        mock_info_service: MagicMock,
    ) -> None:
        """GET /info should serialize the system-info DTO."""
        mock_info_service.get_system_info.return_value = SystemInfoResult(
            version="1.2.3",
            namespace="nom",
            models_dir="/models",
            worker_enabled=True,
            worker_count=3,
        )

        response = client.get("/api/web/info")

        assert response.status_code == 200
        assert response.json() == {
            "version": "1.2.3",
            "namespace": "nom",
            "models_dir": "/models",
            "worker_enabled": True,
            "worker_count": 3,
        }
        mock_info_service.get_system_info.assert_called_once_with()

    def test_get_health_returns_health_status(
        self,
        client: TestClient,
        mock_info_service: MagicMock,
    ) -> None:
        """GET /health should serialize the health-status DTO."""
        mock_info_service.get_health_status.return_value = HealthStatusResult(
            status="healthy",
            processor_initialized=True,
            worker_count=2,
            queue={"depth": 0},
            warnings=["warn-1"],
        )

        response = client.get("/api/web/health")

        assert response.status_code == 200
        assert response.json() == {
            "status": "healthy",
            "processor_initialized": True,
            "worker_count": 2,
            "queue": {"depth": 0},
            "warnings": ["warn-1"],
        }
        mock_info_service.get_health_status.assert_called_once_with()

    def test_get_gpu_health_returns_gpu_status(
        self,
        client: TestClient,
        mock_info_service: MagicMock,
    ) -> None:
        """GET /health/gpu should serialize the GPU-health DTO."""
        mock_info_service.get_gpu_health.return_value = GPUHealthResult(
            available=True,
            error_summary=None,
            monitor_healthy=True,
        )

        response = client.get("/api/web/health/gpu")

        assert response.status_code == 200
        assert response.json() == {
            "available": True,
            "error_summary": None,
            "monitor_healthy": True,
        }
        mock_info_service.get_gpu_health.assert_called_once_with()

    def test_get_gpu_health_returns_degraded_when_monitor_unavailable(
        self,
        client: TestClient,
        mock_info_service: MagicMock,
    ) -> None:
        """A RuntimeError from the GPU monitor should project a degraded-but-200 response."""
        mock_info_service.get_gpu_health.side_effect = RuntimeError("monitor down")

        response = client.get("/api/web/health/gpu")

        assert response.status_code == 200
        assert response.json() == {
            "available": False,
            "error_summary": "GPU monitoring not available",
            "monitor_healthy": False,
        }

    def test_requires_session_auth_without_override(self) -> None:
        """The info routes must reject an unauthenticated request with 401."""
        test_app = FastAPI()
        test_app.include_router(info_router, prefix="/api/web")

        with TestClient(test_app) as test_client:
            response = test_client.get("/api/web/info")

        assert response.status_code == 401
        assert response.json() == {"detail": "Missing Authorization header"}
