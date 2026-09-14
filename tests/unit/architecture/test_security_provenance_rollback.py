"""Static evidence gates for security, provenance, and rollback guidance.

The fixture-backed assertions read a tracked, non-sensitive fixture under
``tests/unit/architecture/fixtures/``, while the handoff check additionally
reads repository files (``capability-manifest.json`` and
``.github/workflows/backend-tests.yml``). No assertion reads the globally
gitignored ``artifacts/`` tree, so a clean checkout passes without it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_DEFAULT_ROOT = Path(__file__).parents[3]
REQUIRED_FIXTURES: tuple[str, ...] = ("security-provenance-rollback.md",)


def _root() -> Path:
    # NOMARR_TEST_ROOT lets the clean-checkout subprocess run the readers
    # against a temporary tree that lacks the ignored artifacts/ directory.
    override = os.environ.get("NOMARR_TEST_ROOT")
    return Path(override) if override else _DEFAULT_ROOT


def _fixture(name: str) -> Path:
    return _root() / "tests/unit/architecture/fixtures" / name


def _manifest_path() -> Path:
    return _root() / "tests/unit/architecture/capability-manifest.json"


def _workflow_path() -> Path:
    return _root() / ".github/workflows/backend-tests.yml"


def _assert_tracked_clean_checkout_fixture(path: Path) -> None:
    """Mirror the tracked-fixture containment proof for these fixtures."""
    assert path.is_file(), f"tracked evidence fixture missing: {path}"
    rel = path.relative_to(_root())
    assert rel.parts[0] == "tests", f"fixture must live under tests/: {rel}"
    assert "artifacts" not in rel.parts, f"fixture must not live under artifacts/: {rel}"
    if shutil.which("git") and (_root() / ".git").exists():
        proc = subprocess.run(
            ["git", "check-ignore", "-q", str(rel)],
            cwd=_root(),
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 1, f"tracked fixture {rel} is gitignored (git check-ignore rc={proc.returncode})"


@pytest.mark.unit
def test_evidence_records_execution_and_protected_file_provenance() -> None:
    path = _fixture("security-provenance-rollback.md")
    _assert_tracked_clean_checkout_fixture(path)
    text = path.read_text(encoding="utf-8")
    assert "worktree was **not** clean" in text
    assert "No commit was created" in text
    assert "protected" in text.lower()


@pytest.mark.unit
def test_evidence_requires_redaction_and_opaque_locator_contract() -> None:
    path = _fixture("security-provenance-rollback.md")
    _assert_tracked_clean_checkout_fixture(path)
    text = path.read_text(encoding="utf-8")
    for required in (
        "nom1",
        "library_uuid",
        "MISSING_LOCATOR",
        "normalized or absolute paths",
        "generated IDs",
        "SQL/session/constraint",
        "raw rows",
        "tag payloads",
        "credentials",
        "locator-addressed",
        "no inbound integer adapter",
        "resolve_song_identity",
        "resolve_song_identities",
        "Every other integer identity crossing is prohibited",
        "No broad resolver allowlist is invented",
    ):
        assert required in text


@pytest.mark.unit
def test_rollback_runbook_forbids_destructive_git_and_preserves_recovery() -> None:
    text = _fixture("security-provenance-rollback.md").read_text(encoding="utf-8")
    for forbidden in ("git reset", "git checkout", "git restore", "git stash", "git clean"):
        assert forbidden in text
    for required in (
        "Quiesce callers and workers",
        "Capture the exact HEAD",
        "Restore the complete protected set coherently",
        "recorded-recoverable",
        "ambiguous commit",
        "DB mood committed",
        "filesystem writeback failed",
    ):
        assert required in text


@pytest.mark.unit
def test_evidence_labels_preserve_blockers() -> None:
    text = _fixture("security-provenance-rollback.md").read_text(encoding="utf-8")
    assert "Exact handoff" in text
    assert "LOCAL_PASS" in text
    assert "LOCAL_UNAVAILABLE" in text
    assert "CI_DEFERRED" in text
    assert "CI_PASS" in text
    assert "BLOCKED" in text
    assert "mood owner" in text
    manifest = json.loads(_manifest_path().read_text(encoding="utf-8"))
    workflow = _workflow_path().read_text(encoding="utf-8")
    assert manifest["ci_job"] == "database-tests"
    assert manifest["marker"] == "requires_database"
    assert "continue-on-error" not in workflow
