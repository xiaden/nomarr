"""File discovery for code graph builder."""

from __future__ import annotations

from pathlib import Path


def discover_python_files(search_paths: list[Path]) -> list[Path]:
    """Discover all Python source files under search paths.

    Skips cache directories and non-source files.
    """
    skip_dirs = {"__pycache__", ".venv", ".mypy_cache", ".pytest_cache", ".tox", "build", "dist", ".git"}
    python_files = []

    for search_path in search_paths:
        for py_file in search_path.rglob("*.py"):
            # Skip if any parent directory is in skip_dirs
            if any(parent.name in skip_dirs for parent in py_file.parents):
                continue

            python_files.append(py_file)

    return sorted(python_files)
