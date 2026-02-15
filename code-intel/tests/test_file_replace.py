"""Tests for edit_file_replace_content tool."""

from pathlib import Path

import pytest

from mcp_code_intel.tools.edit_file_replace_content import edit_file_replace_content


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Create temporary workspace for testing."""
    return tmp_path


def test_replace_single_file(temp_workspace: Path) -> None:
    """Test replacing a single file."""
    # Create original file
    test_file = temp_workspace / "test.py"
    test_file.write_text("# Original\nold_content = 1\n")

    result = edit_file_replace_content(
        [{"path": str(test_file), "content": "# Replaced\nnew_content = 2\n"}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"
    assert len(result["applied_ops"]) == 1
    assert len(result["failed_ops"]) == 0

    # Verify file content replaced
    assert test_file.read_text() == "# Replaced\nnew_content = 2\n"

    # Verify context returned
    op = result["applied_ops"][0]
    assert "new_context" in op
    assert "bytes_written" in op
    assert "lines_total" in op
    assert op["lines_total"] == 2


def test_replace_batch_files(temp_workspace: Path) -> None:
    """Test replacing multiple files in one batch."""
    # Create original files
    file1 = temp_workspace / "file1.py"
    file2 = temp_workspace / "file2.py"
    file3 = temp_workspace / "file3.py"
    file1.write_text("# File 1 original\n")
    file2.write_text("# File 2 original\n")
    file3.write_text("# File 3 original\n")

    result = edit_file_replace_content(
        [
            {"path": str(file1), "content": "# File 1 replaced\n"},
            {"path": str(file2), "content": "# File 2 replaced\n"},
            {"path": str(file3), "content": "# File 3 replaced\n"},
        ],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"
    assert len(result["applied_ops"]) == 3
    assert len(result["failed_ops"]) == 0

    # Verify all files replaced
    assert file1.read_text() == "# File 1 replaced\n"
    assert file2.read_text() == "# File 2 replaced\n"
    assert file3.read_text() == "# File 3 replaced\n"


def test_fail_on_missing_file(temp_workspace: Path) -> None:
    """Test failure when target file doesn't exist."""
    result = edit_file_replace_content(
        [{"path": str(temp_workspace / "missing.py"), "content": "# New\n"}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "failed"
    assert len(result["applied_ops"]) == 0
    assert len(result["failed_ops"]) == 1
    assert "not found" in result["failed_ops"][0]["reason"].lower()


def test_rollback_on_partial_failure(temp_workspace: Path) -> None:
    """Test complete rollback when one file in batch is missing."""
    # Create some files
    file1 = temp_workspace / "file1.py"
    file2 = temp_workspace / "file2.py"
    file1.write_text("# File 1 original\n")
    file2.write_text("# File 2 original\n")

    # Try to replace batch with one missing file
    result = edit_file_replace_content(
        [
            {"path": str(file1), "content": "# File 1 replaced\n"},
            {"path": str(temp_workspace / "missing.py"), "content": "# Should fail\n"},
            {"path": str(file2), "content": "# File 2 replaced\n"},
        ],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "failed"
    assert len(result["applied_ops"]) == 0  # No partial success

    # Verify original files unchanged (rollback)
    assert file1.read_text() == "# File 1 original\n"
    assert file2.read_text() == "# File 2 original\n"


def test_replace_with_empty_content(temp_workspace: Path) -> None:
    """Test replacing file with empty content."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("# Original content\nsome_code = 1\n")

    result = edit_file_replace_content(
        [{"path": str(test_file), "content": ""}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"
    assert len(result["applied_ops"]) == 1

    # Verify file is now empty
    assert test_file.read_text() == ""

    # Verify response indicates 0 lines
    op = result["applied_ops"][0]
    assert op["lines_total"] == 0


def test_large_file_context_capping(temp_workspace: Path) -> None:
    """Test context is capped (first 2 + last 2 lines) for large files."""
    test_file = temp_workspace / "large.py"
    test_file.write_text("# Original\n")

    # Create content with 100 lines
    lines = [f"# Line {i}\n" for i in range(1, 101)]
    content = "".join(lines)

    result = edit_file_replace_content(
        [{"path": str(test_file), "content": content}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"

    # Verify file replaced with all content
    assert test_file.read_text() == content

    # Verify context is capped (first 2 + last 2, not all 100)
    op = result["applied_ops"][0]
    assert "new_context" in op
    assert len(op["new_context"]) <= 6  # First 2 + separator + last 2 + margins
    assert op["lines_total"] == 100


def test_very_large_file_over_1mb(temp_workspace: Path) -> None:
    """Test handling files larger than 1MB."""
    test_file = temp_workspace / "huge.py"
    test_file.write_text("# Original\n")

    # Create content over 1MB (1048576 bytes)
    lines = [f"# This is line {i} with some padding text to make it longer\n" for i in range(11000)]
    content = "".join(lines)
    assert len(content.encode()) > 1_048_576  # Verify >1MB

    result = edit_file_replace_content(
        [{"path": str(test_file), "content": content}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"

    # Verify file replaced
    assert test_file.stat().st_size > 1_048_576

    # Verify context is still capped
    op = result["applied_ops"][0]
    assert len(op["new_context"]) <= 6


def test_binary_file_handling(temp_workspace: Path) -> None:
    """Test replacing binary files (should work but context may be limited)."""
    test_file = temp_workspace / "binary.dat"
    # Create original binary content
    test_file.write_bytes(b"\x00\x01\x02\x03\x04")

    # Replace with new binary content
    new_content = bytes(range(256))  # All byte values 0-255

    result = edit_file_replace_content(
        [{"path": str(test_file), "content": new_content.decode("latin-1")}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"

    # Verify file replaced
    assert test_file.read_bytes() == new_content


def test_duplicate_paths_in_batch(temp_workspace: Path) -> None:
    """Test failure when batch contains duplicate paths."""
    file1 = temp_workspace / "dup.py"
    file2 = temp_workspace / "other.py"
    file1.write_text("# Original\n")
    file2.write_text("# Original\n")

    result = edit_file_replace_content(
        [
            {"path": str(file1), "content": "# First replacement\n"},
            {"path": str(file2), "content": "# Other\n"},
            {"path": str(file1), "content": "# Second replacement\n"},
        ],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "failed"
    assert len(result["applied_ops"]) == 0

    # Verify original content unchanged
    assert file1.read_text() == "# Original\n"
    assert file2.read_text() == "# Original\n"


def test_permission_error_rollback(temp_workspace: Path) -> None:
    """Test rollback on permission errors (if applicable)."""
    try:
        # Create files
        file1 = temp_workspace / "file1.py"
        file2 = temp_workspace / "readonly.py"
        file1.write_text("# File 1 original\n")
        file2.write_text("# Readonly original\n")

        # Make file2 read-only
        file2.chmod(0o444)

        result = edit_file_replace_content(
            [
                {"path": str(file1), "content": "# File 1 replaced\n"},
                {"path": str(file2), "content": "# Should fail\n"},
            ],
            workspace_root=str(temp_workspace),
        )

        # Should fail on permission error
        assert result["status"] == "failed"
        assert len(result["applied_ops"]) == 0

        # Verify first file unchanged (rollback)
        assert file1.read_text() == "# File 1 original\n"

    except (OSError, PermissionError):
        pytest.skip("Cannot simulate permission errors on this system")
    finally:
        # Cleanup: restore permissions
        try:
            file2.chmod(0o644)
        except Exception:
            pass


def test_response_format(temp_workspace: Path) -> None:
    """Test response includes all required fields."""
    test_file = temp_workspace / "test.py"
    test_file.write_text("# Original\n")

    result = edit_file_replace_content(
        [{"path": str(test_file), "content": "# Replaced\nprint('hello')\n"}],
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
    assert "lines_total" in op

    # Verify bytes_written is accurate
    assert op["bytes_written"] == test_file.stat().st_size


def test_multiline_content_preservation(temp_workspace: Path) -> None:
    """Test that multiline content with various line endings is preserved."""
    test_file = temp_workspace / "multiline.py"
    test_file.write_text("# Original\n")

    # Test content with various patterns
    content = """# Header

class MyClass:
    def __init__(self):
        self.value = 1

    def method(self):
        return self.value
"""

    result = edit_file_replace_content(
        [{"path": str(test_file), "content": content}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"

    # Verify exact content preserved
    assert test_file.read_text() == content
