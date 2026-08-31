"""Unit tests for ``nomarr.services.infrastructure.config_svc``."""

from __future__ import annotations

import threading
from typing import cast
from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.helpers.dataclasses.app_dataclasses import ConfigOption
from nomarr.helpers.dto.config_dto import ConfigResult, GetInternalInfoResult, WebConfigResult
from nomarr.helpers.dto.processing_dto import ProcessorConfig
from nomarr.services.infrastructure.config_svc import (
    INTERNAL_ALLOW_SHORT,
    INTERNAL_BATCH_SIZE,
    INTERNAL_MIN_DURATION_S,
    INTERNAL_NAMESPACE,
    INTERNAL_POLL_INTERVAL,
    INTERNAL_VERSION_TAG,
    ConfigService,
)


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
    def test_calls_set_config_option_api(self) -> None:
        """Writes should use ``db.app.set_config_option`` with a scalar value."""
        service = _make_service()

        with patch("nomarr.services.infrastructure.config_svc.Database") as mock_database:
            mock_db_instance = mock_database.return_value

            service._write_to_db("namespace", "myns")

        mock_db_instance.app.set_config_option.assert_called_once_with("namespace", "myns")

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


class TestCoerceValue:
    """Tests for conversion of web-form config values."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("true", True),
            ("YES", True),
            ("1", True),
            (" on ", True),
            ("false", False),
            ("NO", False),
            ("0", False),
            (" off ", False),
        ],
    )
    def test_coerces_common_boolean_strings(self, value: str, expected: bool) -> None:
        """Common boolean spellings should become actual booleans."""
        assert ConfigService._coerce_value("calibrate_heads", value) is expected

    @pytest.mark.unit
    def test_preserves_unknown_boolean_string(self) -> None:
        """Unknown boolean spellings should remain strings."""
        assert ConfigService._coerce_value("calibrate_heads", "maybe") == "maybe"


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
            mock_db_instance.app.list_config_options = MagicMock(return_value=[])
            mock_db_instance.app.set_config_option = MagicMock()
            mock_db_instance.close = MagicMock()

            service._bootstrap_and_load()

        assert mock_db_instance.app.list_config_options.call_count == 2
        mock_db_instance.app.list_config_options.assert_has_calls(
            [call(), call()],
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_seeds_missing_key_to_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing bootstrap keys should be seeded into the DB."""
        service = _make_service()
        monkeypatch.setattr(service, "_build_bootstrap_config", MagicMock(return_value={"library_root": "/test-root"}))

        with patch("nomarr.services.infrastructure.config_svc.Database") as mock_database:
            mock_db_instance = mock_database.return_value
            mock_db_instance.app.list_config_options = MagicMock(side_effect=[[], []])
            mock_db_instance.app.set_config_option = MagicMock()
            mock_db_instance.close = MagicMock()

            service._bootstrap_and_load()

        mock_db_instance.app.set_config_option.assert_called_once_with("library_root", "/test-root")

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
            mock_db_instance.app.list_config_options = MagicMock(
                side_effect=[
                    [],
                    [ConfigOption(key="config_library_root", value="/myns")],
                ]
            )
            mock_db_instance.app.set_config_option = MagicMock()
            mock_db_instance.close = MagicMock()

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
        cb = MagicMock()

        service.subscribe("tagger_worker_count", cb)

        assert "tagger_worker_count" in service._subscriptions
        assert cb in service._subscriptions["tagger_worker_count"]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_non_observable_raises_valueerror(self) -> None:
        """subscribe() raises ValueError for keys not in OBSERVABLE_KEYS."""
        service = _make_service()
        cb = MagicMock()

        with pytest.raises(ValueError, match="not observable"):
            service.subscribe("db_path", cb)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_callback_registered(self) -> None:
        """subscribe() registers callback that is fired on set()."""
        service = _make_service()
        cb = MagicMock()

        service.subscribe("tagger_worker_count", cb)
        assert cb in service._subscriptions["tagger_worker_count"]


