"""Clean-checkout proof for the Q2R-A Plan O/L architecture readers.

These tests prove the repaired readers pass with the globally gitignored
``artifacts/`` tree absent, without moving, deleting, or otherwise touching the
real ``artifacts/`` directory (non-destructive). They also scan the tracked
fixtures for sensitive tokens.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

ROOT = Path(__file__).parents[3]
FIXTURES = ROOT / "tests" / "unit" / "architecture" / "fixtures"
READERS = (
    ROOT / "tests" / "unit" / "architecture" / "test_o_security_provenance_rollback.py",
    ROOT / "tests" / "unit" / "architecture" / "test_l_residual_audit.py",
)
MANIFEST = ROOT / "tests" / "unit" / "architecture" / "capability-manifest.json"
WORKFLOW = ROOT / ".github" / "workflows" / "backend-tests.yml"

_UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_COMMIT40_RE = re.compile(r"\b[0-9a-fA-F]{40}\b")
_COMMIT8_RE = re.compile(r"\b[0-9a-fA-F]{8}\b")
_ABS_PATH_RE = re.compile(r"""(?:^|[\s'"`(])(/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+)""")
_CREDENTIAL_RE = re.compile(
    r"(?i)(?:password|passwd|secret|api[_-]?key|access[_-]?token|private[_-]?key|BEGIN [A-Z ]*PRIVATE KEY)"
)


def _fixture_files() -> list[Path]:
    return sorted(p for p in FIXTURES.iterdir() if p.is_file())


def _load_reader(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_fixtures_are_tracked_and_clean_checkout_safe() -> None:
    """The readers' required evidence lives under tracked ``tests/``, not the
    globally gitignored ``artifacts/`` tree (D3B precedent)."""
    files = _fixture_files()
    assert files, f"no tracked fixtures found under {FIXTURES}"
    for path in files:
        rel = path.relative_to(ROOT)
        assert rel.parts[0] == "tests", f"fixture must live under tests/: {rel}"
        assert "artifacts" not in rel.parts, f"fixture must not live under artifacts/: {rel}"
    if shutil.which("git") and (ROOT / ".git").exists():
        for path in files:
            rel = path.relative_to(ROOT)
            proc = subprocess.run(
                ["git", "check-ignore", "-q", str(rel)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            assert proc.returncode == 1, f"fixture {rel} is gitignored (git check-ignore rc={proc.returncode})"


@pytest.mark.unit
def test_required_reader_evidence_paths_are_under_tests_not_artifacts() -> None:
    """No REQUIRED reader evidence path resolves under ``artifacts/``.

    Resolve each declared name independently against the tracked fixture
    directory rather than through the reader's ``_fixture`` helper, so a
    relocated helper (or a fixture directory move) cannot mask a regression.
    """
    fixture_dir = ROOT / "tests" / "unit" / "architecture" / "fixtures"
    for reader_path in READERS:
        module = _load_reader(reader_path)
        required = module.REQUIRED_FIXTURES
        assert required, f"{reader_path.name} exposes no required fixture list"
        for name in required:
            resolved = fixture_dir / name
            rel = resolved.relative_to(ROOT)
            assert rel.parts[0] == "tests", f"required reader path must be under tests/: {rel}"
            assert "artifacts" not in rel.parts, f"required reader path must not be under artifacts/: {rel}"
            assert resolved.is_file(), f"required reader fixture missing: {rel}"


@pytest.mark.unit
@pytest.mark.parametrize("path", _fixture_files(), ids=lambda p: p.name)
def test_tracked_fixtures_contain_no_sensitive_tokens(path: Path) -> None:
    """Fixture-sensitivity scan: no real UUID, commit-like token, absolute path,
    or credential-like token is present in the tracked fixtures."""
    text = path.read_text(encoding="utf-8")
    assert _UUID_RE.search(text) is None, f"real UUID-like token in {path.name}"
    assert _COMMIT40_RE.search(text) is None, f"40-hex commit-like token in {path.name}"
    assert _COMMIT8_RE.search(text) is None, f"8-hex commit-like token in {path.name}"
    assert _ABS_PATH_RE.search(text) is None, f"absolute path in {path.name}"
    assert _CREDENTIAL_RE.search(text) is None, f"credential-like token in {path.name}"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("pattern", "sample"),
    [
        (_UUID_RE, "song 123e4567-e89b-12d3-a456-426614174000 leaked"),
        (_COMMIT40_RE, "HEAD 0123456789abcdef0123456789abcdef01234567 recorded"),
        (_COMMIT8_RE, "short 0123abcd token leaked"),
        (_ABS_PATH_RE, "stored at /srv/music/Artist/Album/track.flac"),
        (_CREDENTIAL_RE, "api_key = example"),
    ],
    ids=["uuid", "commit40", "commit8", "abs_path", "credential"],
)
def test_sensitive_patterns_match_crafted_poisoned_samples(pattern: re.Pattern[str], sample: str) -> None:
    """Positive control for the fixture-sensitivity scan.

    Each pattern must actually match a crafted poisoned sample; otherwise a
    regex typo would silently disable the guard while the suite stays green.
    The samples are deliberately fake and never appear in any fixture.
    """
    assert pattern.search(sample) is not None, f"pattern failed to match poisoned sample: {sample!r}"


@pytest.mark.unit
def test_sensitive_patterns_ignore_clean_contract_vocabulary() -> None:
    """Negative control: ordinary contract vocabulary must not trip the scan,
    so the guard does not false-positive on the fixtures' allowed prose."""
    clean = (
        "HydrateSongInput is locator-addressed payload-only and the opaque nom1 locator token are contract vocabulary."
    )
    for pattern in (_UUID_RE, _COMMIT40_RE, _COMMIT8_RE, _ABS_PATH_RE, _CREDENTIAL_RE):
        assert pattern.search(clean) is None, f"pattern false-positived on clean sample: {pattern.pattern!r}"


@pytest.mark.unit
def test_readers_pass_in_subprocess_tree_without_artifacts(tmp_path: Path) -> None:
    """Run both reader modules against a tree that contains only tracked
    fixtures (no ``artifacts/``) via the ``NOMARR_TEST_ROOT`` root override.

    The real ``artifacts/`` tree is never touched.
    """
    clean_root = tmp_path / "clean_root"
    (clean_root / "tests" / "unit" / "architecture" / "fixtures").mkdir(parents=True)
    (clean_root / ".github" / "workflows").mkdir(parents=True)
    for src in FIXTURES.iterdir():
        if src.is_file():
            shutil.copy2(src, clean_root / "tests" / "unit" / "architecture" / "fixtures" / src.name)
    shutil.copy2(MANIFEST, clean_root / "tests" / "unit" / "architecture" / MANIFEST.name)
    shutil.copy2(WORKFLOW, clean_root / ".github" / "workflows" / WORKFLOW.name)
    assert not (clean_root / "artifacts").exists()

    env = dict(os.environ)
    env["NOMARR_TEST_ROOT"] = str(clean_root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *(str(p) for p in READERS), "-v", "-p", "no:cacheprovider"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    # Pin that the guarded optional provenance test was reported SKIPPED, not
    # silently passed: absence of ignored evidence must never read as LOCAL_PASS.
    assert "1 skipped" in combined, f"guarded optional provenance test was not reported skipped:\n{combined}"
    assert "test_o_real_provenance_guarded_when_ignored_evidence_present" in combined, (
        f"guarded optional provenance test did not appear in the run summary:\n{combined}"
    )
