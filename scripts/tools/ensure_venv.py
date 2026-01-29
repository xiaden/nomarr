"""
Idempotent virtual environment setup for Nomarr workspace.

This script ensures the Python virtual environment exists and dependencies
are installed only when requirements.txt has changed.

Usage:
    python scripts/tools/ensure_venv.py

Behavior:
- Creates .venv if it doesn't exist
- Only reinstalls requirements if requirements.txt has changed
- Uses marker file (.venv/.requirements_hash) to track state
- Fast when nothing needs to be done
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path


def get_project_root() -> Path:
    """Get project root from script location."""
    # This script is in scripts/tools/, so go up two levels
    return Path(__file__).parent.parent.parent


def get_venv_path(project_root: Path) -> Path:
    """Get the virtual environment path."""
    # Always use .venv in project root
    return project_root / ".venv"


def get_venv_python(venv_path: Path) -> Path:
    """Get the Python executable path in the venv."""
    if sys.platform == "win32":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def compute_requirements_hash(requirements_path: Path) -> str:
    """Compute SHA256 hash of requirements.txt."""
    if not requirements_path.exists():
        return ""

    sha256 = hashlib.sha256()
    with open(requirements_path, "rb") as f:
        sha256.update(f.read())
    return sha256.hexdigest()


def get_stored_hash(venv_path: Path) -> str:
    """Read the stored requirements hash from marker file."""
    marker_file = venv_path / ".requirements_hash"
    if not marker_file.exists():
        return ""

    try:
        return marker_file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def store_hash(venv_path: Path, hash_value: str) -> None:
    """Store the requirements hash in marker file."""
    marker_file = venv_path / ".requirements_hash"
    try:
        marker_file.write_text(hash_value, encoding="utf-8")
    except OSError:
        pass  # Not critical if we can't write the marker


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


def install_requirements(venv_python: Path, requirements_path: Path) -> bool:
    """Install requirements.txt. Returns True if successful."""
    if not requirements_path.exists():
        print("⚠ requirements.txt not found, skipping dependency installation")
        return True

    print("Installing dependencies from requirements.txt...")

    try:
        # Upgrade pip first
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], check=True, capture_output=True, text=True
        )

        # Install requirements
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "-r", str(requirements_path)],
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
    requirements_path = project_root / "requirements.txt"
    venv_python = get_venv_python(venv_path)

    # Check if venv exists
    if not venv_path.exists():
        if not create_venv(venv_path):
            return 1

        # New venv, install requirements
        if not install_requirements(venv_python, requirements_path):
            return 1

        # Store hash after successful install
        req_hash = compute_requirements_hash(requirements_path)
        store_hash(venv_path, req_hash)
        return 0

    # Venv exists, check if it's valid
    if not venv_python.exists():
        print("⚠ Virtual environment exists but Python executable not found")
        print("  Please delete .venv and run this script again")
        return 1

    print("✓ Virtual environment already exists")

    # Check if requirements need updating
    current_hash = compute_requirements_hash(requirements_path)
    stored_hash = get_stored_hash(venv_path)

    if current_hash == stored_hash and current_hash != "":
        print("✓ Dependencies are up-to-date")
        return 0

    # Requirements changed or no marker file, reinstall
    if stored_hash == "":
        print("⚠ No requirements marker found, installing dependencies...")
    else:
        print("⚠ requirements.txt has changed, updating dependencies...")

    if not install_requirements(venv_python, requirements_path):
        return 1

    # Store new hash after successful install
    store_hash(venv_path, current_hash)
    return 0


if __name__ == "__main__":
    sys.exit(main())
