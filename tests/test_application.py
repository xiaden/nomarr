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
    assert app.coordinator is None
    assert app.workers == []


def test_global_application_instance():
    """Verify global application instance exists."""
    import nomarr.app as app

    assert app.application is not None
    assert hasattr(app.application, "start")
    assert hasattr(app.application, "stop")


def test_config_loaded():
    """Verify configuration is loaded."""
    import nomarr.app as app

    assert app.cfg is not None
    assert "db_path" in app.cfg
    assert "host" in app.cfg
    assert "port" in app.cfg


def test_database_singleton():
    """Verify database singleton exists."""
    import nomarr.app as app

    assert app.db is not None
    assert hasattr(app.db, "conn")


def test_queue_singleton():
    """Verify queue singleton exists."""
    import nomarr.app as app

    assert app.queue is not None
    assert hasattr(app.queue, "add")


# NOTE: Full integration tests (start/stop lifecycle) will be added
# after LINT_ERRORS.md bugs are fixed and architecture is stable.
