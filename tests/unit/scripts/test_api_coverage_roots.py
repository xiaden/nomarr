"""Tests for the API-coverage tool's repository-root derivation.

The API coverage utility computes the repository root in two places:

- ``scripts/human-scripts/check_api_coverage.py`` (the CLI entry point) — must
  resolve to ``<repo>`` via ``Path(__file__).resolve().parents[2]``.
- ``scripts/human-scripts/tools/api_coverage/discovery.py`` — must resolve to
  ``<repo>`` via ``Path(__file__).resolve().parents[4]``.

A historical bug used ``parent.parent`` / ``parent.parent.parent.parent`` which
resolved to ``<repo>/scripts`` instead, causing the report to be written to
``<repo>/scripts/scripts/outputs/api_coverage.html``. These tests pin the
correct resolution against the *actual* repository layout and assert that the
tool neither creates nor requires a ``scripts/scripts/`` tree.

The modules are loaded by on-disk path (the ``scripts/human-scripts`` tree is
not importable as a dotted package because of the hyphen), so expectations are
derived purely from ``__file__``-relative layout and never from the current
working directory. Importing either module performs no writes, so nothing is
created here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

# <repo>/tests/unit/scripts -> <repo> (same derivation as ./conftest.py).
REPO_ROOT = Path(__file__).resolve().parents[3]

CHECK_API_COVERAGE = REPO_ROOT / "scripts/human-scripts/check_api_coverage.py"
DISCOVERY = REPO_ROOT / "scripts/human-scripts/tools/api_coverage/discovery.py"


def _load_module(name: str, path: Path):
    """Load a module from its on-disk path, returning the module object."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_check_api_coverage_root_resolves_to_repository_root():
    """check_api_coverage.py must resolve its root to <repo>, not <repo>/scripts."""
    mod = _load_module("check_api_coverage", CHECK_API_COVERAGE)

    assert mod.project_root == REPO_ROOT
    assert mod.project_root != REPO_ROOT / "scripts"
    assert mod.project_root != REPO_ROOT / "scripts/scripts"


def test_discovery_root_resolves_to_repository_root():
    """discovery.py must resolve its root to <repo>, not <repo>/scripts."""
    mod = _load_module("api_coverage_discovery", DISCOVERY)

    assert mod.project_root == REPO_ROOT
    assert mod.project_root != REPO_ROOT / "scripts"
    assert mod.project_root != REPO_ROOT / "scripts/scripts"


def test_report_is_written_to_corrected_location_not_scripts_scripts():
    """The output path derived from the corrected root must not be nested under scripts/scripts/."""
    mod = _load_module("check_api_coverage", CHECK_API_COVERAGE)

    # Mirrors the tool's own derivation: root / "scripts" / "outputs" / "api_coverage.html".
    output = mod.project_root / "scripts" / "outputs" / "api_coverage.html"

    assert output == REPO_ROOT / "scripts/outputs/api_coverage.html"
    assert "scripts/scripts" not in output.as_posix()
