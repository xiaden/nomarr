"""
Pytest configuration for smoke tests.

Provides fixtures for running tests with fake databases and test audio files.
"""

import os
import tempfile

import pytest

from tests.fixtures.generate import create_test_fixtures


@pytest.fixture(scope="session")
def test_audio_fixtures():
    """
    Generate test audio files for the entire test session.

    Returns:
        Dictionary mapping fixture names to file paths
    """
    # Generate fixtures in a temp directory for the session
    with tempfile.TemporaryDirectory() as tmpdir:
        fixtures_dir = os.path.join(tmpdir, "fixtures")
        fixtures = create_test_fixtures(fixtures_dir)

        # Yield fixtures to tests
        yield fixtures


@pytest.fixture
def temp_test_dir(tmp_path):
    """
    Create a temporary directory for test isolation.

    Returns:
        Path to temporary directory
    """
    return tmp_path


@pytest.fixture
def fake_db_dir(tmp_path):
    """
    Create a fake database directory for testing.

    Returns:
        Path to directory containing fake database
    """
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    return db_dir


@pytest.fixture
def fake_config_dir(tmp_path, fake_db_dir):
    """
    Create a fake config directory with minimal config.yaml.

    Returns:
        Path to fake config directory
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    # Create minimal config.yaml
    config_yaml = config_dir / "config.yaml"
    config_yaml.write_text("""
# Minimal test config
worker_enabled: false  # Disable worker for smoke tests
poll_interval: 10
blocking_mode: true
blocking_timeout: 30
min_duration: 7
namespace: essentia
library_path: /music
""")

    return config_dir


@pytest.fixture
def smoke_test_env(fake_config_dir, fake_db_dir):
    """
    Set up environment variables for smoke tests.

    Returns:
        Dictionary of environment variables to use
    """
    return {
        "NOMARR_CONFIG_DIR": str(fake_config_dir),
        "NOMARR_DB_PATH": str(fake_db_dir / "essentia.sqlite"),
    }
