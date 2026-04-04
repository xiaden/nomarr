"""Tests for file_helpers — tab warning behavior."""

from pathlib import Path

import pytest

from mcp_code_intel.helpers.file_helpers import read_file_with_metadata


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Create temporary workspace for testing."""
    return tmp_path


# ---------------------------------------------------------------------------
# Tab indentation → tab_warning present
# ---------------------------------------------------------------------------


def test_leading_tabs_returns_tab_warning(temp_workspace: Path) -> None:
    """File with leading tabs returns content and tab_warning."""
    f = temp_workspace / "tabbed.go"
    f.write_bytes(b"package main\n\tfmt.Println()\n")

    result = read_file_with_metadata(f)

    assert "error" not in result
    assert "content" in result
    assert result["content"] == "package main\n\tfmt.Println()\n"
    assert "tab_warning" in result
    assert "tab" in result["tab_warning"].lower()


def test_mixed_spaces_tabs_returns_tab_warning(temp_workspace: Path) -> None:
    """File with mixed spaces and tabs returns content and tab_warning."""
    f = temp_workspace / "mixed.py"
    f.write_bytes(b"def foo():\n    \tpass\n")

    result = read_file_with_metadata(f)

    assert "error" not in result
    assert "content" in result
    assert "tab_warning" in result
    assert "mixed" in result["tab_warning"].lower() or "tab" in result["tab_warning"].lower()


# ---------------------------------------------------------------------------
# No tabs → no tab_warning key
# ---------------------------------------------------------------------------


def test_no_tabs_returns_no_tab_warning(temp_workspace: Path) -> None:
    """File without tabs has no tab_warning key."""
    f = temp_workspace / "clean.py"
    f.write_bytes(b"def foo():\n    pass\n")

    result = read_file_with_metadata(f)

    assert "error" not in result
    assert "content" in result
    assert "tab_warning" not in result


# ---------------------------------------------------------------------------
# tab_warning includes line number
# ---------------------------------------------------------------------------


def test_tab_warning_includes_line_number(temp_workspace: Path) -> None:
    """tab_warning mentions the line number of the first tab."""
    f = temp_workspace / "tabbed.txt"
    # Tab appears on line 3
    f.write_bytes(b"line one\nline two\n\tline three\n")

    result = read_file_with_metadata(f)

    assert "tab_warning" in result
    # Line 3 should be mentioned
    assert "line 3" in result["tab_warning"].lower() or "3" in result["tab_warning"]
