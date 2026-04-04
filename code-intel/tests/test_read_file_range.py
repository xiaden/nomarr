"""Tests for read_file_range MCP tool.

Covers:
- Read range with 2-line context padding
- Boundary: start=1, end=last line
- Range exceeds file (clamped)
- File not found
- Single line range (start == end)
- Reversed range
"""

import textwrap
from pathlib import Path

from mcp_code_intel.tools.read_file_range import read_file_range

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


def test_read_middle_range(tmp_path: Path) -> None:
    _write_file(tmp_path, "test.txt", SAMPLE_TEXT)
    result = read_file_range(
        file_path="test.txt", start_line=4, end_line=6, workspace_root=tmp_path
    )
    assert "error" not in result
    content = result["requested"]["content"]
    # Context padding: 4-2=2, 6+2=8
    assert result["requested"]["start"] == 2
    assert result["requested"]["end"] == 8
    assert "Line 4" in content
    assert "Line 5" in content
    assert "Line 6" in content


def test_read_from_start(tmp_path: Path) -> None:
    """start_line=1 clamps context to 1."""
    _write_file(tmp_path, "test.txt", SAMPLE_TEXT)
    result = read_file_range(
        file_path="test.txt", start_line=1, end_line=3, workspace_root=tmp_path
    )
    assert "error" not in result
    assert result["requested"]["start"] == 1
    assert "Line 1" in result["requested"]["content"]


def test_read_to_end(tmp_path: Path) -> None:
    """end_line at last line clamps context to total."""
    _write_file(tmp_path, "test.txt", SAMPLE_TEXT)
    result = read_file_range(
        file_path="test.txt", start_line=8, end_line=10, workspace_root=tmp_path
    )
    assert "error" not in result
    assert "Line 10" in result["requested"]["content"]


def test_single_line_range(tmp_path: Path) -> None:
    """start == end reads one line with context."""
    _write_file(tmp_path, "test.txt", SAMPLE_TEXT)
    result = read_file_range(
        file_path="test.txt", start_line=5, end_line=5, workspace_root=tmp_path
    )
    assert "error" not in result
    assert "Line 5" in result["requested"]["content"]
    # Should have context: 3-7
    assert result["requested"]["start"] == 3
    assert result["requested"]["end"] == 7


def test_reversed_range(tmp_path: Path) -> None:
    """When start > end, the tool auto-fixes and warns."""
    _write_file(tmp_path, "test.txt", SAMPLE_TEXT)
    result = read_file_range(
        file_path="test.txt", start_line=6, end_line=4, workspace_root=tmp_path
    )
    assert "error" not in result
    # Should still return content covering lines 4-6
    content = result["requested"]["content"]
    assert "Line 4" in content
    assert "Line 6" in content


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_start_line_zero(tmp_path: Path) -> None:
    _write_file(tmp_path, "test.txt", SAMPLE_TEXT)
    result = read_file_range(
        file_path="test.txt", start_line=0, end_line=5, workspace_root=tmp_path
    )
    assert "error" in result


def test_start_line_exceeds_file(tmp_path: Path) -> None:
    _write_file(tmp_path, "test.txt", SAMPLE_TEXT)
    result = read_file_range(
        file_path="test.txt", start_line=999, end_line=1000, workspace_root=tmp_path
    )
    assert "error" in result


def test_file_not_found(tmp_path: Path) -> None:
    result = read_file_range(
        file_path="ghost.txt", start_line=1, end_line=5, workspace_root=tmp_path
    )
    assert "error" in result


def test_path_outside_workspace(tmp_path: Path) -> None:
    result = read_file_range(
        file_path="../../etc/passwd", start_line=1, end_line=5, workspace_root=tmp_path
    )
    assert "error" in result


# ---------------------------------------------------------------------------
# End line exceeds file (clamped)
# ---------------------------------------------------------------------------


def test_end_line_exceeds_file_is_clamped(tmp_path: Path) -> None:
    """end_line beyond file end should be clamped, not error."""
    _write_file(tmp_path, "test.txt", SAMPLE_TEXT)
    result = read_file_range(
        file_path="test.txt", start_line=8, end_line=999, workspace_root=tmp_path
    )
    assert "error" not in result
    assert "Line 10" in result["requested"]["content"]


# ---------------------------------------------------------------------------
# include_imports
# ---------------------------------------------------------------------------


def test_include_imports_non_overlapping(tmp_path: Path) -> None:
    _write_file(tmp_path, "code.py", SAMPLE_PYTHON)
    result = read_file_range(
        file_path="code.py", start_line=9, end_line=10, workspace_root=tmp_path,
        include_imports=True,
    )
    assert "error" not in result
    assert "imports" in result
    assert "import os" in result["imports"]["content"]


def test_include_imports_overlapping(tmp_path: Path) -> None:
    _write_file(tmp_path, "code.py", SAMPLE_PYTHON)
    result = read_file_range(
        file_path="code.py", start_line=1, end_line=3, workspace_root=tmp_path,
        include_imports=True,
    )
    assert "error" not in result
    # Overlapping — single contiguous block, no separate imports
    assert "import os" in result["requested"]["content"]


def test_include_imports_non_python(tmp_path: Path) -> None:
    _write_file(tmp_path, "data.txt", SAMPLE_TEXT)
    result = read_file_range(
        file_path="data.txt", start_line=3, end_line=5, workspace_root=tmp_path,
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
    (sub / "file.txt").write_text("hello\nworld\n", encoding="utf-8")
    result = read_file_range(
        file_path="sub/file.txt", start_line=1, end_line=2, workspace_root=tmp_path
    )
    assert "error" not in result
    assert "hello" in result["requested"]["content"]


def test_absolute_path(tmp_path: Path) -> None:
    f = _write_file(tmp_path, "abs.txt", "one\ntwo\nthree\n")
    result = read_file_range(
        file_path=str(f), start_line=1, end_line=2, workspace_root=tmp_path
    )
    assert "error" not in result
    assert "one" in result["requested"]["content"]
