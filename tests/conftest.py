"""
Pytest fixtures and configuration for the test suite.

Smart mocking strategy:
- Try to import real dependencies first
- Only mock if unavailable
- Mark tests with what's being mocked
- Use real database (in-memory) for unit tests
"""

import os
import sys
import tempfile
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

# Add project root to path so tests can import nomarr package
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Set test environment variables before imports
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["TF_FORCE_GPU_ALLOW_GROWTH"] = "true"


# === SMART DEPENDENCY DETECTION ===
def _check_essentia():
    """Check if Essentia is available."""
    try:
        import essentia.standard as es

        return True, es
    except ImportError:
        return False, None


def _check_tensorflow():
    """Check if TensorFlow is available."""
    try:
        import tensorflow as tf

        return True, tf
    except ImportError:
        return False, None


def _check_scipy():
    """Check if SciPy is available."""
    try:
        import scipy.signal

        return True, scipy.signal
    except ImportError:
        return False, None


# Check availability
ESSENTIA_AVAILABLE: bool
TENSORFLOW_AVAILABLE: bool
SCIPY_AVAILABLE: bool

ESSENTIA_AVAILABLE, ESSENTIA_MODULE = _check_essentia()
TENSORFLOW_AVAILABLE, TENSORFLOW_MODULE = _check_tensorflow()
SCIPY_AVAILABLE, SCIPY_MODULE = _check_scipy()

# Apply mocks ONLY if dependencies are unavailable
if not ESSENTIA_AVAILABLE:
    sys.modules["essentia"] = MagicMock()
    sys.modules["essentia.standard"] = MagicMock()
    print("⚠️  Essentia not available - using mocks")

if not TENSORFLOW_AVAILABLE:
    sys.modules["tensorflow"] = MagicMock()
    sys.modules["tensorflow.python"] = MagicMock()
    sys.modules["tensorflow.python.eager"] = MagicMock()
    print("⚠️  TensorFlow not available - using mocks")

if not SCIPY_AVAILABLE:
    sys.modules["scipy"] = MagicMock()
    sys.modules["scipy.signal"] = MagicMock()
    print("⚠️  SciPy not available - using mocks")


# === DEPENDENCY AVAILABILITY FIXTURES ===
@pytest.fixture(scope="session")
def essentia_available() -> bool:
    """Indicate whether Essentia is available."""
    return ESSENTIA_AVAILABLE


@pytest.fixture(scope="session")
def tensorflow_available() -> bool:
    """Indicate whether TensorFlow is available."""
    return TENSORFLOW_AVAILABLE


@pytest.fixture(scope="session")
def scipy_available() -> bool:
    """Indicate whether SciPy is available."""
    return SCIPY_AVAILABLE


@pytest.fixture
def skip_if_no_essentia(essentia_available):
    """Skip test if Essentia is not available."""
    if not essentia_available:
        pytest.skip("Essentia not available")


@pytest.fixture
def skip_if_no_tensorflow(tensorflow_available):
    """Skip test if TensorFlow is not available."""
    if not tensorflow_available:
        pytest.skip("TensorFlow not available")


# === DATABASE FIXTURES ===


