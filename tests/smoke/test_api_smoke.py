"""
Smoke tests for API endpoints.

Tests all public and internal API endpoints with minimal setup.
Uses fake database and generated test audio files.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_application():
    """Create a mock Application instance."""
    with patch("nomarr.interfaces.api.app.Application") as MockApp:
        app_instance = MagicMock()
        MockApp.return_value = app_instance

        # Mock services
        app_instance.services.queue_service = MagicMock()
        app_instance.services.processing_service = MagicMock()
        app_instance.services.library_service = MagicMock()
        app_instance.services.worker_service = MagicMock()
        app_instance.services.health_monitor = MagicMock()

        yield app_instance


@pytest.fixture
def test_client(mock_application):
    """Create a TestClient for the API."""
    from nomarr.interfaces.api.app import app

    return TestClient(app)


@pytest.fixture
def api_key(test_client):
    """Get or generate API key for testing."""
    # Mock the API key check
    with patch("nomarr.interfaces.api.auth.verify_api_key", return_value=True):
        yield "test-api-key"


class TestPublicAPITag:
    """Smoke tests for public /api/v1/tag endpoint."""

    def test_tag_file(self, test_client, api_key, test_audio_fixtures):
        """Test tagging a file via API."""
        response = test_client.post(
            "/api/v1/tag",
            json={"path": test_audio_fixtures["basic"]},
            headers={"Authorization": f"Bearer {api_key}"},
        )

        # Should not crash (200, 400, 404 are all acceptable)
        assert response.status_code in [200, 400, 404, 503]

    def test_tag_file_with_force(self, test_client, api_key, test_audio_fixtures):
        """Test tagging with force flag."""
        response = test_client.post(
            "/api/v1/tag",
            json={"path": test_audio_fixtures["basic"], "force": True},
            headers={"Authorization": f"Bearer {api_key}"},
        )

        assert response.status_code in [200, 400, 404, 503]

    def test_tag_nonexistent_file(self, test_client, api_key):
        """Test tagging nonexistent file."""
        response = test_client.post(
            "/api/v1/tag",
            json={"path": "/nonexistent/file.wav"},
            headers={"Authorization": f"Bearer {api_key}"},
        )

        assert response.status_code in [400, 404]

    def test_tag_without_auth(self, test_client, test_audio_fixtures):
        """Test tagging without authentication."""
        response = test_client.post(
            "/api/v1/tag",
            json={"path": test_audio_fixtures["basic"]},
        )

        assert response.status_code == 403  # Forbidden


class TestPublicAPIQueue:
    """Smoke tests for public /api/v1/queue endpoints."""

    def test_list_queue(self, test_client, api_key):
        """Test listing queue."""
        with patch("nomarr.interfaces.api.auth.verify_api_key", return_value=True):
            response = test_client.get(
                "/api/v1/list",
                headers={"Authorization": f"Bearer {api_key}"},
            )

            assert response.status_code == 200

    def test_list_queue_with_pagination(self, test_client, api_key):
        """Test listing queue with pagination."""
        with patch("nomarr.interfaces.api.auth.verify_api_key", return_value=True):
            response = test_client.get(
                "/api/v1/list?limit=10&offset=0",
                headers={"Authorization": f"Bearer {api_key}"},
            )

            assert response.status_code == 200

    def test_list_queue_with_status_filter(self, test_client, api_key):
        """Test listing queue with status filter."""
        with patch("nomarr.interfaces.api.auth.verify_api_key", return_value=True):
            response = test_client.get(
                "/api/v1/list?status=pending",
                headers={"Authorization": f"Bearer {api_key}"},
            )

            assert response.status_code == 200

    def test_job_status(self, test_client, api_key):
        """Test checking job status."""
        with patch("nomarr.interfaces.api.auth.verify_api_key", return_value=True):
            response = test_client.get(
                "/api/v1/status/1",
                headers={"Authorization": f"Bearer {api_key}"},
            )

            # 200 (found) or 404 (not found) are both acceptable
            assert response.status_code in [200, 404]

    def test_legacy_queue_endpoint(self, test_client, api_key):
        """Test legacy /api/v1/queue endpoint."""
        with patch("nomarr.interfaces.api.auth.verify_api_key", return_value=True):
            response = test_client.get(
                "/api/v1/queue",
                headers={"Authorization": f"Bearer {api_key}"},
            )

            assert response.status_code == 200


class TestInternalAPIProcess:
    """Smoke tests for internal /internal/process_* endpoints."""

    def test_process_direct(self, test_client, test_audio_fixtures):
        """Test direct processing."""
        with patch("nomarr.interfaces.api.auth.verify_internal_key", return_value=True):
            response = test_client.post(
                "/internal/process_direct",
                json={"path": test_audio_fixtures["basic"]},
            )

            # Should not crash
            assert response.status_code in [200, 400, 404, 503]

    def test_process_stream(self, test_client, test_audio_fixtures):
        """Test streaming processing."""
        with patch("nomarr.interfaces.api.auth.verify_internal_key", return_value=True):
            response = test_client.post(
                "/internal/process_stream",
                json={"path": test_audio_fixtures["basic"]},
            )

            # SSE endpoints may return different status codes
            assert response.status_code in [200, 400, 404, 503]

    def test_batch_process(self, test_client, test_audio_fixtures):
        """Test batch processing."""
        with patch("nomarr.interfaces.api.auth.verify_internal_key", return_value=True):
            response = test_client.post(
                "/internal/batch_process",
                json={"paths": [test_audio_fixtures["basic"], test_audio_fixtures["long"]]},
            )

            assert response.status_code in [200, 400, 404, 503]


class TestAdminAPIWorker:
    """Smoke tests for /admin/worker endpoints."""

    def test_worker_pause(self, test_client, api_key):
        """Test pausing worker."""
        with patch("nomarr.interfaces.api.auth.verify_api_key", return_value=True):
            response = test_client.post(
                "/admin/worker/pause",
                headers={"Authorization": f"Bearer {api_key}"},
            )

            assert response.status_code in [200, 400]

    def test_worker_resume(self, test_client, api_key):
        """Test resuming worker."""
        with patch("nomarr.interfaces.api.auth.verify_api_key", return_value=True):
            response = test_client.post(
                "/admin/worker/resume",
                headers={"Authorization": f"Bearer {api_key}"},
            )

            assert response.status_code in [200, 400]

    def test_worker_status(self, test_client, api_key):
        """Test checking worker status."""
        with patch("nomarr.interfaces.api.auth.verify_api_key", return_value=True):
            response = test_client.get(
                "/admin/worker/status",
                headers={"Authorization": f"Bearer {api_key}"},
            )

            assert response.status_code == 200


class TestAdminAPIQueue:
    """Smoke tests for /admin/queue endpoints."""

    def test_queue_clear(self, test_client, api_key):
        """Test clearing queue."""
        with patch("nomarr.interfaces.api.auth.verify_api_key", return_value=True):
            response = test_client.post(
                "/admin/queue/clear",
                headers={"Authorization": f"Bearer {api_key}"},
            )

            assert response.status_code in [200, 400]

    def test_queue_remove_job(self, test_client, api_key):
        """Test removing specific job."""
        with patch("nomarr.interfaces.api.auth.verify_api_key", return_value=True):
            response = test_client.post(
                "/admin/queue/remove",
                json={"job_id": 1},
                headers={"Authorization": f"Bearer {api_key}"},
            )

            assert response.status_code in [200, 404]


class TestAdminAPICache:
    """Smoke tests for /admin/cache endpoints."""

    def test_cache_refresh(self, test_client, api_key):
        """Test refreshing model cache."""
        with patch("nomarr.interfaces.api.auth.verify_api_key", return_value=True):
            response = test_client.post(
                "/admin/cache/refresh",
                headers={"Authorization": f"Bearer {api_key}"},
            )

            assert response.status_code in [200, 500]

    def test_cache_list(self, test_client, api_key):
        """Test listing cached models."""
        with patch("nomarr.interfaces.api.auth.verify_api_key", return_value=True):
            response = test_client.get(
                "/admin/cache/list",
                headers={"Authorization": f"Bearer {api_key}"},
            )

            assert response.status_code == 200


class TestWebAuthEndpoints:
    """Smoke tests for /web/auth endpoints."""

    def test_login(self, test_client):
        """Test login endpoint."""
        with patch("nomarr.interfaces.api.auth.verify_admin_password", return_value=True):
            response = test_client.post(
                "/web/auth/login",
                json={"password": "test-password"},
            )

            # Should return session token or error
            assert response.status_code in [200, 401]

    def test_logout(self, test_client):
        """Test logout endpoint."""
        with patch("nomarr.interfaces.api.auth.verify_session_token", return_value=True):
            response = test_client.post(
                "/web/auth/logout",
                headers={"Authorization": "Bearer test-session-token"},
            )

            assert response.status_code in [200, 401]

    def test_verify_session(self, test_client):
        """Test session verification."""
        with patch("nomarr.interfaces.api.auth.verify_session_token", return_value=True):
            response = test_client.get(
                "/web/auth/verify",
                headers={"Authorization": "Bearer test-session-token"},
            )

            assert response.status_code in [200, 401]


class TestWebAPIProxyEndpoints:
    """Smoke tests for /web/api proxy endpoints."""

    def test_web_api_list(self, test_client):
        """Test listing jobs via web API."""
        with patch("nomarr.interfaces.api.auth.verify_session_token", return_value=True):
            response = test_client.get(
                "/web/api/list",
                headers={"Authorization": "Bearer test-session-token"},
            )

            assert response.status_code == 200

    def test_web_api_process(self, test_client, test_audio_fixtures):
        """Test processing via web API."""
        with patch("nomarr.interfaces.api.auth.verify_session_token", return_value=True):
            response = test_client.post(
                "/web/api/process",
                json={"path": test_audio_fixtures["basic"]},
                headers={"Authorization": "Bearer test-session-token"},
            )

            assert response.status_code in [200, 400, 404, 503]

    def test_web_api_batch_process(self, test_client, test_audio_fixtures):
        """Test batch processing via web API."""
        with patch("nomarr.interfaces.api.auth.verify_session_token", return_value=True):
            response = test_client.post(
                "/web/api/batch-process",
                json={"paths": [test_audio_fixtures["basic"]]},
                headers={"Authorization": "Bearer test-session-token"},
            )

            assert response.status_code in [200, 400, 404, 503]


class TestHealthEndpoints:
    """Smoke tests for health check endpoints."""

    def test_health_check(self, test_client):
        """Test health check endpoint."""
        response = test_client.get("/health")

        assert response.status_code == 200

    def test_readiness_check(self, test_client):
        """Test readiness check endpoint."""
        response = test_client.get("/ready")

        # May be ready or not ready depending on state
        assert response.status_code in [200, 503]
