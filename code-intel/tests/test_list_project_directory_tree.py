"""Tests for list_project_directory_tree MCP tool.

Covers:
- Simple directory structure
- Nested directories
- Blacklisted dirs excluded
- Empty directory
- Custom folder parameter (subfolder)
- Files and dirs ordering
- Non-existent folder error
- Path traversal prevention
- Blacklisted folder access error
"""

from pathlib import Path
from typing import Any

import pytest

from mcp_code_intel.tools.list_project_directory_tree import list_project_directory_tree

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tree(tmp_path: Path, spec: dict[str, Any]) -> None:
    """Create files/dirs from a nested dict. Values: str=file content, dict=subdir."""
    for name, val in spec.items():
        p = tmp_path / name
        if isinstance(val, dict):
            p.mkdir(parents=True, exist_ok=True)
            _make_tree(p, val)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(val, encoding="utf-8")


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------


def test_simple_flat_structure(tmp_path: Path) -> None:
    _make_tree(tmp_path, {"README.md": "hi", "main.py": "x=1"})
    result = list_project_directory_tree(folder="", workspace_root=tmp_path)
    assert result["path"] == "."
    struct = result["structure"]
    assert "README.md" in struct
    assert "main.py" in struct


def test_nested_directories(tmp_path: Path) -> None:
    _make_tree(tmp_path, {
        "src": {"app.py": "pass", "lib": {"utils.py": "pass"}},
    })
    result = list_project_directory_tree(folder="", workspace_root=tmp_path)
    struct = result["structure"]
    assert "src/" in struct


def test_subfolder_shows_files(tmp_path: Path) -> None:
    _make_tree(tmp_path, {
        "src": {"app.py": "pass", "lib": {"utils.py": "pass"}},
    })
    result = list_project_directory_tree(folder="src", workspace_root=tmp_path)
    struct = result["structure"]
    assert "app.py" in struct
    assert "lib/" in struct


def test_subfolder_nested_files(tmp_path: Path) -> None:
    _make_tree(tmp_path, {
        "src": {"lib": {"utils.py": "pass"}},
    })
    result = list_project_directory_tree(folder="src/lib", workspace_root=tmp_path)
    struct = result["structure"]
    assert "utils.py" in struct


# ---------------------------------------------------------------------------
# Blacklist filtering
# ---------------------------------------------------------------------------


def test_venv_excluded(tmp_path: Path) -> None:
    _make_tree(tmp_path, {
        ".venv": {"bin": {"python": "#!"}},
        "main.py": "pass",
    })
    result = list_project_directory_tree(folder="", workspace_root=tmp_path)
    struct = result["structure"]
    assert ".venv/" not in struct
    assert "main.py" in struct


def test_node_modules_excluded(tmp_path: Path) -> None:
    _make_tree(tmp_path, {
        "node_modules": {"express": {"index.js": ""}},
        "index.py": "pass",
    })
    result = list_project_directory_tree(folder="", workspace_root=tmp_path)
    assert "node_modules/" not in result["structure"]


def test_pycache_excluded(tmp_path: Path) -> None:
    _make_tree(tmp_path, {
        "src": {"__pycache__": {"mod.cpython-312.pyc": "bytes"}},
    })
    result = list_project_directory_tree(folder="src", workspace_root=tmp_path)
    assert "__pycache__/" not in result["structure"]


def test_git_excluded(tmp_path: Path) -> None:
    _make_tree(tmp_path, {
        ".git": {"HEAD": "ref: refs/heads/main"},
        "README.md": "hi",
    })
    result = list_project_directory_tree(folder="", workspace_root=tmp_path)
    assert ".git/" not in result["structure"]


def test_github_not_excluded(tmp_path: Path) -> None:
    _make_tree(tmp_path, {
        ".github": {"workflows": {"ci.yml": "name: CI"}},
    })
    result = list_project_directory_tree(folder="", workspace_root=tmp_path)
    assert ".github/" in result["structure"]


def test_accessing_blacklisted_dir_raises(tmp_path: Path) -> None:
    (tmp_path / "node_modules").mkdir()
    with pytest.raises(ValueError, match="blacklisted"):
        list_project_directory_tree(folder="node_modules", workspace_root=tmp_path)


# ---------------------------------------------------------------------------
# Empty directory
# ---------------------------------------------------------------------------


def test_empty_directory(tmp_path: Path) -> None:
    result = list_project_directory_tree(folder="", workspace_root=tmp_path)
    assert result["structure"] == {}


def test_empty_subdirectory(tmp_path: Path) -> None:
    (tmp_path / "empty_dir").mkdir()
    result = list_project_directory_tree(folder="empty_dir", workspace_root=tmp_path)
    assert result["structure"] == {}


# ---------------------------------------------------------------------------
# Ordering: directories before files
# ---------------------------------------------------------------------------


def test_dirs_before_files(tmp_path: Path) -> None:
    _make_tree(tmp_path, {
        "zebra": {"a.py": ""},
        "alpha": {"b.py": ""},
        "README.md": "hi",
    })
    result = list_project_directory_tree(folder="", workspace_root=tmp_path)
    keys = list(result["structure"].keys())
    # All dir keys (ending with /) should come before file keys
    dir_keys = [k for k in keys if k.endswith("/")]
    file_keys = [k for k in keys if not k.endswith("/")]
    if dir_keys and file_keys:
        last_dir_idx = keys.index(dir_keys[-1])
        first_file_idx = keys.index(file_keys[0])
        assert last_dir_idx < first_file_idx


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_nonexistent_folder_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Folder not found"):
        list_project_directory_tree(folder="does_not_exist", workspace_root=tmp_path)


def test_path_traversal_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Path traversal"):
        list_project_directory_tree(folder="../../etc", workspace_root=tmp_path)


def test_file_as_folder_raises(tmp_path: Path) -> None:
    (tmp_path / "file.txt").write_text("hello")
    with pytest.raises(ValueError, match="Not a directory"):
        list_project_directory_tree(folder="file.txt", workspace_root=tmp_path)


# ---------------------------------------------------------------------------
# Root vs subfolder mode differences
# ---------------------------------------------------------------------------


def test_root_mode_has_note(tmp_path: Path) -> None:
    """Root listing includes a note about file visibility."""
    _make_tree(tmp_path, {"a.py": "pass"})
    result = list_project_directory_tree(folder="", workspace_root=tmp_path)
    assert "note" in result


def test_subfolder_mode_no_note(tmp_path: Path) -> None:
    """Subfolder listing has no note."""
    _make_tree(tmp_path, {"sub": {"a.py": "pass"}})
    result = list_project_directory_tree(folder="sub", workspace_root=tmp_path)
    assert "note" not in result
