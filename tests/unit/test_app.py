"""Unit tests for ``nomarr.app`` — Application composition root.

Tests cover the unit-testable surface of ``Application`` without triggering
the heavy ``__init__`` (which opens a real PostgreSQL connection and validates
the environment). We bypass construction with ``object.__new__(Application)``
and manually set only the attributes each test needs.
"""

from __future__ import annotations

import logging
import os
from unittest.mock import MagicMock

# Ensure the module-level Application() construction in nomarr.app doesn't
# fail during import. The guard checks PYTEST_CURRENT_TEST, but that env var
# is only set by pytest *during* test execution, not at collection/import time.
# Setting it here lets the import succeed without a real PG_DATABASE_URL.
os.environ.setdefault("PYTEST_CURRENT_TEST", "tests/unit/test_app.py")

import pytest

from nomarr.app import Application, validate_environment

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bare_application() -> Application:
    """Build an ``Application`` without running ``__init__``.

    ``Application.__init__`` calls ``validate_environment``, opens a real
    ``Database``, and runs database migrations — none of which we want in a
    unit test. ``object.__new__`` gives us an empty shell we can populate
    with only the attributes the method under test touches.
    """
    app = object.__new__(Application)
    app.services = {}
    app.worker_system = None
    app._running = False
    return app


# ===========================================================================
# validate_environment()
# ===========================================================================


class TestValidateEnvironment:
    """Tests for the module-level ``validate_environment`` function."""

    @pytest.mark.unit
    def test_passes_when_pg_database_url_is_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No error when the required env var is present."""
        monkeypatch.setenv("PG_DATABASE_URL", "postgresql+psycopg2://u:p@h/db")
        validate_environment()  # Should not raise

    @pytest.mark.unit
    def test_exits_when_pg_database_url_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing required env var triggers ``sys.exit(1)``."""
        monkeypatch.delenv("PG_DATABASE_URL", raising=False)
        mock_exit = MagicMock(side_effect=SystemExit(1))
        monkeypatch.setattr("sys.exit", mock_exit)

        with pytest.raises(SystemExit):
            validate_environment()

        mock_exit.assert_called_once_with(1)

    @pytest.mark.unit
    def test_exits_when_pg_database_url_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty string is treated as missing (``os.getenv`` returns ``""``)."""
        monkeypatch.setenv("PG_DATABASE_URL", "")
        mock_exit = MagicMock(side_effect=SystemExit(1))
        monkeypatch.setattr("sys.exit", mock_exit)

        with pytest.raises(SystemExit):
            validate_environment()

        mock_exit.assert_called_once_with(1)

    @pytest.mark.unit
    def test_logs_critical_with_missing_var_names(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The critical log should name the missing variables."""
        monkeypatch.delenv("PG_DATABASE_URL", raising=False)
        monkeypatch.setattr("sys.exit", MagicMock(side_effect=SystemExit(1)))

        with caplog.at_level(logging.CRITICAL), pytest.raises(SystemExit):
            validate_environment()

        assert any("PG_DATABASE_URL" in record.message for record in caplog.records)


# ===========================================================================
# Application.register_service / get_service
# ===========================================================================


class TestApplicationServices:
    """Tests for the DI container methods on ``Application``."""

    @pytest.mark.unit
    def test_register_service_stores_instance(self) -> None:
        """``register_service`` adds the service to ``self.services``."""
        app = _make_bare_application()
        mock_svc = MagicMock()

        app.register_service("config", mock_svc)

        assert app.services["config"] is mock_svc

    @pytest.mark.unit
    def test_register_multiple_services(self) -> None:
        """Multiple services can coexist in the container."""
        app = _make_bare_application()
        svc_a = MagicMock(name="svc_a")
        svc_b = MagicMock(name="svc_b")

        app.register_service("a", svc_a)
        app.register_service("b", svc_b)

        assert app.services["a"] is svc_a
        assert app.services["b"] is svc_b

    @pytest.mark.unit
    def test_register_service_overwrites_existing(self) -> None:
        """Re-registering the same name replaces the previous service."""
        app = _make_bare_application()
        original = MagicMock(name="original")
        replacement = MagicMock(name="replacement")

        app.register_service("config", original)
        app.register_service("config", replacement)

        assert app.services["config"] is replacement

    @pytest.mark.unit
    def test_get_service_returns_registered(self) -> None:
        """``get_service`` returns the instance registered under that name."""
        app = _make_bare_application()
        mock_svc = MagicMock()
        app.register_service("library", mock_svc)

        result = app.get_service("library")

        assert result is mock_svc

    @pytest.mark.unit
    def test_get_service_raises_keyerror_when_missing(self) -> None:
        """Requesting an unknown service raises ``KeyError`` with a helpful message."""
        app = _make_bare_application()

        with pytest.raises(KeyError) as exc_info:
            app.get_service("nonexistent")

        assert "nonexistent" in str(exc_info.value)
        assert "Available services" in str(exc_info.value)

    @pytest.mark.unit
    def test_get_service_error_lists_registered_names(self) -> None:
        """The KeyError message should enumerate the services that ARE available."""
        app = _make_bare_application()
        app.register_service("config", MagicMock())
        app.register_service("library", MagicMock())

        with pytest.raises(KeyError) as exc_info:
            app.get_service("missing")

        message = str(exc_info.value)
        assert "config" in message
        assert "library" in message


