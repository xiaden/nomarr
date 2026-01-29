"""Unit tests for nomarr.helpers.dto.config_dto module.

Tests the configuration DTOs.
"""

import pytest

from nomarr.helpers.dto.config_dto import (
    ConfigResult,
    GetInternalInfoResult,
    WebConfigResult,
)


class TestGetInternalInfoResult:
    """Tests for GetInternalInfoResult dataclass."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """GetInternalInfoResult should be creatable with all required fields."""
        result = GetInternalInfoResult(
            namespace="nom",
            version_tag="nom_version",
            min_duration_s=60,
            allow_short=False,
            poll_interval=2,
            library_scan_poll_interval=10,
            worker_enabled=True,
        )
        assert result.namespace == "nom"
        assert result.version_tag == "nom_version"
        assert result.min_duration_s == 60
        assert result.allow_short is False
        assert result.poll_interval == 2
        assert result.library_scan_poll_interval == 10
        assert result.worker_enabled is True

    @pytest.mark.unit
    def test_fields_are_accessible(self) -> None:
        """All fields should be accessible as attributes."""
        result = GetInternalInfoResult(
            namespace="test",
            version_tag="v1",
            min_duration_s=30,
            allow_short=True,
            poll_interval=5,
            library_scan_poll_interval=15,
            worker_enabled=False,
        )
        # All fields should be accessible
        assert hasattr(result, "namespace")
        assert hasattr(result, "version_tag")
        assert hasattr(result, "min_duration_s")
        assert hasattr(result, "allow_short")
        assert hasattr(result, "poll_interval")
        assert hasattr(result, "library_scan_poll_interval")
        assert hasattr(result, "worker_enabled")


class TestConfigResult:
    """Tests for ConfigResult dataclass."""

    @pytest.mark.unit
    def test_can_create_with_empty_config(self) -> None:
        """ConfigResult should be creatable with empty config dict."""
        result = ConfigResult(config={})
        assert result.config == {}

    @pytest.mark.unit
    def test_can_create_with_config_values(self) -> None:
        """ConfigResult should store config dict values."""
        config = {
            "models_dir": "/app/models",
            "db_path": "/app/config/db/nomarr.db",
            "library_root": "/media",
        }
        result = ConfigResult(config=config)
        assert result.config == config
        assert result.config["models_dir"] == "/app/models"

    @pytest.mark.unit
    def test_config_is_mutable(self) -> None:
        """Config dict should be mutable after creation."""
        result = ConfigResult(config={"key": "value"})
        result.config["new_key"] = "new_value"
        assert result.config["new_key"] == "new_value"


class TestWebConfigResult:
    """Tests for WebConfigResult dataclass."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """WebConfigResult should be creatable with all required fields."""
        internal_info = GetInternalInfoResult(
            namespace="nom",
            version_tag="nom_version",
            min_duration_s=60,
            allow_short=False,
            poll_interval=2,
            library_scan_poll_interval=10,
            worker_enabled=True,
        )
        result = WebConfigResult(
            config={"file_write_mode": "full"},
            internal_info=internal_info,
            worker_enabled=True,
        )
        assert result.config == {"file_write_mode": "full"}
        assert result.internal_info == internal_info
        assert result.worker_enabled is True

    @pytest.mark.unit
    def test_worker_enabled_can_differ_from_internal_info(self) -> None:
        """worker_enabled can differ from internal_info.worker_enabled (live vs default)."""
        internal_info = GetInternalInfoResult(
            namespace="nom",
            version_tag="nom_version",
            min_duration_s=60,
            allow_short=False,
            poll_interval=2,
            library_scan_poll_interval=10,
            worker_enabled=True,  # Default
        )
        result = WebConfigResult(
            config={},
            internal_info=internal_info,
            worker_enabled=False,  # Live status differs
        )
        assert result.internal_info.worker_enabled is True
        assert result.worker_enabled is False
