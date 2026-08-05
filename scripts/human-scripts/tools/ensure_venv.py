"""Idempotent virtual environment setup for Nomarr workspace.

This script ensures the Python virtual environment exists and dependencies
are installed only when pyproject.toml / uv.lock has changed.

Usage:
    python scripts/human-scripts/tools/ensure_venv.py

Behavior:
- Creates .venv if it doesn't exist
- Only reinstalls dependencies if pyproject.toml or uv.lock has changed
- Uses marker file (.venv/.deps_hash) to track state
- Fast when nothing needs to be done
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import subprocess
import sys
from pathlib import Path


def get_project_root() -> Path:
    """Get project root from script location."""
    # This script is in scripts/human-scripts/tools/, so go up four levels
    return Path(__file__).parent.parent.parent.parent


def get_venv_path(project_root: Path) -> Path:
    """Get the virtual environment path."""
    # Always use .venv in project root
    return project_root / ".venv"


def get_venv_python(venv_path: Path) -> Path:
    """Get the Python executable path in the venv."""
    if sys.platform == "win32":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def compute_deps_hash(dep_paths: list[Path]) -> str:
    """Compute SHA256 hash of pyproject.toml and uv.lock."""
    existing = [p for p in dep_paths if p.exists()]
    if not existing:
        return ""

    sha256 = hashlib.sha256()
    for path in sorted(existing):
        sha256.update(path.name.encode("utf-8"))
        with open(path, "rb") as f:
            sha256.update(f.read())
    return sha256.hexdigest()


def get_stored_hash(venv_path: Path) -> str:
    """Read the stored dependency hash from marker file."""
    marker_file = venv_path / ".deps_hash"
    if not marker_file.exists():
        return ""

    try:
        return marker_file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def store_hash(venv_path: Path, hash_value: str) -> None:
    """Store the dependency hash in marker file."""
    marker_file = venv_path / ".deps_hash"
    with contextlib.suppress(OSError):
        marker_file.write_text(hash_value, encoding="utf-8")


def create_venv(venv_path: Path) -> bool:
    """Create virtual environment. Returns True if successful."""
    print("Creating virtual environment...")
    try:
        # Use current Python to create the venv
        subprocess.run([sys.executable, "-m", "venv", str(venv_path)], check=True, capture_output=True, text=True)
        print("✓ Created virtual environment")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to create virtual environment: {e}")
        if e.stderr:
            print(e.stderr)
        return False


def install_dependencies(venv_python: Path, project_root: Path) -> bool:
    """Install project dependencies from pyproject.toml ([dev] extra). Returns True if successful."""
    if not (project_root / "pyproject.toml").exists():
        print("⚠ pyproject.toml not found, skipping dependency installation")
        return True

    print("Installing dependencies from pyproject.toml (editable, [dev] extra)...")

    try:
        # Upgrade pip first
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "--upgrade", "pip"],
            check=True,
            capture_output=True,
            text=True,
        )

        # Install the project editable with dev extras, run from project root
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "-e", ".[dev]"],
            cwd=str(project_root),
            check=True,
            capture_output=True,
            text=True,
        )

        print("✓ Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to install dependencies: {e}")
        if e.stderr:
            print(e.stderr)
        return False


def main() -> int:
    """Main entry point."""
    # Parse arguments (accept but ignore --command for VS Code compatibility)
    parser = argparse.ArgumentParser(description="Setup Python virtual environment")
    parser.add_argument("--command", "-Command", help="Ignored (for VS Code compatibility)", default=None)
    parser.parse_args()

    project_root = get_project_root()
    venv_path = get_venv_path(project_root)
    dep_paths = [project_root / "pyproject.toml", project_root / "uv.lock"]
    venv_python = get_venv_python(venv_path)

    # Check if venv exists
    if not venv_path.exists():
        if not create_venv(venv_path):
            return 1

        # New venv, install dependencies
        if not install_dependencies(venv_python, project_root):
            return 1

        # Store hash after successful install
        deps_hash = compute_deps_hash(dep_paths)
        store_hash(venv_path, deps_hash)
        return 0

    # Venv exists, check if it's valid
    if not venv_python.exists():
        print("⚠ Virtual environment exists but Python executable not found")
        print("  Please delete .venv and run this script again")
        return 1

    print("✓ Virtual environment already exists")

    # Check if dependencies need updating
    current_hash = compute_deps_hash(dep_paths)
    stored_hash = get_stored_hash(venv_path)

    if current_hash == stored_hash and current_hash != "":
        print("✓ Dependencies are up-to-date")
        return 0

    # Dependencies changed or no marker file, reinstall
    if stored_hash == "":
        print("⚠ No dependency marker found, installing dependencies...")
    else:
        print("⚠ pyproject.toml / uv.lock has changed, updating dependencies...")

    if not install_dependencies(venv_python, project_root):
        return 1

    # Store new hash after successful install
    store_hash(venv_path, current_hash)
    return 0


if __name__ == "__main__":
    sys.exit(main())
