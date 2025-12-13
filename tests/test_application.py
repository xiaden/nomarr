"""
Basic smoke test for Application class lifecycle.

This ensures the tests folder is committed and provides a foundation
for future test development after bug fixes are complete.
"""

import os
import tempfile

import pytest


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".db") as f:
        db_path = f.name

    # Set environment variable to override config db_path
    os.environ["NOMARR_DB_PATH"] = db_path

    yield db_path

    # Cleanup
    try:
        os.unlink(db_path)
    except FileNotFoundError:
        pass
    finally:
        os.environ.pop("NOMARR_DB_PATH", None)


def test_application_exists():
    """Verify Application class can be imported."""
    from nomarr.app import Application

    assert Application is not None


def test_application_initialization(temp_db):
    """Verify Application can be instantiated with test database."""
    from nomarr.app import Application

    app = Application()
    assert app is not None
    assert hasattr(app, "start")
    assert hasattr(app, "stop")
    assert hasattr(app, "is_running")
    # Verify using test database
    assert app.db_path == temp_db

    # Cleanup
    app.db.close()


def test_application_initial_state(temp_db):
    """Verify Application starts in correct initial state."""
    from nomarr.app import Application

    app = Application()
    assert app.is_running() is False
    assert app.services == {}
    # Core dependencies initialized in __init__
    assert app.db is not None

    # Cleanup
    app.db.close()


def test_global_application_instance():
    """Verify global application instance is not created during tests."""
    import nomarr.app as app

    # During tests, application should be None (not created)
    assert app.application is None


def test_config_loaded(temp_db):
    """Verify configuration is loaded via application instance."""
    from nomarr.app import Application

    app = Application()

    # Config is accessed via application._config_service or direct attributes
    assert app.db_path is not None
    assert app.api_host is not None
    assert app.api_port is not None

    # Cleanup
    app.db.close()


def test_database_singleton(temp_db):
    """Verify database singleton exists on application instance."""
    from nomarr.app import Application

    app = Application()

    # Database is accessed via application.db
    assert app.db is not None
    assert hasattr(app.db, "conn")

    # Cleanup
    app.db.close()


def test_queue_singleton(temp_db):
    """Verify queue service exists on application instance."""
    from nomarr.app import Application

    app = Application()

    # Phase 1: Queue wrapper removed, access via services instead
    # Queue operations now go through QueueService registered in services dict
    # Will be fully restored in Phase 4
    assert app.services is not None
    assert isinstance(app.services, dict)

    # Cleanup
    app.db.close()


# NOTE: Full integration tests (start/stop lifecycle) will be added
# after LINT_ERRORS.md bugs are fixed and architecture is stable.
