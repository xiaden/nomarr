"""Tests for tool input validation and MCP error propagation.

Covers:
- Structurally invalid inputs return error dicts (not soft "no results")
- Empty/whitespace required parameters → error
- Malformed module paths → error
- Invalid parameter combinations → error
- _extract_tool_error helper correctly extracts errors
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp_code_intel.tools.asr_search import asr_search
from mcp_code_intel.tools.locate_module_symbol import locate_module_symbol
from mcp_code_intel.tools.read_module_api import read_module_api
from mcp_code_intel.tools.read_module_source import read_module_source

# ---------------------------------------------------------------------------
# _extract_tool_error helper
# ---------------------------------------------------------------------------


def _extract_tool_error(result: dict[str, Any]) -> str | None:
    """Mirror of the server helper for testing."""
    if "error" not in result:
        return None

    message = result.get("message")
    if isinstance(message, str) and message:
        return message

    error = result["error"]
    return error if isinstance(error, str) else str(error)


class TestExtractToolError:
    def test_no_error(self) -> None:
        assert _extract_tool_error({"matches": []}) is None

    def test_code_tool_error(self) -> None:
        result = {"error": "module not found"}
        assert _extract_tool_error(result) == "module not found"

    def test_artifact_tool_error(self) -> None:
        result = {"error": "not_found", "message": "ADR-999 does not exist"}
        assert _extract_tool_error(result) == "ADR-999 does not exist"

    def test_artifact_tool_error_without_message(self) -> None:
        result = {"error": "unknown_error"}
        assert _extract_tool_error(result) == "unknown_error"


# ---------------------------------------------------------------------------
# locate_module_symbol — invalid inputs
# ---------------------------------------------------------------------------


class TestLocateModuleSymbolValidation:
    def test_empty_symbol_name(self) -> None:
        result = locate_module_symbol("")
        assert "error" in result
        assert "empty" in result["error"].lower()

    def test_whitespace_symbol_name(self) -> None:
        result = locate_module_symbol("   ")
        assert "error" in result
        assert "empty" in result["error"].lower()


# ---------------------------------------------------------------------------
# read_module_api — invalid inputs
# ---------------------------------------------------------------------------


class TestReadModuleApiValidation:
    def test_empty_module_name(self) -> None:
        result = read_module_api("")
        assert "error" in result
        assert "empty" in result["error"].lower()

    def test_whitespace_module_name(self) -> None:
        result = read_module_api("   ")
        assert "error" in result
        assert "empty" in result["error"].lower()

    def test_module_name_with_forward_slash(self) -> None:
        result = read_module_api("nomarr/helpers/dto")
        assert "error" in result
        assert "path separator" in result["error"].lower()

    def test_module_name_with_backslash(self) -> None:
        result = read_module_api("nomarr\\helpers\\dto")
        assert "error" in result
        assert "path separator" in result["error"].lower()


# ---------------------------------------------------------------------------
# read_module_source — invalid inputs
# ---------------------------------------------------------------------------


class TestReadModuleSourceValidation:
    def test_empty_qualified_name(self) -> None:
        result = read_module_source("")
        assert "error" in result
        assert "empty" in result["error"].lower()

    def test_whitespace_qualified_name(self) -> None:
        result = read_module_source("   ")
        assert "error" in result
        assert "empty" in result["error"].lower()


# ---------------------------------------------------------------------------
# asr_search — invalid parameter combinations
# ---------------------------------------------------------------------------


class TestAsrSearchValidation:
    def test_negative_priority_min(self, tmp_path: Path) -> None:
        result = asr_search(priority_min=-1, workspace_root=tmp_path)
        assert "error" in result
        assert "negative" in result.get("message", "").lower()

    def test_negative_priority_max(self, tmp_path: Path) -> None:
        result = asr_search(priority_max=-5, workspace_root=tmp_path)
        assert "error" in result
        assert "negative" in result.get("message", "").lower()

    def test_priority_min_exceeds_max(self, tmp_path: Path) -> None:
        result = asr_search(priority_min=500, priority_max=100, workspace_root=tmp_path)
        assert "error" in result
        assert "exceed" in result.get("message", "").lower()

    def test_valid_priority_range_no_error(self, tmp_path: Path) -> None:
        # Valid range should not return an error (just empty results)
        result = asr_search(priority_min=0, priority_max=100, workspace_root=tmp_path)
        assert "error" not in result
