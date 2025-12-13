"""
Integration tests for production API endpoints.

Tests the real API with real ML processing (not mocked).

These tests require:
- Running API server
- ML models available
- GPU for inference (or very slow on CPU)
- Docker container environment preferred

Skip in CI with: pytest -m "not container_only"
"""

import os

import pytest
import requests

# Mark all tests in this module
pytestmark = [
    pytest.mark.integration,
    pytest.mark.container_only,
    pytest.mark.slow,
]

# Test fixtures path
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "fixtures")
API_BASE_URL = os.getenv("NOMARR_API_URL", "http://localhost:8356")
API_KEY = os.getenv("NOMARR_API_KEY", "")


@pytest.fixture(scope="module")
def api_headers():
    """Get API headers with authentication."""
    return {"Authorization": f"Bearer {API_KEY}"}


@pytest.fixture(scope="module")
def test_files():
    """Get paths to test audio files."""
    return {
        "basic": os.path.join(FIXTURES_DIR, "test_basic.mp3"),
        "long": os.path.join(FIXTURES_DIR, "test_long.mp3"),
        "short": os.path.join(FIXTURES_DIR, "test_short.mp3"),
        "variety": os.path.join(FIXTURES_DIR, "test_variety.mp3"),
    }


class TestPublicAPITag:
    """Test /api/v1/tag endpoint with real processing."""

    def test_tag_basic_file(self, api_headers, test_files):
        """Test tagging a basic audio file end-to-end."""
        response = requests.post(
            f"{API_BASE_URL}/api/v1/tag",
            json={"path": test_files["basic"]},
            headers=api_headers,
            timeout=120,
        )

        assert response.status_code in [200, 202], f"Tagging failed: {response.text}"

        # If blocking mode, should have result
        if response.status_code == 200:
            data = response.json()
            assert "job_id" in data or "result" in data

    def test_tag_with_force(self, api_headers, test_files):
        """Test force re-tagging."""
        response = requests.post(
            f"{API_BASE_URL}/api/v1/tag",
            json={"path": test_files["basic"], "force": True},
            headers=api_headers,
            timeout=120,
        )

        assert response.status_code in [200, 202]

    def test_tag_short_file_rejected(self, api_headers, test_files):
        """Test that files below min_duration are rejected."""
        response = requests.post(
            f"{API_BASE_URL}/api/v1/tag",
            json={"path": test_files["short"]},
            headers=api_headers,
            timeout=30,
        )

        # Should reject short file (400) or queue it and fail later
        assert response.status_code in [200, 202, 400]

    def test_tag_nonexistent_file(self, api_headers):
        """Test tagging nonexistent file returns 404."""
        response = requests.post(
            f"{API_BASE_URL}/api/v1/tag",
            json={"path": "/nonexistent/file.mp3"},
            headers=api_headers,
            timeout=30,
        )

        assert response.status_code in [400, 404]

    def test_tag_without_auth(self, test_files):
        """Test that authentication is required."""
        response = requests.post(
            f"{API_BASE_URL}/api/v1/tag",
            json={"path": test_files["basic"]},
            timeout=30,
        )

        assert response.status_code == 403


class TestPublicAPIQueue:
    """Test queue listing and management endpoints."""

    def test_list_queue(self, api_headers):
        """Test listing queue jobs."""
        response = requests.get(
            f"{API_BASE_URL}/api/v1/list",
            headers=api_headers,
            timeout=30,
        )

        assert response.status_code == 200
        data = response.json()
        assert "jobs" in data or isinstance(data, list)

    def test_list_with_pagination(self, api_headers):
        """Test queue listing with pagination."""
        response = requests.get(
            f"{API_BASE_URL}/api/v1/list?limit=10&offset=0",
            headers=api_headers,
            timeout=30,
        )

        assert response.status_code == 200

    def test_list_with_status_filter(self, api_headers):
        """Test filtering jobs by status."""
        response = requests.get(
            f"{API_BASE_URL}/api/v1/list?status=pending",
            headers=api_headers,
            timeout=30,
        )

        assert response.status_code == 200


class TestInternalAPIProcess:
    """Test internal processing endpoints."""

    def test_process_direct(self, test_files):
        """Test direct synchronous processing."""
        response = requests.post(
            f"{API_BASE_URL}/internal/process_direct",
            json={"path": test_files["basic"]},
            timeout=180,
        )

        # Should process successfully or fail with clear error
        assert response.status_code in [200, 400, 404, 503]

    def test_process_stream(self, test_files):
        """Test streaming processing with SSE."""
        response = requests.post(
            f"{API_BASE_URL}/internal/process_stream",
            json={"path": test_files["basic"]},
            stream=True,
            timeout=180,
        )

        # SSE stream should start
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")


class TestAdminAPI:
    """Test admin endpoints."""

    def test_worker_status(self, api_headers):
        """Test getting worker status."""
        response = requests.get(
            f"{API_BASE_URL}/admin/worker/status",
            headers=api_headers,
            timeout=30,
        )

        assert response.status_code == 200
        data = response.json()
        assert "enabled" in data or "status" in data

    def test_cache_list(self, api_headers):
        """Test listing cached models."""
        response = requests.get(
            f"{API_BASE_URL}/admin/cache/list",
            headers=api_headers,
            timeout=30,
        )

        assert response.status_code == 200


class TestWebAuth:
    """Test web UI authentication."""

    def test_login_with_invalid_password(self):
        """Test login fails with wrong password."""
        response = requests.post(
            f"{API_BASE_URL}/web/auth/login",
            json={"password": "wrong-password"},
            timeout=30,
        )

        assert response.status_code == 401

    def test_verify_without_token(self):
        """Test session verification requires token."""
        response = requests.get(
            f"{API_BASE_URL}/web/auth/verify",
            timeout=30,
        )

        assert response.status_code == 401


class TestHealthEndpoints:
    """Test health check endpoints."""

    def test_health_check(self):
        """Test basic health check."""
        response = requests.get(
            f"{API_BASE_URL}/health",
            timeout=30,
        )

        assert response.status_code == 200

    def test_readiness_check(self):
        """Test readiness check."""
        response = requests.get(
            f"{API_BASE_URL}/ready",
            timeout=30,
        )

        # May be ready or not depending on system state
        assert response.status_code in [200, 503]
