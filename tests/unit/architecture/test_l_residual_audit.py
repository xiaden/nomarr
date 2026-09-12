"""Static gates for Plan L's residual inventory and downstream handoff.

Clean-checkout boundary (Q2R-A): assertions read tracked, non-sensitive fixtures
under ``tests/unit/architecture/fixtures/`` instead of the globally gitignored
``artifacts/`` tree.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_DEFAULT_ROOT = Path(__file__).parents[3]
REQUIRED_FIXTURES: tuple[str, ...] = ("l-residual-manifest.md", "song-row-mirror-contracts.md")


def _root() -> Path:
    # NOMARR_TEST_ROOT lets the clean-checkout subprocess run the readers
    # against a temporary tree that lacks the ignored artifacts/ directory.
    override = os.environ.get("NOMARR_TEST_ROOT")
    return Path(override) if override else _DEFAULT_ROOT


def _fixture(name: str) -> Path:
    return _root() / "tests/unit/architecture/fixtures" / name


def _assert_tracked_clean_checkout_fixture(path: Path) -> None:
    """Mirror the D3B tracked-fixture containment proof for these fixtures."""
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


def test_manifest_has_complete_classification_vocabulary() -> None:
    path = _fixture("l-residual-manifest.md")
    _assert_tracked_clean_checkout_fixture(path)
    text = path.read_text(encoding="utf-8")
    required = {
        "PERSISTENCE_PRIVATE",
        "LOCATOR_BOUNDARY",
        "HYDRATE_INBOUND_ONLY",
        "EXACT_ALLOWLIST",
        "DEAD_ALLOWLISTED",
        "EXTERNAL_OWNER",
        "RELEASE_BLOCKING_DEFECT",
    }
    assert all(f"`{item}`" in text for item in required)
    for owner in ("**M**", "**N**", "**O**", "**P**"):
        assert owner in text


def test_manifest_does_not_approve_broad_resolvers_or_integer_wire_ids() -> None:
    text = _fixture("l-residual-manifest.md").read_text(encoding="utf-8")
    assert (
        "each other resolver needs owner, boundary, reason, positive test, non-propagation, removal condition" in text
    )
    assert "never integer" in text
    assert "No wrapper or alias added by L" in text


def test_contract_keeps_hydration_as_the_only_provisional_integer_adapter() -> None:
    path = _fixture("song-row-mirror-contracts.md")
    _assert_tracked_clean_checkout_fixture(path)
    text = path.read_text(encoding="utf-8")
    assert "HydrateSongInput" in text
    assert "All other integer identity crossings are prohibited" in text
    assert "exact L/N/P allowlist" in text


def test_manifest_records_unavailable_infrastructure_without_false_pass() -> None:
    text = _fixture("l-residual-manifest.md").read_text(encoding="utf-8")
    assert "LOCAL_UNAVAILABLE" in text
    assert "CI_DEFERRED" in text
    assert "no local PASS" in text
