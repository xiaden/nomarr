"""Unit tests for NomarrLogFilter.

Tests verify automatic identity/role tag derivation and context injection.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from nomarr.helpers.logging_helper import (
    NomarrLogFilter,
    clear_log_context,
    set_log_context,
)


class TestNomarrLogFilterIdentityRole:
    """Tests for identity and role tag derivation from logger names."""

    @pytest.fixture
    def log_filter(self) -> NomarrLogFilter:
        """Create a fresh filter instance."""
        return NomarrLogFilter()

    def _make_record(self, name: str) -> logging.LogRecord:
        """Create a minimal LogRecord with given logger name."""
        return logging.LogRecord(
            name=name,
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )

    @pytest.mark.unit
    def test_service_suffix(self, log_filter: NomarrLogFilter) -> None:
        """_svc suffix should produce [Identity] [Service] tags."""
        record = self._make_record("nomarr.services.infrastructure.health_monitor_svc")
        log_filter.filter(record)

        assert record.nomarr_identity_tag == "[Health Monitor]"
        assert record.nomarr_role_tag == "[Service]"

    @pytest.mark.unit
    def test_workflow_suffix(self, log_filter: NomarrLogFilter) -> None:
        """_wf suffix should produce [Identity] [Workflow] tags."""
        record = self._make_record("nomarr.workflows.library.scan_library_direct_wf")
        log_filter.filter(record)

        assert record.nomarr_identity_tag == "[Scan Library Direct]"
        assert record.nomarr_role_tag == "[Workflow]"

    @pytest.mark.unit
    def test_component_suffix(self, log_filter: NomarrLogFilter) -> None:
        """_comp suffix should produce [Identity] [Component] tags."""
        record = self._make_record("nomarr.components.platform.gpu_probe_comp")
        log_filter.filter(record)

        assert record.nomarr_identity_tag == "[Gpu Probe]"
        assert record.nomarr_role_tag == "[Component]"

    @pytest.mark.unit
    def test_aql_suffix(self, log_filter: NomarrLogFilter) -> None:
        """_aql suffix should produce [Identity] [AQL] tags."""
        record = self._make_record("nomarr.persistence.database.library_files_aql")
        log_filter.filter(record)

        assert record.nomarr_identity_tag == "[Library Files]"
        assert record.nomarr_role_tag == "[AQL]"

    @pytest.mark.unit
    def test_helper_suffix(self, log_filter: NomarrLogFilter) -> None:
        """_helper suffix should produce [Identity] [Helper] tags."""
        record = self._make_record("nomarr.helpers.time_helper")
        log_filter.filter(record)

        assert record.nomarr_identity_tag == "[Time]"
        assert record.nomarr_role_tag == "[Helper]"

    @pytest.mark.unit
    def test_dto_suffix(self, log_filter: NomarrLogFilter) -> None:
        """_dto suffix should produce [Identity] [DTO] tags."""
        record = self._make_record("nomarr.helpers.dto.info_dto")
        log_filter.filter(record)

        assert record.nomarr_identity_tag == "[Info]"
        assert record.nomarr_role_tag == "[DTO]"

    @pytest.mark.unit
    def test_interface_suffix(self, log_filter: NomarrLogFilter) -> None:
        """_if suffix should produce [Identity] [Interface] tags."""
        record = self._make_record("nomarr.interfaces.api.web.library_if")
        log_filter.filter(record)

        assert record.nomarr_identity_tag == "[Library]"
        assert record.nomarr_role_tag == "[Interface]"

    @pytest.mark.unit
    def test_unknown_suffix_uses_full_name(self, log_filter: NomarrLogFilter) -> None:
        """Unknown suffix should preserve full logger name, empty role tag."""
        record = self._make_record("nomarr.services.domain.library_svc.scan")
        log_filter.filter(record)

        assert record.nomarr_identity_tag == "nomarr.services.domain.library_svc.scan"
        assert record.nomarr_role_tag == ""

    @pytest.mark.unit
    def test_empty_stem_falls_back(self, log_filter: NomarrLogFilter) -> None:
        """Empty stem (e.g., '_svc') should fall back to full name."""
        record = self._make_record("nomarr.weird._svc")
        log_filter.filter(record)

        assert record.nomarr_identity_tag == "nomarr.weird._svc"
        assert record.nomarr_role_tag == ""

    @pytest.mark.unit
    def test_simple_name_no_dots(self, log_filter: NomarrLogFilter) -> None:
        """Logger name without dots should still work."""
        record = self._make_record("my_service_svc")
        log_filter.filter(record)

        assert record.nomarr_identity_tag == "[My Service]"
        assert record.nomarr_role_tag == "[Service]"

    @pytest.mark.unit
    def test_third_party_logger(self, log_filter: NomarrLogFilter) -> None:
        """Third-party logger should show full name."""
        record = self._make_record("uvicorn.access")
        log_filter.filter(record)

        assert record.nomarr_identity_tag == "uvicorn.access"
        assert record.nomarr_role_tag == ""


class TestNomarrLogFilterContext:
    """Tests for dynamic context injection."""

    @pytest.fixture
    def log_filter(self) -> NomarrLogFilter:
        """Create a fresh filter instance."""
        return NomarrLogFilter()

    @pytest.fixture(autouse=True)
    def clear_context(self) -> None:
        """Clear context before each test."""
        clear_log_context()
        yield
        clear_log_context()

    def _make_record(self, name: str = "test_svc") -> logging.LogRecord:
        """Create a minimal LogRecord."""
        return logging.LogRecord(
            name=name,
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )

    @pytest.mark.unit
    def test_no_context_empty_string(self, log_filter: NomarrLogFilter) -> None:
        """No context should produce empty context_str."""
        record = self._make_record()
        log_filter.filter(record)

        assert record.context_str == ""

    @pytest.mark.unit
    def test_context_single_value(self, log_filter: NomarrLogFilter) -> None:
        """Single context value should be formatted."""
        set_log_context(worker_id="worker_0")
        record = self._make_record()
        log_filter.filter(record)

        assert record.context_str == "[worker_id=worker_0] "

    @pytest.mark.unit
    def test_context_multiple_values(self, log_filter: NomarrLogFilter) -> None:
        """Multiple context values should be formatted."""
        set_log_context(worker_id="worker_0", job_id=123)
        record = self._make_record()
        log_filter.filter(record)

        # Order may vary, check both are present
        assert "worker_id=worker_0" in record.context_str
        assert "job_id=123" in record.context_str
        assert record.context_str.startswith("[")
        assert record.context_str.endswith("] ")


class TestNomarrLogFilterSafety:
    """Tests for filter safety (never crashes)."""

    @pytest.fixture
    def log_filter(self) -> NomarrLogFilter:
        """Create a fresh filter instance."""
        return NomarrLogFilter()

    @pytest.mark.unit
    def test_empty_name(self, log_filter: NomarrLogFilter) -> None:
        """Empty logger name should not crash."""
        record = logging.LogRecord(
            name="",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test",
            args=(),
            exc_info=None,
        )
        result = log_filter.filter(record)

        assert result is True
        assert hasattr(record, "nomarr_identity_tag")
        assert hasattr(record, "nomarr_role_tag")
        assert hasattr(record, "context_str")

    @pytest.mark.unit
    def test_none_attributes_dont_crash(self, log_filter: NomarrLogFilter) -> None:
        """Unusual record attributes should not crash filter."""
        record = MagicMock(spec=logging.LogRecord)
        record.name = "test_svc"

        result = log_filter.filter(record)

        assert result is True

    @pytest.mark.unit
    def test_filter_always_returns_true(self, log_filter: NomarrLogFilter) -> None:
        """Filter should always return True (never suppress logs)."""
        record = logging.LogRecord(
            name="anything",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test",
            args=(),
            exc_info=None,
        )

        assert log_filter.filter(record) is True
