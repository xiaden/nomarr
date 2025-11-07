"""
Pytest fixtures and configuration for the test suite.
"""

import os
import sys
import tempfile
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

# Mock essentia and tensorflow for Windows testing (these are Docker-only dependencies)
if sys.platform == "win32":
    sys.modules["essentia"] = MagicMock()
    sys.modules["essentia.standard"] = MagicMock()
    sys.modules["tensorflow"] = MagicMock()
    sys.modules["tensorflow.python"] = MagicMock()
    sys.modules["tensorflow.python.eager"] = MagicMock()
    sys.modules["scipy"] = MagicMock()
    sys.modules["scipy.signal"] = MagicMock()

# Set test environment variables before imports
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["TF_FORCE_GPU_ALLOW_GROWTH"] = "true"


@pytest.fixture
def temp_db() -> Generator[str, None, None]:
    """Provide a temporary SQLite database for testing."""
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
def temp_dir() -> Generator[Path, None, None]:
    """Provide a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_config() -> dict:
    """Provide a mock configuration dictionary."""
    return {
        "models_dir": "/app/models",
        "db_path": ":memory:",
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
    """Provide mock audio waveform data (5 seconds at 16kHz)."""
    sample_rate = 16000
    duration = 5
    # Generate simple sine wave
    t = np.linspace(0, duration, sample_rate * duration, dtype=np.float32)
    audio = np.sin(2 * np.pi * 440 * t)  # 440 Hz tone
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
def test_db(temp_db):
    """Provide a Database instance with initialized schema."""
    from nomarr.data.db import Database

    db = Database(temp_db)
    return db


@pytest.fixture
def mock_key_service(test_db):
    """Provide a KeyManagementService instance and set it in state."""
    import nomarr.app as app
    from nomarr.services.keys import KeyManagementService

    # Create service
    service = KeyManagementService(test_db)

    # Set in state for tests that use state.key_service
    original_service = app.key_service
    app.key_service = service

    yield service

    # Restore original state
    app.key_service = original_service


@pytest.fixture
def mock_job_queue(test_db):
    """Provide a JobQueue instance with initialized DB."""
    from nomarr.data.queue import JobQueue

    return JobQueue(test_db)


@pytest.fixture
def mock_api_key() -> str:
    """Provide a mock API key."""
    return "test_api_key_1234567890abcdef"


@pytest.fixture
def mock_admin_password() -> str:
    """Provide a mock admin password."""
    return "admin_password_123"


@pytest.fixture
def mock_session_token() -> str:
    """Provide a mock session token."""
    return "session_token_abcdef123456"


@pytest.fixture
def mock_predictor():
    """Provide a mock predictor function."""

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
    """Provide a mock TagWriter."""
    writer = MagicMock()
    writer.read_tags.return_value = {}
    writer.write_tags.return_value = None
    return writer


@pytest.fixture(autouse=True)
def reset_cache():
    """Reset the predictor cache between tests."""
    yield
    # Clear cache after each test to prevent state leakage
    try:
        from nomarr.ml.cache import clear_predictor_cache

        clear_predictor_cache()
    except Exception:
        pass  # Cache may not be initialized