class TestSetCallbacks:
    """Tests for ``ConfigService.set()`` callback firing."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_observable_key_fires_callbacks(self) -> None:
        """set() fires registered callbacks for observable keys."""
        service = _make_service()
        cb = MagicMock()

        service.subscribe("tagger_worker_count", cb)

        with patch.object(service, "_write_to_db") as mock_write:
            service.set("tagger_worker_count", 3)

        mock_write.assert_called_once_with("tagger_worker_count", "3")
        cb.assert_called_once_with("tagger_worker_count", 3)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_non_observable_key_no_callback(self) -> None:
        """set() does NOT fire callbacks for non-observable keys."""
        service = _make_service()
        cb = MagicMock()

        # calibrate_heads is in ALL_CONFIG_KEYS but NOT in OBSERVABLE_KEYS
        service._subscriptions["calibrate_heads"] = [cb]

        with patch.object(service, "_write_to_db") as mock_write:
            service.set("calibrate_heads", True)

        mock_write.assert_called_once()
        cb.assert_not_called()


class TestGetConfig:
    """Tests for ``ConfigService.get_config()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_config_result_with_cache_copy(self) -> None:
        """get_config() returns a ConfigResult wrapping a shallow copy of the cache."""
        service = _make_service()
        service._cache = {"key1": "val1"}

        result = service.get_config()

        assert isinstance(result, ConfigResult)
        assert result.config == {"key1": "val1"}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_config_when_cache_empty(self) -> None:
        """get_config() returns an empty config dict when cache is empty."""
        service = _make_service()

        result = service.get_config()

        assert isinstance(result, ConfigResult)
        assert result.config == {}


class TestGet:
    """Tests for ``ConfigService.get(key, default)``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_value_for_existing_key(self) -> None:
        """get() returns the cached value for an existing key."""
        service = _make_service()
        service._cache = {"a": 1, "b": 2}

        assert service.get("a") == 1

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_default_for_missing_key(self) -> None:
        """get() returns the default value for a missing key."""
        service = _make_service()
        service._cache = {"a": 1}

        assert service.get("b", "fallback") == "fallback"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_default_when_not_specified(self) -> None:
        """get() returns None when key is missing and no default is given."""
        service = _make_service()
        service._cache = {"a": 1}

        assert service.get("b") is None


class TestSet:
    """Tests for ``ConfigService.set(key, value)`` happy path."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_raises_valueerror_for_invalid_key(self) -> None:
        """set() raises ValueError for keys not in ALL_CONFIG_KEYS."""
        service = _make_service()

        with pytest.raises(ValueError, match="not an allowed config key"):
            service.set("nonexistent_key", 1)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_updates_cache_for_valid_key(self) -> None:
        """set() updates the in-memory cache for valid keys."""
        service = _make_service()

        with patch.object(service, "_write_to_db"):
            service.set("db_path", "/new/path")

        assert service._cache["db_path"] == "/new/path"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_calls_write_to_db_with_stringified_value(self) -> None:
        """set() stringifies the value before persisting to DB."""
        service = _make_service()

        with patch.object(service, "_write_to_db") as mock_write:
            service.set("tagger_worker_count", 3)

        mock_write.assert_called_once_with("tagger_worker_count", "3")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_calls_write_to_db_with_empty_string_for_none(self) -> None:
        """set() persists an empty string when value is None."""
        service = _make_service()

        with patch.object(service, "_write_to_db") as mock_write:
            service.set("db_path", None)

        mock_write.assert_called_once_with("db_path", "")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_coerces_web_form_values_before_caching(self) -> None:
        service = _make_service()
        with patch.object(service, "_write_to_db"):
            service.set("calibrate_heads", "false")
            service.set("vector_group_size", "25")
            service.set("pp_half_life_days", "12.5")

        assert service.get("calibrate_heads") is False
        assert service.get("vector_group_size") == 25
        assert service.get("pp_half_life_days") == 12.5


class TestGetInternalInfo:
    """Tests for ``ConfigService.get_internal_info()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_get_internal_info_result(self) -> None:
        """get_internal_info() returns a GetInternalInfoResult with expected constants."""
        service = _make_service()

        result = service.get_internal_info()

        assert isinstance(result, GetInternalInfoResult)
        assert result.namespace == INTERNAL_NAMESPACE
        assert result.namespace == "nom"
        assert result.version_tag == INTERNAL_VERSION_TAG
        assert result.version_tag == "nom_version"
        assert result.min_duration_s == INTERNAL_MIN_DURATION_S
        assert result.min_duration_s == 60
        assert result.allow_short == INTERNAL_ALLOW_SHORT
        assert result.allow_short is False
        assert result.poll_interval == INTERNAL_POLL_INTERVAL
        assert result.poll_interval == 2
        assert result.library_scan_poll_interval == 10
        assert result.worker_enabled is True


class TestGetWorkerCount:
    """Tests for ``ConfigService.get_worker_count()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_configured_count(self) -> None:
        """get_worker_count() returns the configured value when present."""
        service = _make_service()
        service._cache = {"tagger_worker_count": 4}

        assert service.get_worker_count("tagger") == 4

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_clamps_to_max_8(self) -> None:
        """get_worker_count() clamps to 8 when value exceeds maximum."""
        service = _make_service()
        service._cache = {"tagger_worker_count": 20}

        assert service.get_worker_count("tagger") == 8

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_clamps_to_min_1(self) -> None:
        """get_worker_count() clamps to 1 when value is below minimum."""
        service = _make_service()
        service._cache = {"tagger_worker_count": 0}

        assert service.get_worker_count("tagger") == 1

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_defaults_to_1_when_not_configured(self) -> None:
        """get_worker_count() defaults to 1 when key is missing from cache."""
        service = _make_service()

        assert service.get_worker_count("tagger") == 1

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_handles_empty_string_as_default(self) -> None:
        """get_worker_count() defaults to 1 when value is an empty string."""
        service = _make_service()
        service._cache = {"tagger_worker_count": ""}

        assert service.get_worker_count("tagger") == 1


