"""Tests for edit_file_create tool."""

from pathlib import Path

import pytest

from mcp_code_intel.tools.edit_file_create import edit_file_create


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Create temporary workspace for testing."""
    return tmp_path


def test_create_single_file(temp_workspace: Path) -> None:
    """Test creating a single file."""
    result = edit_file_create(
        [{"path": str(temp_workspace / "test.py"), "content": "# Test\n"}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"
    assert len(result["applied_ops"]) == 1
    assert len(result["failed_ops"]) == 0

    # Verify file exists and has correct content
    test_file = temp_workspace / "test.py"
    assert test_file.exists()
    assert test_file.read_text() == "# Test\n"

    # Verify context returned
    op = result["applied_ops"][0]
    assert "new_context" in op
    assert "Created test.py" in op["new_context"]
    assert "7 bytes" in op["new_context"]


def test_create_batch_files(temp_workspace: Path) -> None:
    """Test creating multiple files in one batch."""
    result = edit_file_create(
        [
            {"path": str(temp_workspace / "file1.py"), "content": "# File 1\n"},
            {"path": str(temp_workspace / "file2.py"), "content": "# File 2\n"},
            {"path": str(temp_workspace / "file3.py"), "content": "# File 3\n"},
        ],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"
    assert len(result["applied_ops"]) == 3
    assert len(result["failed_ops"]) == 0

    # Verify all files exist
    assert (temp_workspace / "file1.py").exists()
    assert (temp_workspace / "file2.py").exists()
    assert (temp_workspace / "file3.py").exists()


def test_create_nested_directories(temp_workspace: Path) -> None:
    """Test creating files in nested directories (mkdir -p behavior)."""
    result = edit_file_create(
        [
            {
                "path": str(temp_workspace / "services" / "auth" / "session.py"),
                "content": "# Session\n",
            },
            {
                "path": str(temp_workspace / "services" / "auth" / "token.py"),
                "content": "# Token\n",
            },
            {
                "path": str(temp_workspace / "services" / "user" / "profile.py"),
                "content": "# Profile\n",
            },
        ],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"
    assert len(result["applied_ops"]) == 3

    # Verify all nested files exist
    assert (temp_workspace / "services" / "auth" / "session.py").exists()
    assert (temp_workspace / "services" / "auth" / "token.py").exists()
    assert (temp_workspace / "services" / "user" / "profile.py").exists()


def test_create_empty_file(temp_workspace: Path) -> None:
    """Test creating an empty file."""
    result = edit_file_create(
        [{"path": str(temp_workspace / "empty.txt")}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"
    assert len(result["applied_ops"]) == 1

    # Verify file exists and is empty
    empty_file = temp_workspace / "empty.txt"
    assert empty_file.exists()
    assert empty_file.read_text() == ""


def test_fail_on_existing_file(temp_workspace: Path) -> None:
    """Test failure when target file already exists."""
    # Create a file first
    existing = temp_workspace / "existing.py"
    existing.write_text("# Existing\n")

    # Try to create it again
    result = edit_file_create(
        [{"path": str(existing), "content": "# New\n"}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "failed"
    assert len(result["applied_ops"]) == 0
    assert len(result["failed_ops"]) == 1
    assert "already exists" in result["failed_ops"][0]["reason"].lower()

    # Verify original content unchanged
    assert existing.read_text() == "# Existing\n"


def test_rollback_on_partial_failure(temp_workspace: Path) -> None:
    """Test complete rollback when one file in batch fails."""
    # Create an existing file
    existing = temp_workspace / "existing.py"
    existing.write_text("# Existing\n")

    # Try to create batch with one existing file
    result = edit_file_create(
        [
            {"path": str(temp_workspace / "new1.py"), "content": "# New 1\n"},
            {"path": str(temp_workspace / "new2.py"), "content": "# New 2\n"},
            {"path": str(existing), "content": "# Should fail\n"},
            {"path": str(temp_workspace / "new3.py"), "content": "# New 3\n"},
        ],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "failed"
    assert len(result["applied_ops"]) == 0  # No partial success

    # Verify none of the new files were created
    assert not (temp_workspace / "new1.py").exists()
    assert not (temp_workspace / "new2.py").exists()
    assert not (temp_workspace / "new3.py").exists()

    # Verify existing file unchanged
    assert existing.read_text() == "# Existing\n"


def test_duplicate_paths_in_batch(temp_workspace: Path) -> None:
    """Test failure when batch contains duplicate paths."""
    result = edit_file_create(
        [
            {"path": str(temp_workspace / "dup.py"), "content": "# First\n"},
            {"path": str(temp_workspace / "other.py"), "content": "# Other\n"},
            {"path": str(temp_workspace / "dup.py"), "content": "# Second\n"},
        ],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "failed"
    assert len(result["applied_ops"]) == 0

    # Verify no files created
    assert not (temp_workspace / "dup.py").exists()
    assert not (temp_workspace / "other.py").exists()


def test_large_file_context_capping(temp_workspace: Path) -> None:
    """Test context is capped at ~52 lines for large files."""
    # Create content with 100 lines
    lines = [f"# Line {i}\n" for i in range(1, 101)]
    content = "".join(lines)

    result = edit_file_create(
        [{"path": str(temp_workspace / "large.py"), "content": content}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"

    # Verify file created with all content
    large_file = temp_workspace / "large.py"
    assert large_file.exists()
    assert large_file.read_text() == content

    # Verify context is capped (should be ~52 lines, not all 100)
    op = result["applied_ops"][0]
    assert "new_context" in op
    context_lines = op["new_context"].split("\n")
    assert len(context_lines) <= 55  # ~52 + some margin


def test_very_large_file_over_1mb(temp_workspace: Path) -> None:
    """Test handling files larger than 1MB."""
    # Create content over 1MB (1048576 bytes)
    # Each line is ~100 bytes, so 11000 lines = ~1.1MB
    lines = [f"# This is line {i} with some padding text to make it longer\n" for i in range(11000)]
    content = "".join(lines)
    assert len(content.encode()) > 1_048_576  # Verify >1MB

    result = edit_file_create(
        [{"path": str(temp_workspace / "huge.py"), "content": content}],
        workspace_root=str(temp_workspace),
    )

    assert result["status"] == "applied"

    # Verify file created
    huge_file = temp_workspace / "huge.py"
    assert huge_file.exists()
    assert huge_file.stat().st_size > 1_048_576

    # Verify context summary returned (not full file content due to size)
    op = result["applied_ops"][0]
    assert "new_context" in op
    assert "Created huge.py" in op["new_context"]
    assert "bytes" in op["new_context"]


def test_permission_error_rollback(temp_workspace: Path) -> None:
    """Test rollback on permission errors (if applicable)."""
    import sys
    if sys.platform == "win32":
        pytest.skip("Permission error simulation not reliable on Windows")

    # This test is platform-dependent and may not work on all systems
    # Skip if we can't simulate permission errors
    try:
        # Create a read-only directory
        readonly_dir = temp_workspace / "readonly"
        readonly_dir.mkdir()
        readonly_dir.chmod(0o444)  # Read-only

        result = edit_file_create(
            [
                {"path": str(temp_workspace / "good.py"), "content": "# Good\n"},
                {"path": str(readonly_dir / "bad.py"), "content": "# Bad\n"},
            ],
            workspace_root=str(temp_workspace),
        )

        # Should fail on permission error
        assert result["status"] == "failed"
        assert len(result["applied_ops"]) == 0

        # Verify first file not created (rollback)
        assert not (temp_workspace / "good.py").exists()

    except (OSError, PermissionError):
        pytest.skip("Cannot simulate permission errors on this system")
    finally:
        # Cleanup: restore permissions
        try:
            readonly_dir.chmod(0o755)
        except Exception:
            pass


def test_response_format(temp_workspace: Path) -> None:
    """Test response includes all required fields."""
    result = edit_file_create(
        [{"path": str(temp_workspace / "test.py"), "content": "# Test\nprint('hello')\n"}],
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

    # Verify bytes_written is accurate
    test_file = temp_workspace / "test.py"
    assert op["bytes_written"] == test_file.stat().st_size
