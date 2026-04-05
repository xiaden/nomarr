"""Tests for read_file_line MCP tool.

Covers:
- Read specific line with 2-line context
- Boundary: first line, last line
- Line out of range
- File not found
- include_imports for Python files
"""

import textwrap
from pathlib import Path

from mcp_code_intel.tools.read_file_line import read_file_line

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_TEXT = textwrap.dedent("""\
    Line 1
    Line 2
    Line 3
    Line 4
    Line 5
    Line 6
    Line 7
    Line 8
    Line 9
    Line 10
""")

SAMPLE_PYTHON = textwrap.dedent("""\
    import os
    from pathlib import Path

    X = 1

    def hello():
        return "world"

    def goodbye():
        return "farewell"
""")


def _write_file(tmp_path: Path, name: str, content: str) -> Path:
    f = tmp_path / name
    f.write_text(content, encoding="utf-8")
    return f


# ---------------------------------------------------------------------------
# Basic reads
# ---------------------------------------------------------------------------


def test_read_middle_line(tmp_path: Path) -> None:
    _write_file(tmp_path, "test.txt", SAMPLE_TEXT)
    result = read_file_line(file_path="test.txt", line_number=5, workspace_root=tmp_path)
    assert "error" not in result
    assert result["requested"]["start"] == 3
    assert result["requested"]["end"] == 7
    assert "Line 5" in result["requested"]["content"]


def test_read_first_line(tmp_path: Path) -> None:
    """At file start, context is clamped — start should be 1."""
    _write_file(tmp_path, "test.txt", SAMPLE_TEXT)
    result = read_file_line(file_path="test.txt", line_number=1, workspace_root=tmp_path)
    assert "error" not in result
    assert result["requested"]["start"] == 1
    assert "Line 1" in result["requested"]["content"]


def test_read_last_line(tmp_path: Path) -> None:
    """At file end, context is clamped — end should be total lines."""
    _write_file(tmp_path, "test.txt", SAMPLE_TEXT)
    result = read_file_line(file_path="test.txt", line_number=10, workspace_root=tmp_path)
    assert "error" not in result
    assert "Line 10" in result["requested"]["content"]


def test_read_second_line(tmp_path: Path) -> None:
    """Line 2 has only 1 line before it."""
    _write_file(tmp_path, "test.txt", SAMPLE_TEXT)
    result = read_file_line(file_path="test.txt", line_number=2, workspace_root=tmp_path)
    assert "error" not in result
    assert result["requested"]["start"] == 1
    assert "Line 2" in result["requested"]["content"]


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_line_out_of_range_high(tmp_path: Path) -> None:
    _write_file(tmp_path, "test.txt", SAMPLE_TEXT)
    result = read_file_line(file_path="test.txt", line_number=999, workspace_root=tmp_path)
    assert "error" in result


def test_line_out_of_range_zero(tmp_path: Path) -> None:
    _write_file(tmp_path, "test.txt", SAMPLE_TEXT)
    result = read_file_line(file_path="test.txt", line_number=0, workspace_root=tmp_path)
    assert "error" in result


def test_line_out_of_range_negative(tmp_path: Path) -> None:
    _write_file(tmp_path, "test.txt", SAMPLE_TEXT)
    result = read_file_line(file_path="test.txt", line_number=-1, workspace_root=tmp_path)
    assert "error" in result


def test_file_not_found(tmp_path: Path) -> None:
    result = read_file_line(file_path="nonexistent.txt", line_number=1, workspace_root=tmp_path)
    assert "error" in result
    assert "not found" in result["error"].lower() or "not found" in result["error"]


def test_path_outside_workspace(tmp_path: Path) -> None:
    result = read_file_line(file_path="../../etc/passwd", line_number=1, workspace_root=tmp_path)
    assert "error" in result


# ---------------------------------------------------------------------------
# Python file warning
# ---------------------------------------------------------------------------


def test_python_file_has_warning(tmp_path: Path) -> None:
    _write_file(tmp_path, "code.py", SAMPLE_PYTHON)
    result = read_file_line(file_path="code.py", line_number=6, workspace_root=tmp_path)
    assert "warning" in result


def test_non_python_file_no_warning(tmp_path: Path) -> None:
    _write_file(tmp_path, "data.txt", SAMPLE_TEXT)
    result = read_file_line(file_path="data.txt", line_number=5, workspace_root=tmp_path)
    assert "warning" not in result


# ---------------------------------------------------------------------------
# include_imports
# ---------------------------------------------------------------------------


def test_include_imports_non_overlapping(tmp_path: Path) -> None:
    """When target line is far from imports, both blocks are returned."""
    _write_file(tmp_path, "code.py", SAMPLE_PYTHON)
    result = read_file_line(
        file_path="code.py",
        line_number=9,
        workspace_root=tmp_path,
        include_imports=True,
    )
    assert "error" not in result
    assert "imports" in result
    assert result["imports"]["start"] == 1
    assert "import os" in result["imports"]["content"]


def test_include_imports_overlapping(tmp_path: Path) -> None:
    """When target line is near imports, they merge into a single block."""
    _write_file(tmp_path, "code.py", SAMPLE_PYTHON)
    result = read_file_line(
        file_path="code.py",
        line_number=3,
        workspace_root=tmp_path,
        include_imports=True,
    )
    assert "error" not in result
    # Overlapping — imports block merged, no separate imports key
    assert "imports" not in result
    assert result["requested"]["start"] == 1


def test_include_imports_non_python_ignored(tmp_path: Path) -> None:
    """include_imports on non-Python file has no effect."""
    _write_file(tmp_path, "data.txt", SAMPLE_TEXT)
    result = read_file_line(
        file_path="data.txt",
        line_number=5,
        workspace_root=tmp_path,
        include_imports=True,
    )
    assert "error" not in result
    assert "imports" not in result


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def test_relative_path(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "file.txt").write_text("hello\n", encoding="utf-8")
    result = read_file_line(file_path="sub/file.txt", line_number=1, workspace_root=tmp_path)
    assert "error" not in result
    assert "hello" in result["requested"]["content"]


def test_absolute_path(tmp_path: Path) -> None:
    f = _write_file(tmp_path, "abs.txt", "absolute\n")
    result = read_file_line(file_path=str(f), line_number=1, workspace_root=tmp_path)
    assert "error" not in result
    assert "absolute" in result["requested"]["content"]