# ===========================================================================
# Application.is_running
# ===========================================================================


class TestApplicationIsRunning:
    """Tests for ``Application.is_running``."""

    @pytest.mark.unit
    def test_returns_false_after_construction(self) -> None:
        """Freshly-built application is not running."""
        app = _make_bare_application()
        assert app.is_running() is False

    @pytest.mark.unit
    def test_returns_true_when_running_flag_set(self) -> None:
        """``is_running`` reflects the ``_running`` attribute."""
        app = _make_bare_application()
        app._running = True
        assert app.is_running() is True


# ===========================================================================
# Application._on_tagger_worker_count_changed
# ===========================================================================


class TestApplicationWorkerCount:
    """Tests for the live config callback ``_on_tagger_worker_count_changed``."""

    @pytest.fixture
    def app_with_mocks(self) -> tuple[Application, MagicMock, MagicMock]:
        """Return an ``Application`` with mocked ``worker_system`` and ``_config_service``."""
        app = _make_bare_application()
        app.worker_system = MagicMock()
        app._config_service = MagicMock()
        return app, app.worker_system, app._config_service

    @pytest.mark.unit
    def test_noop_when_worker_system_is_none(self) -> None:
        """If worker_system hasn't been wired yet, the callback is a no-op."""
        app = _make_bare_application()
        app.worker_system = None
        app._config_service = MagicMock()

        # Should not raise
        app._on_tagger_worker_count_changed("tagger_worker_count", 4)

        # _config_service is never consulted because we return early
        app._config_service.get_worker_count.assert_not_called()

    @pytest.mark.unit
    def test_adds_workers_when_delta_positive(self, app_with_mocks: tuple[Application, MagicMock, MagicMock]) -> None:
        """When desired > current, ``add_workers(delta)`` is called."""
        app, worker_system, config_service = app_with_mocks
        config_service.get_worker_count.return_value = 5  # new desired
        worker_system.get_worker_count.return_value = 2  # current

        app._on_tagger_worker_count_changed("tagger_worker_count", 5)

        worker_system.add_workers.assert_called_once_with(3)
        worker_system.remove_workers.assert_not_called()

    @pytest.mark.unit
    def test_removes_workers_when_delta_negative(
        self, app_with_mocks: tuple[Application, MagicMock, MagicMock]
    ) -> None:
        """When desired < current, ``remove_workers(abs(delta))`` is called."""
        app, worker_system, config_service = app_with_mocks
        config_service.get_worker_count.return_value = 1  # new desired
        worker_system.get_worker_count.return_value = 4  # current

        app._on_tagger_worker_count_changed("tagger_worker_count", 1)

        worker_system.remove_workers.assert_called_once_with(3)
        worker_system.add_workers.assert_not_called()

    @pytest.mark.unit
    def test_noop_when_delta_zero(self, app_with_mocks: tuple[Application, MagicMock, MagicMock]) -> None:
        """When desired == current, neither add nor remove is called."""
        app, worker_system, config_service = app_with_mocks
        config_service.get_worker_count.return_value = 3
        worker_system.get_worker_count.return_value = 3

        app._on_tagger_worker_count_changed("tagger_worker_count", 3)

        worker_system.add_workers.assert_not_called()
        worker_system.remove_workers.assert_not_called()

    @pytest.mark.unit
    def test_uses_config_service_for_new_count(self, app_with_mocks: tuple[Application, MagicMock, MagicMock]) -> None:
        """The new count comes from ``_config_service.get_worker_count('tagger')``, not the callback value."""
        app, worker_system, config_service = app_with_mocks
        # The callback `value` argument is ignored in favor of re-reading config
        config_service.get_worker_count.return_value = 7
        worker_system.get_worker_count.return_value = 5

        app._on_tagger_worker_count_changed("tagger_worker_count", "ignored_value")

        config_service.get_worker_count.assert_called_once_with("tagger")
        worker_system.add_workers.assert_called_once_with(2)
