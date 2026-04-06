"""Unit tests for nomarr.helpers.dto.info_dto module.

Tests info-related DTOs for proper structure and behavior.
"""

import pytest

from nomarr.helpers.dto.info_dto import (
    ConfigInfo,
    GPUHealthResult,
    HealthStatusResult,
    LibraryPipelineInfo,
    ModelsInfo,
    PublicInfoResult,
    QueueInfo,
    ScanningLibraryInfo,
    SystemInfoResult,
    WorkerInfo,
    WorkStatusResult,
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
        """Should handle available GPU with healthy monitor."""
        health = GPUHealthResult(
            available=True,
            error_summary=None,
            monitor_healthy=True,
        )
        assert health.available
        assert health.error_summary is None
        assert health.monitor_healthy

    @pytest.mark.unit
    def test_gpu_unavailable(self) -> None:
        """Should handle unavailable GPU."""
        health = GPUHealthResult(
            available=False,
            error_summary="CUDA out of memory",
            monitor_healthy=True,
        )
        assert not health.available
        assert health.error_summary == "CUDA out of memory"
        assert health.monitor_healthy

    @pytest.mark.unit
    def test_gpu_monitor_unhealthy(self) -> None:
        """Should handle unhealthy GPU monitor (subprocess dead/unresponsive)."""
        health = GPUHealthResult(
            available=False,
            error_summary=None,
            monitor_healthy=False,
        )
        assert not health.available
        assert not health.monitor_healthy


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


class TestLibraryPipelineInfo:
    """Tests for LibraryPipelineInfo dataclass."""

    @pytest.mark.unit
    def test_can_create_pipeline_info(self) -> None:
        """Should create pipeline info with all fields."""
        info = LibraryPipelineInfo(
            library_id="libraries/1",
            name="Rock Library",
            state="write_ready",
            library_auto_write=True,
        )
        assert info.library_id == "libraries/1"
        assert info.name == "Rock Library"
        assert info.state == "write_ready"
        assert info.library_auto_write is True

    @pytest.mark.unit
    def test_library_auto_write_false(self) -> None:
        """Should handle auto-write disabled."""
        info = LibraryPipelineInfo(
            library_id="libraries/2",
            name="Jazz Library",
            state="idle",
            library_auto_write=False,
        )
        assert not info.library_auto_write
        assert info.state == "idle"


class TestWorkStatusResult:
    """Tests for WorkStatusResult dataclass."""

    @pytest.mark.unit
    def test_can_create_with_pipeline_libraries(self) -> None:
        """Should create work status with pipeline_libraries populated."""
        pipeline_lib = LibraryPipelineInfo(
            library_id="libraries/1",
            name="Rock Library",
            state="ml_running",
            library_auto_write=False,
        )
        result = WorkStatusResult(
            is_scanning=False,
            scanning_libraries=[],
            pipeline_libraries=[pipeline_lib],
            is_processing=True,
            pending_files=50,
            processed_files=950,
            total_files=1000,
            files_per_minute=10.0,
            estimated_minutes_remaining=5.0,
            is_busy=True,
        )
        assert len(result.pipeline_libraries) == 1
        assert result.pipeline_libraries[0].state == "ml_running"
        assert result.is_processing
        assert result.is_busy

    @pytest.mark.unit
    def test_idle_state_has_no_eta(self) -> None:
        """Should represent idle system with None ETA and empty pipeline_libraries."""
        result = WorkStatusResult(
            is_scanning=False,
            scanning_libraries=[],
            pipeline_libraries=[],
            is_processing=False,
            pending_files=0,
            processed_files=100,
            total_files=100,
            files_per_minute=0.0,
            estimated_minutes_remaining=None,
            is_busy=False,
        )
        assert not result.is_busy
        assert result.estimated_minutes_remaining is None
        assert result.pipeline_libraries == []

    @pytest.mark.unit
    def test_scanning_state_is_busy(self) -> None:
        """Should treat active scanning as busy."""
        scanning = ScanningLibraryInfo(
            library_id="libraries/1",
            name="Rock Library",
            progress=50,
            total=200,
        )
        result = WorkStatusResult(
            is_scanning=True,
            scanning_libraries=[scanning],
            pipeline_libraries=[],
            is_processing=False,
            pending_files=0,
            processed_files=0,
            total_files=0,
            files_per_minute=0.0,
            estimated_minutes_remaining=None,
            is_busy=True,
        )
        assert result.is_scanning
        assert len(result.scanning_libraries) == 1
        assert result.scanning_libraries[0].progress == 50
