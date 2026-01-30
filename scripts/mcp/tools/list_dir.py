#!/usr/bin/env python3
"""Repository Structure Tool.

Returns directory tree structure with blacklist filtering for .venv, node_modules, etc.
"""

from __future__ import annotations

__all__ = ["list_dir"]

from fnmatch import fnmatch
from pathlib import Path
from typing import Any


def list_dir(folder: str = "", *, workspace_root: Path) -> dict[str, Any]:
    """List directory contents with smart filtering.

    Returns a JSON representation of the directory tree with blacklisted
    directories excluded (node_modules, .venv, etc.).

    Args:
        folder: Subfolder path relative to workspace root (empty for root)
               Use forward slashes: "nomarr/services"
        workspace_root: Root directory of the workspace

    Returns:
        JSON string representing directory structure

    Raises:
        FileNotFoundError: If folder doesn't exist
        ValueError: If folder path is invalid

    """
    # Directories that are always excluded
    blacklist_dirs = {
        ".venv",
        "venv",
        "node_modules",
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
    }

    # Glob patterns for exclusion
    blacklist_patterns = ["*.egg-info"]

    def should_exclude(path: Path) -> bool:
        for part in path.parts:
            # Check exact matches
            if part in blacklist_dirs:
                return True
            # Check hidden dirs (except .github)
            if part.startswith(".") and part not in {".github"}:
                return True
            # Check glob patterns
            for pattern in blacklist_patterns:
                if fnmatch(part, pattern):
                    return True
        return False

    def build_tree(
        root: Path, max_depth: int | None, current_depth: int = 0, show_files_at_root_only: bool = False
    ) -> dict[str, Any]:
        if not root.is_dir():
            return {"error": "not a directory"}

        tree: dict[str, Any] = {}

        try:
            items = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        except PermissionError:
            return {"error": "permission denied"}

        for item in items:
            if should_exclude(item):
                continue

            if item.is_dir():
                # Check max depth only if it's set
                if max_depth is not None and current_depth >= max_depth - 1:
                    # At max depth, mark folder but don't recurse
                    tree[item.name + "/ (max depth)"] = {}
                else:
                    tree[item.name + "/"] = build_tree(item, max_depth, current_depth + 1, show_files_at_root_only)
            # Include files based on mode
            elif show_files_at_root_only:
                # Only show files at depth 0 (workspace root)
                if current_depth == 0 and item.suffix in {".md", ".py", ".json", ".toml", ".yaml", ".yml", ".txt"}:
                    tree[item.name] = 1
            else:
                # Normal mode: show files at current level with suffix filter
                if current_depth == 0 or item.suffix in {".md", ".py", ".json", ".toml", ".yaml", ".yml", ".txt"}:
                    tree[item.name] = 1

        return tree

    # Resolve workspace root to absolute path
    workspace_root = workspace_root.resolve()

    # Resolve target path with security checks
    if folder:
        # Split by forward slash and construct path
        folder_parts = folder.split("/")
        target = (workspace_root / Path(*folder_parts)).resolve()

        # Security: ensure target is within workspace
        try:
            target.relative_to(workspace_root)
        except ValueError:
            msg = f"Path traversal attempt detected: {folder}"
            raise ValueError(msg)
    else:
        target = workspace_root

    if not target.exists():
        msg = f"Folder not found: {folder or '.'}"
        raise FileNotFoundError(msg)

    if not target.is_dir():
        msg = f"Not a directory: {folder}"
        raise ValueError(msg)

    # Check if target is blacklisted
    if should_exclude(target):
        msg = f"Cannot access blacklisted directory: {folder}"
        raise ValueError(msg)

    # Build tree structure
    # Root call: no max depth, files at root only (complete folder map)
    # Specific folder: max_depth=3, show files normally (content view)
    if folder == "":
        max_depth = None
        show_files_at_root_only = True
        note = "Complete folder structure. Files shown at root level only. Use folder parameter to see files in specific directories."
    else:
        max_depth = 3
        show_files_at_root_only = False
        note = None

    tree = build_tree(target, max_depth=max_depth, show_files_at_root_only=show_files_at_root_only)

    # Return structured dict
    result: dict[str, Any] = {"path": folder or ".", "structure": tree}
    if note:
        result["note"] = note

    return result

    # Return structured dict
    result = {"path": folder or ".", "structure": tree}
    if show_files_at_root_only:
        result["note"] = (
            "Files shown at root level only. Subdirectories show folder structure only. Use folder parameter to see files in specific directories."
        )

    return result