@pytest.fixture
def temp_db() -> Generator[str, None, None]:
    """Provide a temporary SQLite database for testing.

    This uses a real SQLite file to test actual database behavior.
    For faster unit tests, use in_memory_db fixture.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        yield db_path
    finally:
        # Close any open connections before cleanup
        import gc

        gc.collect()  # Force garbage collection to close connections

        # Try to remove the file (may fail on Windows if still locked)
        try:
            if os.path.exists(db_path):
                os.unlink(db_path)
        except PermissionError:
            pass  # File still locked, will be cleaned up eventually


@pytest.fixture
def test_db(temp_db):
    """Provide a Database instance with initialized schema (real DB file)."""
    from nomarr.persistence.db import Database

    db = Database(temp_db)
    return db


@pytest.fixture
def default_library(test_db):
    """Provide a default library ID for testing."""
    library_id = test_db.libraries.create_library(
        name="Test Library",
        root_path="/music",
        is_enabled=True,
        is_default=True,
    )
    return library_id


@pytest.fixture
def in_memory_db():
    """Provide an in-memory Database instance for fast unit tests."""
    from nomarr.persistence.db import Database

    db = Database(":memory:")
    return db


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_audio_file(temp_dir) -> Generator[Path, None, None]:
    """Provide a temporary audio file for testing.

    Creates a real MP3 file with minimal valid structure.
    Use this for integration tests that need actual audio files.
    """
    audio_path = temp_dir / "test_audio.mp3"

    # Create minimal valid MP3 file (ID3v2 + minimal audio frame)
    # This is enough for tag reading/writing tests
    id3v2_header = b"ID3\x03\x00\x00\x00\x00\x00\x00"  # ID3v2.3, no tags
    # MP3 frame header: MPEG1 Layer3, 128kbps, 44100Hz, no padding
    mp3_frame = b"\xff\xfb\x90\x00" + b"\x00" * 417  # Minimal frame

    with open(audio_path, "wb") as f:
        f.write(id3v2_header)
        f.write(mp3_frame)

    yield audio_path


@pytest.fixture
def temp_music_library(temp_dir) -> Generator[Path, None, None]:
    """Provide a temporary music library structure for testing.

    Creates a realistic library structure:
    /Artist1/Album1/Track1.mp3
    /Artist1/Album1/Track2.mp3
    /Artist2/Album2/Track3.mp3
    """
    library_path = temp_dir / "music"
    library_path.mkdir()

    # Create Artist1/Album1 structure
    artist1_path = library_path / "Artist1"
    album1_path = artist1_path / "Album1"
    album1_path.mkdir(parents=True)

    # Create Artist2/Album2 structure
    artist2_path = library_path / "Artist2"
    album2_path = artist2_path / "Album2"
    album2_path.mkdir(parents=True)

    # Create minimal MP3 files
    id3v2_header = b"ID3\x03\x00\x00\x00\x00\x00\x00"
    mp3_frame = b"\xff\xfb\x90\x00" + b"\x00" * 417

    tracks = [
        album1_path / "Track1.mp3",
        album1_path / "Track2.mp3",
        album2_path / "Track3.mp3",
    ]

    for track in tracks:
        with open(track, "wb") as f:
            f.write(id3v2_header)
            f.write(mp3_frame)

    yield library_path


# === MOCK DATA FIXTURES ===


@pytest.fixture
def mock_config() -> dict:
    """Provide a mock configuration dictionary with in-memory database.

    Use this for unit tests that need config but don't require persistent DB.
    """
    return {
        "models_dir": "/app/models",
        "db_path": ":memory:",  # Fast in-memory DB for unit tests
        "namespace": "essentia",
        "worker_enabled": False,  # Disabled for tests
        "poll_interval": 2,
        "blocking_mode": True,
        "blocking_timeout": 300,
        "cache_idle_timeout": 300,
        "cache_auto_evict": True,
        "library_path": "/music",
        "library_scan_poll_interval": 10,
        "worker_count": 1,
        "log_level": "ERROR",
    }


@pytest.fixture
def mock_audio_data() -> np.ndarray:
    """Provide mock audio waveform data (5 seconds at 16kHz).

    This is synthetic data - use for unit tests that don't need real audio.
    """
    sample_rate = 16000
    duration = 5
    # Generate simple sine wave
    t = np.linspace(0, duration, sample_rate * duration, dtype=np.float32)
    audio: np.ndarray = np.sin(2 * np.pi * 440 * t)  # 440 Hz tone
    return audio


@pytest.fixture
def mock_embeddings() -> np.ndarray:
    """Provide mock embeddings (batch of 10 embeddings, 512-dim)."""
    return np.random.randn(10, 512).astype(np.float32)


@pytest.fixture
def mock_head_scores() -> np.ndarray:
    """Provide mock head output scores (10 segments, 5 classes)."""
    # Softmax-like scores
    scores = np.random.rand(10, 5).astype(np.float32)
    scores = scores / scores.sum(axis=1, keepdims=True)
    return scores


# === MODEL MOCK FIXTURES ===


@pytest.fixture
def mock_sidecar() -> dict:
    """Provide a mock model sidecar JSON matching real structure."""
    return {
        "schema_version": "1.0",
        "name": "test_model",
        "version": "1",
        "description": "Test model for unit tests",
        "type": "multiclass",
        "classes": ["class_a", "class_b", "class_c", "class_d", "class_e"],
        "predictor_class": "TensorflowPredictVGGish",
        "predictor_params": {"input": "melspectrogram", "output": "embeddings"},
    }


@pytest.fixture
def mock_multilabel_sidecar() -> dict:
    """Provide a mock multilabel model sidecar JSON matching real structure."""
    return {
        "schema_version": "1.0",
        "name": "test_multilabel",
        "version": "1",
        "description": "Test multilabel model",
        "type": "multilabel",
        "classes": ["tag1", "tag2", "tag3"],
        "predictor_class": "TensorflowPredictVGGish",
        "predictor_params": {"input": "melspectrogram", "output": "embeddings"},
    }


@pytest.fixture
def mock_regression_sidecar() -> dict:
    """Provide a mock regression model sidecar JSON matching real structure."""
    return {
        "schema_version": "1.0",
        "name": "test_regression",
        "version": "1",
        "description": "Test regression model",
        "type": "regression",
        "classes": ["energy"],
        "predictor_class": "TensorflowPredictVGGish",
        "predictor_params": {"input": "melspectrogram", "output": "embeddings"},
    }


@pytest.fixture
def mock_predictor():
    """Provide a mock predictor function.

    Use this for unit tests of tag aggregation or writing logic.
    For integration tests, try to use real models if available.
    """

    def predictor(embeddings: np.ndarray, batch_size: int = 32) -> np.ndarray:
        """Mock predictor returns random scores matching input batch size."""
        n_segments = len(embeddings)
        n_classes = 5
        scores = np.random.rand(n_segments, n_classes).astype(np.float32)
        scores = scores / scores.sum(axis=1, keepdims=True)
        return scores

    return predictor


@pytest.fixture
def mock_tag_writer():
    """Provide a mock TagWriter.

    Use for unit tests that don't need to actually write files.
    For integration tests, use real file I/O with temp files.
    """
    writer = MagicMock()
    writer.read_tags.return_value = {}
    writer.write_tags.return_value = None
    return writer


# === SERVICE FIXTURES ===


@pytest.fixture
def real_queue_service(test_db):
    """Provide a real QueueService instance for testing.

    This uses a real Database and ProcessingQueue - not mocked.
    Use for service layer and integration tests.
    """
    from nomarr.services.queue_service import ProcessingQueue, QueueService

    queue = ProcessingQueue(test_db)
    return QueueService(queue)


@pytest.fixture
def real_processing_service(test_db):
    """Provide a real ProcessingService instance for testing.

    Note: This service requires ProcessingCoordinator which may not be
    available in all test contexts. Tests using this should handle
    coordinator unavailability gracefully.
    """
    from nomarr.services.processing_service import ProcessingService

    return ProcessingService()


@pytest.fixture
def real_library_service(test_db, temp_music_library):
    """Provide a real LibraryService instance for testing with temp library root."""
    from nomarr.services.library_service import LibraryRootConfig, LibraryService

    cfg = LibraryRootConfig(namespace="nom", library_root=str(temp_music_library))
    return LibraryService(test_db, cfg)


@pytest.fixture
def real_worker_service(test_db):
    """Provide a real WorkerService instance for testing."""
    from nomarr.services.queue_service import ProcessingQueue
    from nomarr.services.worker_service import WorkerConfig, WorkerService

    queue = ProcessingQueue(test_db)
    # Disable workers by default for tests (avoids event_broker requirement)
    cfg = WorkerConfig(default_enabled=False, worker_count=1, poll_interval=1)
    return WorkerService(test_db, queue, cfg)


@pytest.fixture
def real_health_monitor(test_db):
    """Provide a real HealthMonitorService instance for testing."""
    from nomarr.services.health_monitor_service import HealthMonitorConfig, HealthMonitorService

    cfg = HealthMonitorConfig(check_interval=1)
    return HealthMonitorService(cfg)


@pytest.fixture
def real_key_service(test_db):
    """Provide a real KeyManagementService for integration testing.

    This is a real service instance for integration testing.
    """
    from nomarr.services.keys_service import KeyManagementService

    # Create and return service directly - tests should use this fixture
    service = KeyManagementService(test_db)
    return service


@pytest.fixture
def mock_job_queue(test_db):
    """Provide a ProcessingQueue instance with real DB.

    This is a real queue for integration testing - uses actual database operations.
    """
    from nomarr.services.queue_service import ProcessingQueue

    return ProcessingQueue(test_db)


# === AUTH/SECURITY FIXTURES ===


# === AUTH/SECURITY FIXTURES ===


@pytest.fixture
def mock_api_key() -> str:
    """Provide a mock API key for authentication testing."""
    return "test_api_key_1234567890abcdef"


@pytest.fixture
def mock_admin_password() -> str:
    """Provide a mock admin password for authentication testing."""
    return "admin_password_123"


@pytest.fixture
def mock_session_token() -> str:
    """Provide a mock session token for web UI testing."""
    return "session_token_abcdef123456"


# === API/APPLICATION FIXTURES ===


@pytest.fixture
def test_application(test_db, mock_config):
    """Provide a real Application instance for integration testing.

    This creates a minimal Application with real services but test database.
    Use for API endpoint tests and CLI integration tests.
    """
    import os

    from nomarr.app import Application

    # Override config environment to use test database
    original_db_path = os.environ.get("NOMARR_DB_PATH")
    os.environ["NOMARR_DB_PATH"] = test_db.db_path

    app = Application()
    app.start()

    yield app

    # Cleanup
    app.stop()

    # Restore original environment
    if original_db_path is not None:
        os.environ["NOMARR_DB_PATH"] = original_db_path
    elif "NOMARR_DB_PATH" in os.environ:
        del os.environ["NOMARR_DB_PATH"]


@pytest.fixture
def test_client(test_application):
    """Provide a FastAPI TestClient for API testing.

    This uses a real Application instance with test database.
    Use for testing HTTP endpoints without running actual server.
    """
    from fastapi.testclient import TestClient

    from nomarr.interfaces.api import api_app as fastapi_app

    # Note: test_application must be started before creating client
    return TestClient(fastapi_app)


@pytest.fixture
def cli_runner():
    """Provide a Click CliRunner for CLI testing.

    Use for testing CLI commands without subprocess calls.
    """
    from click.testing import CliRunner

    return CliRunner()


# === CACHE MANAGEMENT ===


@pytest.fixture(autouse=True)
def reset_cache():
    """Reset the predictor cache between tests to prevent state leakage.

    This runs automatically for all tests.
    """
    yield
    # Clear cache after each test
    try:
        from nomarr.components.ml.cache import clear_predictor_cache

        clear_predictor_cache()
    except Exception:
        pass  # Cache may not be initialized


# === PYTEST MARKERS ===


def pytest_configure(config):
    """Register custom pytest markers."""
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line("markers", "integration: mark test as integration test (requires full system)")
    config.addinivalue_line("markers", "requires_ml: mark test as requiring ML dependencies (Essentia/TF)")
    config.addinivalue_line("markers", "requires_audio: mark test as requiring real audio files")
