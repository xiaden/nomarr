"""Unit tests for ``nomarr.services.infrastructure.config_svc``."""

from __future__ import annotations

import threading
from typing import cast
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from nomarr.services.infrastructure.config_svc import ConfigService


def _make_service() -> ConfigService:
    """Build a ``ConfigService`` instance without running ``__init__``."""
    service = ConfigService.__new__(ConfigService)
    service._cache = {}
    service._subscriptions = {}
    service._background_tasks: set = set()
    service._lock = threading.Lock()
    service._logger = MagicMock()  # type: ignore[assignment]
    return service


class TestWriteToDb:
    """Tests for ``ConfigService._write_to_db``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_calls_update_config_option_api(self) -> None:
        """Writes should use ``db.app.update_config_option``."""
        service = _make_service()

        with patch("nomarr.services.infrastructure.config_svc.Database") as mock_database:
            mock_db_instance = mock_database.return_value

            service._write_to_db("namespace", "myns")

        mock_db_instance.app.update_config_option.assert_called_once_with(
            "config_namespace",
            {"value": "myns"},
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_closes_connection_after_write(self) -> None:
        """The throwaway database connection should always be closed."""
        service = _make_service()

        with patch("nomarr.services.infrastructure.config_svc.Database") as mock_database:
            mock_db_instance = mock_database.return_value

            service._write_to_db("namespace", "myns")

        assert mock_db_instance.close.call_count == 1

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_swallows_exception_on_db_failure(self) -> None:
        """Database construction failures should be logged, not raised."""
        service = _make_service()

        with patch(
            "nomarr.services.infrastructure.config_svc.Database",
            side_effect=RuntimeError("conn failed"),
        ):
            service._write_to_db("namespace", "myns")

        cast("MagicMock", service._logger).exception.assert_called_once_with(
            "Failed to persist config '%s' to DB",
            "namespace",
        )


class TestBootstrapAndLoad:
    """Tests for ``ConfigService._bootstrap_and_load``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_reads_existing_config_via_list_config_options(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bootstrap should list config docs twice: existing keys, then loaded values."""
        service = _make_service()
        monkeypatch.setattr(service, "_build_bootstrap_config", MagicMock(return_value={"library_root": "/test-root"}))

        with patch("nomarr.services.infrastructure.config_svc.Database") as mock_database:
            mock_db_instance = mock_database.return_value
            mock_db_instance.app.list_config_options.return_value = []

            service._bootstrap_and_load()

        assert mock_db_instance.app.list_config_options.call_count == 2
        mock_db_instance.app.list_config_options.assert_has_calls(
            [call(prefix="config_"), call(prefix="config_")],
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_seeds_missing_key_to_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing bootstrap keys should be seeded into the DB."""
        service = _make_service()
        monkeypatch.setattr(service, "_build_bootstrap_config", MagicMock(return_value={"library_root": "/test-root"}))

        with patch("nomarr.services.infrastructure.config_svc.Database") as mock_database:
            mock_db_instance = mock_database.return_value
            mock_db_instance.app.list_config_options.side_effect = [[], []]

            service._bootstrap_and_load()

        mock_db_instance.app.update_config_option.assert_called_once_with(
            "config_library_root",
            {"value": "/test-root"},
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_populates_cache_from_db_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Loaded DB values should populate the in-memory cache."""
        service = _make_service()
        monkeypatch.setattr(
            service, "_build_bootstrap_config", MagicMock(return_value={"library_root": "/bootstrap-root"})
        )

        with patch("nomarr.services.infrastructure.config_svc.Database") as mock_database:
            mock_db_instance = mock_database.return_value
            mock_db_instance.app.list_config_options.side_effect = [
                [],
                [{"key": "config_library_root", "value": "/myns"}],
            ]

            service._bootstrap_and_load()

        assert service._cache.get("library_root") == "/myns"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_falls_back_to_file_config_when_db_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bootstrap should fall back to file/env config when the DB is unavailable."""
        service = _make_service()
        monkeypatch.setattr(
            service, "_build_bootstrap_config", MagicMock(return_value={"library_root": "/fallback-root"})
        )

        with patch(
            "nomarr.services.infrastructure.config_svc.Database",
            side_effect=RuntimeError("no db"),
        ):
            service._bootstrap_and_load()

        assert service._cache
        assert service._cache["library_root"] == "/fallback-root"


class TestSubscribe:
    """Tests for ``ConfigService.subscribe()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_observable_key_accepted(self) -> None:
        """subscribe() does not raise for keys in OBSERVABLE_KEYS."""
        service = _make_service()
        cb = AsyncMock()

        service.subscribe("tagger_worker_count", cb)

        assert "tagger_worker_count" in service._subscriptions
        assert cb in service._subscriptions["tagger_worker_count"]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_non_observable_raises_valueerror(self) -> None:
        """subscribe() raises ValueError for keys not in OBSERVABLE_KEYS."""
        service = _make_service()
        cb = AsyncMock()

        with pytest.raises(ValueError, match="not observable"):
            service.subscribe("db_path", cb)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_callback_registered(self) -> None:
        """subscribe() registers callback that is fired on set()."""
        service = _make_service()
        cb = AsyncMock()

        service.subscribe("tagger_worker_count", cb)
        assert cb in service._subscriptions["tagger_worker_count"]


class TestSetCallbacks:
    """Tests for ``ConfigService.set()`` callback firing."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_observable_key_fires_callbacks(self) -> None:
        """set() fires registered callbacks for observable keys."""
        service = _make_service()
        cb = AsyncMock()

        service.subscribe("tagger_worker_count", cb)

        with (
            patch("nomarr.services.infrastructure.config_svc.asyncio") as mock_asyncio,
            patch.object(service, "_write_to_db"),
        ):
            mock_task = MagicMock()
            mock_asyncio.create_task.return_value = mock_task

            service.set("tagger_worker_count", 3)

        mock_asyncio.create_task.assert_called_once()
        # Verify the callback was wrapped in create_task
        coro = mock_asyncio.create_task.call_args[0][0]
        assert coro is not None

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_non_observable_key_no_callback(self) -> None:
        """set() does NOT fire callbacks for non-observable keys."""
        service = _make_service()
        cb = AsyncMock()

        # calibrate_heads is in ALL_CONFIG_KEYS but NOT in OBSERVABLE_KEYS
        service._subscriptions["calibrate_heads"] = [cb]

        with (
            patch("nomarr.services.infrastructure.config_svc.asyncio") as mock_asyncio,
            patch.object(service, "_write_to_db"),
        ):
            service.set("calibrate_heads", True)

        mock_asyncio.create_task.assert_not_called()
