"""Tests for edit_file_move tool."""

import textwrap
from pathlib import Path

import pytest

from mcp_code_intel.tools.edit_file_move import edit_file_move


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    """Workspace root."""
    return tmp_path


def _make_file(ws: Path, rel: str, content: str = "hello\n") -> Path:
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


# -- Happy paths --


def test_move_file_to_new_directory(ws: Path) -> None:
    """Move a file into a directory that doesn't exist yet (auto-creates parents)."""
    _make_file(ws, "src/old.py", "content\n")

    result = edit_file_move("src/old.py", "dst/sub/new.py", workspace_root=ws)

    assert result["status"] == "moved"
    assert not (ws / "src/old.py").exists()
    assert (ws / "dst/sub/new.py").read_text() == "content\n"
    assert "dst" in result["dirs_created"][0] or "dst\\sub" in result["dirs_created"][0]
    assert result["bytes"] > 0


def test_rename_file_in_same_directory(ws: Path) -> None:
    """Rename a file without changing its directory."""
    _make_file(ws, "foo.txt", "data")

    result = edit_file_move("foo.txt", "bar.txt", workspace_root=ws)

    assert result["status"] == "moved"
    assert not (ws / "foo.txt").exists()
    assert (ws / "bar.txt").read_text() == "data"
    assert result["dirs_created"] == []


def test_move_to_existing_directory(ws: Path) -> None:
    """Move a file into a directory that already exists."""
    _make_file(ws, "a.txt", "abc")
    (ws / "existing_dir").mkdir()

    result = edit_file_move("a.txt", "existing_dir/a.txt", workspace_root=ws)

    assert result["status"] == "moved"
    assert (ws / "existing_dir/a.txt").read_text() == "abc"
    assert result["dirs_created"] == []


def test_move_preserves_file_content(ws: Path) -> None:
    """After move, destination has identical content to original source."""
    content = textwrap.dedent("""\
        line 1
        line 2
        line 3
    """)
    _make_file(ws, "original.py", content)

    edit_file_move("original.py", "moved.py", workspace_root=ws)

    assert not (ws / "original.py").exists()
    assert (ws / "moved.py").read_text() == content


def test_relative_paths_work(ws: Path) -> None:
    """Workspace-relative paths resolve correctly."""
    _make_file(ws, "sub/file.txt", "ok")

    result = edit_file_move("sub/file.txt", "sub/renamed.txt", workspace_root=ws)

    assert result["status"] == "moved"
    assert "sub" in result["old_path"]


# -- Error cases --


def test_source_not_found(ws: Path) -> None:
    """Source file doesn't exist → error."""
    result = edit_file_move("nonexistent.py", "dest.py", workspace_root=ws)

    assert "error" in result


def test_destination_already_exists(ws: Path) -> None:
    """Destination already exists → error."""
    _make_file(ws, "src.txt", "source")
    _make_file(ws, "dst.txt", "dest")

    result = edit_file_move("src.txt", "dst.txt", workspace_root=ws)

    assert "error" in result
    assert "already exists" in result["error"].lower() or "Target already exists" in result["error"]
    # Source should be untouched
    assert (ws / "src.txt").read_text() == "source"


def test_same_source_and_dest(ws: Path) -> None:
    """Source and destination are the same path → error."""
    _make_file(ws, "same.txt", "data")

    result = edit_file_move("same.txt", "same.txt", workspace_root=ws)

    assert "error" in result
