"""Tests for edit_file_insert_text tool (refactored - no col support)."""

from pathlib import Path

import pytest
from mcp_code_intel.tools.edit_file_insert_text import edit_file_insert_text


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Create temporary workspace for testing."""
    return tmp_path


def test_insert_bof(temp_workspace: Path) -> None:
    """Test inserting at beginning of file."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("# Existing content\nprint('hello')\n")

    result = edit_file_insert_text(
        [{"path": str(test_file), "content": "# Header\n", "at": "bof"}],
        workspace_root=temp_workspace,
    )

    assert result["status"] == "applied"
    assert test_file.read_text() == "# Header\n# Existing content\nprint('hello')\n"


def test_insert_eof(temp_workspace: Path) -> None:
    """Test inserting at end of file."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("# Existing content\nprint('hello')\n")

    result = edit_file_insert_text(
        [{"path": str(test_file), "content": "# Footer\n", "at": "eof"}],
        workspace_root=temp_workspace,
    )

    assert result["status"] == "applied"
    assert test_file.read_text() == "# Existing content\nprint('hello')\n\n# Footer"


def test_insert_before_line(temp_workspace: Path) -> None:
    """Test inserting before a specific line."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("line 1\nline 2\nline 3\n")

    result = edit_file_insert_text(
        [{"path": str(test_file), "content": "inserted\n", "at": "before_line", "line": 2}],
        workspace_root=temp_workspace,
    )

    assert result["status"] == "applied"
    assert test_file.read_text() == "line 1\ninserted\nline 2\nline 3\n"


def test_insert_after_line(temp_workspace: Path) -> None:
    """Test inserting after a specific line."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("line 1\nline 2\nline 3\n")

    result = edit_file_insert_text(
        [{"path": str(test_file), "content": "inserted\n", "at": "after_line", "line": 2}],
        workspace_root=temp_workspace,
    )

    assert result["status"] == "applied"
    assert test_file.read_text() == "line 1\nline 2\ninserted\nline 3\n"


def test_batch_same_file_coordinate_preservation(temp_workspace: Path) -> None:
    """Test that multiple insertions to same file use original coordinates."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("line 1\nline 2\nline 3\nline 4\n")

    # Insert at lines 2 and 3 (both refer to original file state)
    result = edit_file_insert_text(
        [
            {"path": str(test_file), "content": "after 3\n", "at": "after_line", "line": 3},
            {"path": str(test_file), "content": "after 2\n", "at": "after_line", "line": 2},
        ],
        workspace_root=temp_workspace,
    )

    assert result["status"] == "applied"
    # Should insert bottom-to-top: first after 3, then after 2
    content = test_file.read_text()
    assert content == "line 1\nline 2\nafter 2\nline 3\nafter 3\nline 4\n"


def test_batch_multi_file(temp_workspace: Path) -> None:
    """Test batching insertions across multiple files."""
    file1 = temp_workspace / "file1.py"
    file2 = temp_workspace / "file2.py"
    file1.write_text("content1\n")
    file2.write_text("content2\n")

    result = edit_file_insert_text(
        [
            {"path": str(file1), "content": "# header1\n", "at": "bof"},
            {"path": str(file2), "content": "# header2\n", "at": "bof"},
        ],
        workspace_root=temp_workspace,
    )

    assert result["status"] == "applied"
    assert file1.read_text() == "# header1\ncontent1\n"
    assert file2.read_text() == "# header2\ncontent2\n"


def test_edge_case_line_1(temp_workspace: Path) -> None:
    """Test inserting before/after line 1."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("line 1\nline 2\n")

    # After line 1
    result = edit_file_insert_text(
        [{"path": str(test_file), "content": "inserted\n", "at": "after_line", "line": 1}],
        workspace_root=temp_workspace,
    )
    assert result["status"] == "applied"
    assert test_file.read_text() == "line 1\ninserted\nline 2\n"

    # Before line 1
    test_file.write_text("line 1\nline 2\n")
    result = edit_file_insert_text(
        [{"path": str(test_file), "content": "inserted\n", "at": "before_line", "line": 1}],
        workspace_root=temp_workspace,
    )
    assert result["status"] == "applied"
    assert test_file.read_text() == "inserted\nline 1\nline 2\n"


def test_invalid_line_number(temp_workspace: Path) -> None:
    """Test error handling for invalid line numbers."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("line 1\nline 2\n")

    result = edit_file_insert_text(
        [{"path": str(test_file), "content": "text\n", "at": "after_line", "line": 100}],
        workspace_root=temp_workspace,
    )

    assert result["status"] == "failed"
    assert len(result["failed_ops"]) == 1


def test_missing_line_parameter(temp_workspace: Path) -> None:
    """Test error when line is missing for before_line/after_line."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("line 1\n")

    result = edit_file_insert_text(
        [{"path": str(test_file), "content": "text\n", "at": "after_line"}],
        workspace_root=temp_workspace,
    )

    assert result["status"] == "failed"


def test_file_not_found(temp_workspace: Path) -> None:
    """Test error handling when file doesn't exist."""
    result = edit_file_insert_text(
        [{"path": str(temp_workspace / "nonexistent.py"), "content": "text\n", "at": "bof"}],
        workspace_root=temp_workspace,
    )

    assert result["status"] == "failed"
    assert len(result["failed_ops"]) == 1


def test_context_return(temp_workspace: Path) -> None:
    """Test that context is returned for applied operations."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("line 1\nline 2\nline 3\nline 4\nline 5\n")

    result = edit_file_insert_text(
        [{"path": str(test_file), "content": "inserted\n", "at": "after_line", "line": 3}],
        workspace_root=temp_workspace,
    )

    assert result["status"] == "applied"
    assert len(result["applied_ops"]) == 1
    assert "new_context" in result["applied_ops"][0]
    assert "inserted" in result["applied_ops"][0]["new_context"]


def test_response_format(temp_workspace: Path) -> None:
    """Test response format compliance."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("content\n")

    result = edit_file_insert_text(
        [{"path": str(test_file), "content": "new\n", "at": "bof"}],
        workspace_root=temp_workspace,
    )

    # Check BatchResponse structure
    assert "status" in result
    assert result["status"] in ["applied", "failed"]
    assert "applied_ops" in result or "failed_ops" in result

    if result["status"] == "applied":
        for op in result.get("applied_ops", []):
            assert "filepath" in op
            assert "start_line" in op
            assert "end_line" in op
