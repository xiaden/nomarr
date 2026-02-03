"""Tests for file_insert_text tool."""

from pathlib import Path

import pytest
from mcp_code_intel.file_insert_text import file_insert_text


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Create temporary workspace for testing."""
    return tmp_path


def test_insert_bof(temp_workspace: Path) -> None:
    """Test inserting at beginning of file."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("# Existing content\nprint('hello')\n")

    result = file_insert_text(
        [{"path": str(test_file), "content": "# Header\n", "at": "bof"}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"
    assert test_file.read_text() == "# Header\n# Existing content\nprint('hello')\n"


def test_insert_eof(temp_workspace: Path) -> None:
    """Test inserting at end of file."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("# Existing content\nprint('hello')\n")

    result = file_insert_text(
        [{"path": str(test_file), "content": "\n# Footer\n", "at": "eof"}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"
    assert test_file.read_text() == "# Existing content\nprint('hello')\n\n# Footer\n"


def test_insert_before_line(temp_workspace: Path) -> None:
    """Test inserting before a specific line."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("line 1\nline 2\nline 3\n")

    result = file_insert_text(
        [{"path": str(test_file), "content": "inserted\n", "at": "before_line", "line": 2}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"
    assert test_file.read_text() == "line 1\ninserted\nline 2\nline 3\n"


def test_insert_after_line(temp_workspace: Path) -> None:
    """Test inserting after a specific line."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("line 1\nline 2\nline 3\n")

    result = file_insert_text(
        [{"path": str(test_file), "content": "inserted\n", "at": "after_line", "line": 2}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"
    assert test_file.read_text() == "line 1\nline 2\ninserted\nline 3\n"


def test_col_positioning_bol(temp_workspace: Path) -> None:
    """Test column positioning at beginning of line."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("line 1\nline 2\n")

    # Both None and 0 mean BOL
    result = file_insert_text(
        [{"path": str(test_file), "content": "PREFIX_", "at": "after_line", "line": 1, "col": 0}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"
    # Should insert at beginning of line 2 (after line 1)
    assert "PREFIX_" in test_file.read_text()


def test_col_positioning_eol(temp_workspace: Path) -> None:
    """Test column positioning at end of line."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("line 1\nline 2\n")

    result = file_insert_text(
        [
            {
                "path": str(test_file),
                "content": " # comment",
                "at": "after_line",
                "line": 1,
                "col": -1,
            }
        ],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"
    content = test_file.read_text()
    assert "line 1 # comment" in content


def test_col_positioning_specific(temp_workspace: Path) -> None:
    """Test column positioning at specific character."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("def func():pass\n")

    # Insert return type hint at position 9 (after 'func()')
    result = file_insert_text(
        [{"path": str(test_file), "content": " -> None", "at": "after_line", "line": 1, "col": 11}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"
    content = test_file.read_text()
    assert "def func() -> None:pass" in content


def test_batch_same_file_coordinate_preservation(temp_workspace: Path) -> None:
    """Test coordinate preservation when multiple inserts target same file."""
    test_file = temp_workspace / "test.py"
    content = "\n".join([f"line {i}" for i in range(1, 11)]) + "\n"
    test_file.write_text(content)

    # Insert at lines 3, 6, 9 - all coordinates refer to ORIGINAL state
    result = file_insert_text(
        [
            {"path": str(test_file), "content": "# Comment A\n", "at": "after_line", "line": 3},
            {"path": str(test_file), "content": "# Comment B\n", "at": "after_line", "line": 6},
            {"path": str(test_file), "content": "# Comment C\n", "at": "after_line", "line": 9},
        ],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"
    final_content = test_file.read_text()

    # Verify insertions happened at correct original positions
    lines = final_content.split("\n")
    assert lines[3] == "# Comment A"  # After original line 3
    assert lines[7] == "# Comment B"  # After original line 6 (now 7 due to insert)
    assert lines[11] == "# Comment C"  # After original line 9 (now 11)


def test_batch_multi_file(temp_workspace: Path) -> None:
    """Test inserting into multiple files in one batch."""
    file1 = temp_workspace / "file1.py"
    file2 = temp_workspace / "file2.py"
    file1.write_text("# File 1\n")
    file2.write_text("# File 2\n")

    result = file_insert_text(
        [
            {"path": str(file1), "content": "import sys\n", "at": "bof"},
            {"path": str(file2), "content": "import os\n", "at": "bof"},
        ],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"
    assert len(result["applied_ops"]) == 2
    assert "import sys" in file1.read_text()
    assert "import os" in file2.read_text()


def test_edge_case_line_1(temp_workspace: Path) -> None:
    """Test inserting before line 1."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("line 1\n")

    result = file_insert_text(
        [{"path": str(test_file), "content": "line 0\n", "at": "before_line", "line": 1}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"
    assert test_file.read_text() == "line 0\nline 1\n"


def test_edge_case_eof_line_number(temp_workspace: Path) -> None:
    """Test inserting at EOF using line number."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("line 1\nline 2\n")

    # Insert after last line should work
    result = file_insert_text(
        [{"path": str(test_file), "content": "line 3\n", "at": "after_line", "line": 2}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"
    assert "line 3" in test_file.read_text()


def test_invalid_line_number(temp_workspace: Path) -> None:
    """Test error on invalid line number."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("line 1\nline 2\n")

    result = file_insert_text(
        [{"path": str(test_file), "content": "text\n", "at": "after_line", "line": 999}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "failed"
    assert len(result["failed_ops"]) == 1


def test_invalid_col_number(temp_workspace: Path) -> None:
    """Test error on invalid column number."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("short\n")

    result = file_insert_text(
        [{"path": str(test_file), "content": "text", "at": "after_line", "line": 1, "col": 999}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "failed"
    assert len(result["failed_ops"]) == 1


def test_missing_line_parameter(temp_workspace: Path) -> None:
    """Test error when line parameter missing for before/after_line modes."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("line 1\n")

    # Should fail validation - before_line requires line parameter
    result = file_insert_text(
        [{"path": str(test_file), "content": "text\n", "at": "before_line"}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "failed"


def test_file_not_found(temp_workspace: Path) -> None:
    """Test error when target file doesn't exist."""
    result = file_insert_text(
        [{"path": str(temp_workspace / "missing.py"), "content": "text\n", "at": "bof"}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "failed"
    assert len(result["failed_ops"]) == 1
    assert "not found" in result["failed_ops"][0]["reason"].lower()


def test_context_return(temp_workspace: Path) -> None:
    """Test that context includes changed region ± 2 lines."""
    test_file = temp_workspace / "test.py"
    content = "\n".join([f"line {i}" for i in range(1, 11)]) + "\n"
    test_file.write_text(content)

    result = file_insert_text(
        [{"path": str(test_file), "content": "# INSERTED\n", "at": "after_line", "line": 5}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"

    # Should have context with ±2 lines around insertion
    op = result["applied_ops"][0]
    assert "new_context" in op
    context_lines = op["new_context"]
    # Should include lines around the insertion point
    assert len(context_lines) >= 3  # At minimum: before, inserted, after


def test_response_format(temp_workspace: Path) -> None:
    """Test response includes all required fields."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("line 1\n")

    result = file_insert_text(
        [{"path": str(test_file), "content": "line 2\n", "at": "eof"}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"
    assert "applied_ops" in result
    assert "failed_ops" in result

    op = result["applied_ops"][0]
    assert "index" in op
    assert "filepath" in op
    assert "start_line" in op
    assert "end_line" in op
    assert "new_context" in op
    assert "bytes_written" in op
