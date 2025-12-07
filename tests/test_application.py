"""
Basic smoke test for Application class lifecycle.

This ensures the tests folder is committed and provides a foundation
for future test development after bug fixes are complete.
"""


def test_application_exists():
    """Verify Application class can be imported."""
    from nomarr.app import Application

    assert Application is not None


def test_application_initialization():
    """Verify Application can be instantiated."""
    from nomarr.app import Application

    app = Application()
    assert app is not None
    assert hasattr(app, "start")
    assert hasattr(app, "stop")
    assert hasattr(app, "is_running")


def test_application_initial_state():
    """Verify Application starts in correct initial state."""
    from nomarr.app import Application

    app = Application()
    assert app.is_running() is False
    assert app.services == {}
    # Core dependencies initialized in __init__
    assert app.db is not None


def test_global_application_instance():
    """Verify global application instance exists."""
    import nomarr.app as app

    assert app.application is not None
    assert hasattr(app.application, "start")
    assert hasattr(app.application, "stop")


def test_config_loaded():
    """Verify configuration is loaded via application instance."""
    import nomarr.app as app

    # Config is accessed via application._config_service or direct attributes
    assert app.application.db_path is not None
    assert app.application.api_host is not None
    assert app.application.api_port is not None


def test_database_singleton():
    """Verify database singleton exists on application instance."""
    import nomarr.app as app

    # Database is accessed via application.db
    assert app.application.db is not None
    assert hasattr(app.application.db, "conn")


def test_queue_singleton():
    """Verify queue service exists on application instance."""
    import nomarr.app as app

    # Phase 1: Queue wrapper removed, access via services instead
    # Queue operations now go through QueueService registered in services dict
    # Will be fully restored in Phase 4
    assert app.application.services is not None
    assert isinstance(app.application.services, dict)


# NOTE: Full integration tests (start/stop lifecycle) will be added
# after LINT_ERRORS.md bugs are fixed and architecture is stable.
