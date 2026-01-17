"""
Unit tests for nomarr.helpers.dto.info_dto module.

Tests info-related DTOs for proper structure and behavior.
"""

import pytest

from nomarr.helpers.dto.info_dto import (
    ConfigInfo,
    GPUHealthResult,
    HealthStatusResult,
    ModelsInfo,
    PublicInfoResult,
    QueueInfo,
    SystemInfoResult,
    WorkerInfo,
)


class TestSystemInfoResult:
    """Tests for SystemInfoResult dataclass."""

    @pytest.mark.unit
    def test_can_create_system_info(self) -> None:
        """Should create system info result."""
        info = SystemInfoResult(
            version="0.1.0",
            namespace="nom-music",
            models_dir="/models",
            worker_enabled=True,
            worker_count=4,
        )
        assert info.version == "0.1.0"
        assert info.namespace == "nom-music"
        assert info.worker_count == 4

    @pytest.mark.unit
    def test_worker_disabled_state(self) -> None:
        """Should handle disabled worker state."""
        info = SystemInfoResult(
            version="0.1.0",
            namespace="nom-music",
            models_dir="/models",
            worker_enabled=False,
            worker_count=0,
        )
        assert not info.worker_enabled
        assert info.worker_count == 0


class TestHealthStatusResult:
    """Tests for HealthStatusResult dataclass."""

    @pytest.mark.unit
    def test_can_create_healthy_status(self) -> None:
        """Should create healthy status result."""
        status = HealthStatusResult(
            status="healthy",
            processor_initialized=True,
            worker_count=4,
            queue={"depth": 0, "pending": 0},
            warnings=[],
        )
        assert status.status == "healthy"
        assert status.processor_initialized
        assert len(status.warnings) == 0

    @pytest.mark.unit
    def test_can_create_status_with_warnings(self) -> None:
        """Should handle status with warnings."""
        status = HealthStatusResult(
            status="degraded",
            processor_initialized=True,
            worker_count=2,
            queue={"depth": 100, "pending": 100},
            warnings=["Queue backlog detected", "GPU unavailable"],
        )
        assert status.status == "degraded"
        assert len(status.warnings) == 2

    @pytest.mark.unit
    def test_uninitialized_processor(self) -> None:
        """Should handle uninitialized processor."""
        status = HealthStatusResult(
            status="initializing",
            processor_initialized=False,
            worker_count=0,
            queue={},
            warnings=[],
        )
        assert not status.processor_initialized


class TestGPUHealthResult:
    """Tests for GPUHealthResult dataclass."""

    @pytest.mark.unit
    def test_gpu_available(self) -> None:
        """Should handle available GPU."""
        health = GPUHealthResult(
            available=True,
            last_check_at=1700000000.0,
            last_ok_at=1700000000.0,
            consecutive_failures=0,
            error_summary=None,
        )
        assert health.available
        assert health.consecutive_failures == 0
        assert health.error_summary is None

    @pytest.mark.unit
    def test_gpu_unavailable(self) -> None:
        """Should handle unavailable GPU."""
        health = GPUHealthResult(
            available=False,
            last_check_at=1700000000.0,
            last_ok_at=None,
            consecutive_failures=5,
            error_summary="CUDA out of memory",
        )
        assert not health.available
        assert health.consecutive_failures == 5
        assert health.error_summary == "CUDA out of memory"

    @pytest.mark.unit
    def test_gpu_never_checked(self) -> None:
        """Should handle GPU that was never checked."""
        health = GPUHealthResult(
            available=False,
            last_check_at=None,
            last_ok_at=None,
            consecutive_failures=0,
            error_summary=None,
        )
        assert health.last_check_at is None


class TestConfigInfo:
    """Tests for ConfigInfo dataclass."""

    @pytest.mark.unit
    def test_can_create_config_info(self) -> None:
        """Should create config info."""
        config = ConfigInfo(
            db_path="/data/nomarr.db",
            models_dir="/models",
            namespace="nom-music",
            api_host="0.0.0.0",
            api_port=8484,
            worker_enabled=True,
            worker_enabled_default=True,
            worker_count=4,
            poll_interval=1.0,
        )
        assert config.db_path == "/data/nomarr.db"
        assert config.api_port == 8484
        assert config.worker_count == 4

    @pytest.mark.unit
    def test_optional_fields_can_be_none(self) -> None:
        """Should handle None for optional fields."""
        config = ConfigInfo(
            db_path=None,
            models_dir="/models",
            namespace="nom-music",
            api_host=None,
            api_port=None,
            worker_enabled=False,
            worker_enabled_default=True,
            worker_count=0,
            poll_interval=1.0,
        )
        assert config.db_path is None
        assert config.api_host is None


class TestModelsInfo:
    """Tests for ModelsInfo dataclass."""

    @pytest.mark.unit
    def test_can_create_models_info(self) -> None:
        """Should create models info."""
        info = ModelsInfo(
            total_heads=25,
            embeddings=["effnet", "musicnn"],
        )
        assert info.total_heads == 25
        assert len(info.embeddings) == 2

    @pytest.mark.unit
    def test_empty_models(self) -> None:
        """Should handle no models."""
        info = ModelsInfo(
            total_heads=0,
            embeddings=[],
        )
        assert info.total_heads == 0


class TestQueueInfo:
    """Tests for QueueInfo dataclass."""

    @pytest.mark.unit
    def test_can_create_queue_info(self) -> None:
        """Should create queue info."""
        info = QueueInfo(
            depth=50,
            counts={"pending": 30, "processing": 10, "failed": 10},
        )
        assert info.depth == 50
        assert info.counts["pending"] == 30

    @pytest.mark.unit
    def test_empty_queue(self) -> None:
        """Should handle empty queue."""
        info = QueueInfo(
            depth=0,
            counts={},
        )
        assert info.depth == 0


class TestWorkerInfo:
    """Tests for WorkerInfo dataclass."""

    @pytest.mark.unit
    def test_worker_active(self) -> None:
        """Should handle active worker."""
        info = WorkerInfo(
            enabled=True,
            alive=True,
            last_heartbeat=1700000000.0,
        )
        assert info.enabled
        assert info.alive
        assert info.last_heartbeat is not None

    @pytest.mark.unit
    def test_worker_disabled(self) -> None:
        """Should handle disabled worker."""
        info = WorkerInfo(
            enabled=False,
            alive=False,
            last_heartbeat=None,
        )
        assert not info.enabled
        assert not info.alive


class TestPublicInfoResult:
    """Tests for PublicInfoResult dataclass."""

    @pytest.mark.unit
    def test_can_create_full_public_info(self) -> None:
        """Should create complete public info result."""
        config = ConfigInfo(
            db_path="/data/nomarr.db",
            models_dir="/models",
            namespace="nom-music",
            api_host="0.0.0.0",
            api_port=8484,
            worker_enabled=True,
            worker_enabled_default=True,
            worker_count=4,
            poll_interval=1.0,
        )
        models = ModelsInfo(total_heads=25, embeddings=["effnet"])
        queue = QueueInfo(depth=0, counts={})
        worker = WorkerInfo(enabled=True, alive=True, last_heartbeat=1700000000.0)

        result = PublicInfoResult(
            config=config,
            models=models,
            queue=queue,
            worker=worker,
        )

        assert result.config.namespace == "nom-music"
        assert result.models.total_heads == 25
        assert result.queue.depth == 0
        assert result.worker.alive
