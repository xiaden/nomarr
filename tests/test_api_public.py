"""
Integration tests for public API endpoints (/api/v1/tag, /api/v1/list, /api/v1/status, etc.)
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api_client(test_db, tmp_path, monkeypatch):
    """Create TestClient with mocked dependencies."""
    import nomarr.app as app
    from nomarr.data.queue import JobQueue
    from nomarr.interfaces.api.api_app import api_app
    from nomarr.interfaces.api.auth import get_or_create_api_key
    from nomarr.interfaces.api.coordinator import ProcessingCoordinator
    from nomarr.services.queue import QueueService
    from nomarr.services.worker import WorkerService

    # Create test queue
    queue = JobQueue(test_db)

    # Create services
    queue_service = QueueService(test_db, queue)
    worker_service = WorkerService(test_db, queue, default_enabled=False)

    # Mock ProcessingCoordinator to avoid worker pool issues
    mock_coordinator = ProcessingCoordinator(num_workers=1)  # Set module-level globals (what endpoints actually use)
    monkeypatch.setattr(app, "db", test_db)
    monkeypatch.setattr(app, "queue", queue)
    monkeypatch.setattr(app, "queue_service", queue_service)
    monkeypatch.setattr(app, "worker_service", worker_service)
    monkeypatch.setattr(app, "worker_pool", None)
    monkeypatch.setattr(app, "processor_coord", mock_coordinator)
    monkeypatch.setattr(app, "BLOCKING_MODE", False)  # Disable blocking for fast tests
    monkeypatch.setattr(app, "BLOCKING_TIMEOUT", 1)  # Short timeout for tests
    monkeypatch.setattr(app, "WORKER_POLL_INTERVAL", 0.1)  # Fast polling for tests
    monkeypatch.setattr(app, "WORKER_ENABLED_DEFAULT", False)
    monkeypatch.setattr(app, "WORKER_COUNT", 1)
    monkeypatch.setattr(app, "cfg", {"paths": {"models_dir": str(tmp_path / "models")}, "namespace": "essentia"})
    monkeypatch.setattr(app, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(app, "API_HOST", "0.0.0.0")
    monkeypatch.setattr(app, "API_PORT", 8356)

    # Create API key for auth
    api_key = get_or_create_api_key(test_db)

    # Set mock database and API key in app for the API to use
    monkeypatch.setattr(app, "db", test_db)
    monkeypatch.setattr(app, "API_KEY", api_key)
    monkeypatch.setattr(app, "INTERNAL_KEY", "test_internal_key")

    # Return client with api_key attached for convenience
    class ClientWithAuth(TestClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.api_key = api_key

        def post(self, *args, **kwargs):
            if "headers" not in kwargs:
                kwargs["headers"] = {}
            kwargs["headers"]["Authorization"] = f"Bearer {self.api_key}"
            return super().post(*args, **kwargs)

        def get(self, *args, **kwargs):
            if "headers" not in kwargs:
                kwargs["headers"] = {}
            kwargs["headers"]["Authorization"] = f"Bearer {self.api_key}"
            return super().get(*args, **kwargs)

    auth_client = ClientWithAuth(api_app)
    auth_client.api_key = api_key

    yield auth_client

    # Cleanup: Reset dependency overrides
    api_app.dependency_overrides.clear()


@pytest.mark.integration
class TestTagEndpoint:
    """Test POST /tag endpoint."""

    def test_tag_audio_success(self, api_client, tmp_path):
        """Test queueing a file for tagging."""
        # Create a test file
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"fake audio data")

        response = api_client.post("/api/v1/tag", json={"path": str(test_file)})

        # Debug: Print error if not 200
        if response.status_code != 200:
            print(f"Error response: {response.json()}")

        assert response.status_code == 200

        data = response.json()
        # API returns full job object with 'id' field (not 'job_id')
        assert "id" in data
        assert data["status"] in ("queued", "pending", "done")
        assert data["path"] == str(test_file)

    def test_tag_audio_missing_file(self, api_client):
        """Test tagging non-existent file returns 404."""
        response = api_client.post("/api/v1/tag", json={"path": "/nonexistent/file.mp3"})
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_tag_audio_force_flag(self, api_client, tmp_path):
        """Test force flag is respected."""
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"fake audio data")

        response = api_client.post("/api/v1/tag", json={"path": str(test_file), "force": True})
        assert response.status_code == 200

        data = response.json()
        # API returns full job object with 'id' field
        assert "id" in data
        assert data["force"] is True

    def test_tag_audio_missing_auth(self, api_client):
        """Test missing authorization returns 401."""
        # Remove auth header
        client_no_auth = TestClient(api_client.app)
        response = client_no_auth.post("/api/v1/tag", json={"path": "/music/test.mp3"})
        assert response.status_code == 401  # 401 for missing auth, 403 for invalid auth

    def test_tag_audio_invalid_auth(self, api_client):
        """Test invalid API key returns 403."""
        client_bad_auth = TestClient(api_client.app)
        client_bad_auth.headers = {"Authorization": "Bearer invalid_key"}
        response = client_bad_auth.post("/api/v1/tag", json={"path": "/music/test.mp3"})
        assert response.status_code == 403


@pytest.mark.integration
class TestListEndpoint:
    """Test GET /list endpoint."""

    def test_list_jobs_empty(self, api_client):
        """Test listing jobs when queue is empty."""
        response = api_client.get("/api/v1/list")
        assert response.status_code == 200

        data = response.json()
        assert data["jobs"] == []
        assert data["total"] == 0
        assert data["limit"] == 50
        assert data["offset"] == 0

    def test_list_jobs_with_jobs(self, api_client, tmp_path):
        """Test listing jobs."""
        # Queue some jobs
        for i in range(3):
            test_file = tmp_path / f"test{i}.mp3"
            test_file.write_bytes(b"fake audio")
            api_client.post("/api/v1/tag", json={"path": str(test_file)})

        response = api_client.get("/api/v1/list")
        assert response.status_code == 200

        data = response.json()
        assert len(data["jobs"]) == 3
        assert data["total"] == 3

    def test_list_jobs_pagination(self, api_client, tmp_path):
        """Test pagination with limit and offset."""
        # Queue 5 jobs
        for i in range(5):
            test_file = tmp_path / f"test{i}.mp3"
            test_file.write_bytes(b"fake audio")
            api_client.post("/api/v1/tag", json={"path": str(test_file)})

        # Get first 2
        response = api_client.get("/api/v1/list?limit=2&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert len(data["jobs"]) == 2
        assert data["total"] == 5
        assert data["limit"] == 2
        assert data["offset"] == 0

        # Get next 2
        response = api_client.get("/api/v1/list?limit=2&offset=2")
        data = response.json()
        assert len(data["jobs"]) == 2
        assert data["offset"] == 2

    def test_list_jobs_status_filter(self, api_client, tmp_path):
        """Test filtering by status."""
        # Queue a job and mark it running
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"fake audio")
        resp = api_client.post("/api/v1/tag", json={"path": str(test_file)})
        job_id = resp.json()["id"]  # Changed from job_id to id

        # Mark it as running via queue
        import nomarr.app as app

        app.queue.start(job_id)

        # Filter by pending
        response = api_client.get("/api/v1/list?status=pending")
        data = response.json()
        assert all(job["status"] == "pending" for job in data["jobs"])

        # Filter by running
        response = api_client.get("/api/v1/list?status=running")
        data = response.json()
        assert len(data["jobs"]) == 1
        # All endpoints now use Job.to_dict() which returns "id"
        assert data["jobs"][0]["id"] == job_id
        assert data["jobs"][0]["status"] == "running"


@pytest.mark.integration
class TestStatusEndpoint:
    """Test GET /status/{job_id} endpoint."""

    def test_get_status_success(self, api_client, tmp_path):
        """Test getting job status."""
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"fake audio")

        # Queue a job
        resp = api_client.post("/api/v1/tag", json={"path": str(test_file)})
        job_id = resp.json()["id"]  # Changed from job_id to id

        # Get its status
        response = api_client.get(f"/api/v1/status/{job_id}")
        assert response.status_code == 200

        data = response.json()
        # All endpoints now use Job.to_dict() which returns "id"
        assert data["id"] == job_id
        assert data["status"] in ("pending", "queued", "done")
        assert data["path"] == str(test_file)

    def test_get_status_nonexistent(self, api_client):
        """Test getting status for non-existent job returns 404."""
        response = api_client.get("/api/v1/status/99999")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


@pytest.mark.integration
class TestInfoEndpoint:
    """Test GET /info endpoint."""

    def test_get_info(self, api_client):
        """Test getting system info."""
        response = api_client.get("/api/v1/info")
        assert response.status_code == 200

        data = response.json()
        # Should have config section
        assert "config" in data
        assert "models_dir" in data["config"]

        # Should have queue stats
        assert "queue" in data
        assert "depth" in data["queue"]