class TestMakeProcessorConfig:
    """Tests for ``ConfigService.make_processor_config()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_processor_config_with_models_dir(self) -> None:
        """make_processor_config() builds a ProcessorConfig with the correct models_dir."""
        service = _make_service()
        service._cache = {"models_dir": "/test/models"}

        with patch(
            "nomarr.services.infrastructure.config_svc.compute_model_suite_hash",
            return_value="abc123def456",
        ):
            result = service.make_processor_config()

        assert isinstance(result, ProcessorConfig)
        assert result.models_dir == "/test/models"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_includes_internal_constants(self) -> None:
        """make_processor_config() includes internal constants from module-level values."""
        service = _make_service()
        service._cache = {"models_dir": "/test/models"}

        with patch(
            "nomarr.services.infrastructure.config_svc.compute_model_suite_hash",
            return_value="abc123def456",
        ):
            result = service.make_processor_config()

        assert result.min_duration_s == INTERNAL_MIN_DURATION_S
        assert result.min_duration_s == 60
        assert result.batch_size == INTERNAL_BATCH_SIZE
        assert result.batch_size == 11
        assert result.namespace == INTERNAL_NAMESPACE
        assert result.namespace == "nom"
        assert result.version_tag_key == INTERNAL_VERSION_TAG
        assert result.version_tag_key == "nom_version"
        assert result.allow_short == INTERNAL_ALLOW_SHORT
        assert result.allow_short is False
        assert result.tagger_version == "abc123def456"


class TestGetConfigForWeb:
    """Tests for ``ConfigService.get_config_for_web()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_only_web_editable_keys(self) -> None:
        """get_config_for_web() filters config to WEB_EDITABLE_KEYS only."""
        service = _make_service()
        service._cache = {
            "calibrate_heads": True,
            "tagger_worker_count": 2,
            "models_dir": "/test/models",  # static key — NOT web-editable
        }

        result = service.get_config_for_web()

        assert isinstance(result, WebConfigResult)
        assert "calibrate_heads" in result.config
        assert "tagger_worker_count" in result.config
        assert "models_dir" not in result.config

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_redacts_sensitive_keys_to_none(self) -> None:
        """get_config_for_web() redacts sensitive keys to None."""
        service = _make_service()
        service._cache = {
            "navidrome_api_password": "secret123",
            "spotify_client_secret": "topsecret",
            "calibrate_heads": False,
        }

        result = service.get_config_for_web()

        assert result.config["navidrome_api_password"] is None
        assert result.config["spotify_client_secret"] is None
        assert result.config["calibrate_heads"] is False

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_includes_internal_info(self) -> None:
        """get_config_for_web() includes internal_info in the result."""
        service = _make_service()

        result = service.get_config_for_web()

        assert isinstance(result.internal_info, GetInternalInfoResult)
        assert result.internal_info.namespace == "nom"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_worker_enabled_from_worker_service(self) -> None:
        """get_config_for_web() uses worker_service status when provided."""
        service = _make_service()
        mock_worker_service = MagicMock()
        mock_worker_service.is_worker_system_enabled.return_value = False

        result = service.get_config_for_web(worker_service=mock_worker_service)

        assert result.worker_enabled is False
        mock_worker_service.is_worker_system_enabled.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_worker_enabled_defaults_to_internal_constant(self) -> None:
        """get_config_for_web() falls back to internal constant when no worker_service."""
        service = _make_service()

        result = service.get_config_for_web()

        assert result.worker_enabled is True
