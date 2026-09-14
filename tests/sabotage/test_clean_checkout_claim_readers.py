"""Clean-checkout proof for the state/claim contract reader.

These tests prove the ``tests/sabotage/test_state_claim_contracts.py`` module
passes with the globally gitignored ``artifacts/`` tree absent, without moving,
deleting, or otherwise touching the real ``artifacts/`` directory
(non-destructive). They also scan the tracked state/claim fixtures for sensitive
tokens.

The proof runs the reader in a subprocess for isolation: the subprocess gets a
clean ``NOMARR_TEST_ROOT`` tree with no ``artifacts/`` directory, so ``_root()``
resolves only the tracked ``tests/`` fixtures. Executing the reader's tests
in-process would instead run them against this repo root, where the ignored
``artifacts/`` tree exists and would mask the regression under test.
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

ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "tests" / "sabotage" / "fixtures"
READER = ROOT / "tests" / "sabotage" / "test_state_claim_contracts.py"

_REQUIRED_RUNNING_TESTS = (
    "test_broad_resolver_requires_named_allowlist_evidence",
    "test_owner_gate_records_missing_named_owner",
)

_UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_COMMIT40_RE = re.compile(r"\b[0-9a-fA-F]{40}\b")
_COMMIT8_RE = re.compile(r"\b[0-9a-fA-F]{8}\b")
# 32-hex calibration marker tokens and 64-hex SHA-256 digests must not slip past
# the scan; read them at a token boundary with alnum/underscore lookarounds (not
# ``\b``) so a 64-hex hash is caught too (a bare ``\b`` after 40 hex would let the
# trailing 24 hex digits continue an alnum token and not match).
_HEX32_RE = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{32}(?![0-9a-fA-F])")
_HEX64_RE = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])")
_ABS_PATH_RE = re.compile(r"""(?:^|[\s'"`(])(/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+)""")
_CREDENTIAL_RE = re.compile(
    r"(?i)(?:password|passwd|secret|api[_-]?key|access[_-]?token|private[_-]?key|BEGIN [A-Z ]*PRIVATE KEY)"
)

_SENSITIVE_PATTERNS = (_UUID_RE, _COMMIT40_RE, _COMMIT8_RE, _HEX32_RE, _HEX64_RE, _ABS_PATH_RE, _CREDENTIAL_RE)

# The exact assertion tokens the reader must keep: a future paired weakening of
# a reader assertion plus a fixture edit must not stay green.
_REQUIRED_ASSERTION_TOKENS = (
    "exact owner/boundary allowlist",
    "resolve_song_identity",
    "resolve_song_identities",
    "BLOCKED: no named owner contract",
    "No schema or marker semantics are invented",
)


def _fixture_files() -> list[Path]:
    return sorted(p for p in FIXTURES.iterdir() if p.is_file())


def _load_reader(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.sabotage_check
@pytest.mark.unit
def test_fixtures_are_tracked_and_clean_checkout_safe() -> None:
    """The reader's required evidence lives under tracked ``tests/``, not the
    globally gitignored ``artifacts/`` tree."""
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


@pytest.mark.sabotage_check
@pytest.mark.unit
def test_required_reader_evidence_paths_are_under_tests_not_artifacts() -> None:
    """No REQUIRED reader evidence path resolves under ``artifacts/``.

    Resolve each declared name independently against the tracked fixture
    directory rather than through the reader's ``_fixture`` helper, so a
    relocated helper (or a fixture directory move) cannot mask a regression.
    """
    fixture_dir = ROOT / "tests" / "sabotage" / "fixtures"
    reader = _load_reader(READER)
    required = reader.REQUIRED_FIXTURES
    assert required, f"{READER.name} exposes no required fixture list"
    for name in required:
        resolved = fixture_dir / name
        rel = resolved.relative_to(ROOT)
        assert rel.parts[0] == "tests", f"required reader path must be under tests/: {rel}"
        assert "artifacts" not in rel.parts, f"required reader path must not be under artifacts/: {rel}"
        assert resolved.is_file(), f"required reader fixture missing: {rel}"


@pytest.mark.sabotage_check
@pytest.mark.unit
@pytest.mark.parametrize("path", _fixture_files(), ids=lambda p: p.name)
def test_tracked_fixtures_contain_no_sensitive_tokens(path: Path) -> None:
    """Fixture-sensitivity scan: no real UUID, commit-like token, 32-hex
    calibration marker, 64-hex SHA-256 digest, absolute path, or credential-like
    token is present in the tracked state/claim fixtures."""
    text = path.read_text(encoding="utf-8")
    assert _UUID_RE.search(text) is None, f"real UUID-like token in {path.name}"
    assert _COMMIT40_RE.search(text) is None, f"40-hex commit-like token in {path.name}"
    assert _COMMIT8_RE.search(text) is None, f"8-hex commit-like token in {path.name}"
    assert _HEX32_RE.search(text) is None, f"32-hex calibration-marker token in {path.name}"
    assert _HEX64_RE.search(text) is None, f"64-hex SHA-256 token in {path.name}"
    assert _ABS_PATH_RE.search(text) is None, f"absolute path in {path.name}"
    assert _CREDENTIAL_RE.search(text) is None, f"credential-like token in {path.name}"


@pytest.mark.sabotage_check
@pytest.mark.unit
@pytest.mark.parametrize(
    ("pattern", "sample"),
    [
        (_UUID_RE, "song 123e4567-e89b-12d3-a456-426614174000 leaked"),
        (_COMMIT40_RE, "HEAD 0123456789abcdef0123456789abcdef01234567 recorded"),
        (_COMMIT8_RE, "short 0123abcd token leaked"),
        (_HEX32_RE, "calibration marker deadbeefdeadbeefdeadbeefdeadbeef leaked"),
        (_HEX64_RE, "sha256 " + "a" * 64 + " leaked"),
        (_ABS_PATH_RE, "stored at /srv/music/Artist/Album/track.flac"),
        (_CREDENTIAL_RE, "api_key = example"),
    ],
    ids=["uuid", "commit40", "commit8", "hex32_calibration_marker", "hex64_sha256", "abs_path", "credential"],
)
def test_sensitive_patterns_match_crafted_poisoned_samples(pattern: re.Pattern[str], sample: str) -> None:
    """Positive control for the fixture-sensitivity scan.

    Each pattern must actually match a crafted poisoned sample; otherwise a
    regex typo would silently disable the guard while the suite stays green.
    """
    assert pattern.search(sample) is not None, f"pattern failed to match poisoned sample: {sample!r}"


@pytest.mark.sabotage_check
@pytest.mark.unit
def test_sensitive_patterns_ignore_clean_contract_vocabulary() -> None:
    """Negative control: ordinary contract vocabulary must not trip the scan."""
    clean = (
        "HydrateSongInput is locator-addressed payload-only and the opaque nom1 locator token are contract vocabulary."
    )
    for pattern in _SENSITIVE_PATTERNS:
        assert pattern.search(clean) is None, f"pattern false-positived on clean sample: {pattern.pattern!r}"


@pytest.mark.sabotage_check
@pytest.mark.unit
def test_reader_passes_in_subprocess_tree_without_artifacts(tmp_path: Path) -> None:
    """Run the reader against a tree that contains only tracked fixtures (no
    ``artifacts/``) via the ``NOMARR_TEST_ROOT`` root override.

    The real ``artifacts/`` tree is never touched.
    """
    clean_root = tmp_path / "clean_root"
    (clean_root / "tests" / "sabotage" / "fixtures").mkdir(parents=True)
    for src in _fixture_files():
        shutil.copy2(src, clean_root / "tests" / "sabotage" / "fixtures" / src.name)
    assert not (clean_root / "artifacts").exists()

    env = dict(os.environ)
    env["NOMARR_TEST_ROOT"] = str(clean_root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(READER), "-v", "-p", "no:cacheprovider"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    # The fixture-backed evidence tests must actually RUN and pass, not be
    # skipped or silently absent on a clean checkout.
    for node in _REQUIRED_RUNNING_TESTS:
        assert node in combined, f"required reader test did not appear in the run:\n{combined}"
        assert f"{node} PASSED" in combined, f"required reader test did not pass:\n{combined}"


@pytest.mark.sabotage_check
@pytest.mark.unit
def test_reader_keeps_required_assertion_tokens() -> None:
    """Pin the exact assertion tokens the reader must keep.

    Guards against a future paired weakening of a reader assertion plus a fixture
    edit: both the reader source and the tracked fixtures must still carry every
    required token.
    """
    reader_text = READER.read_text(encoding="utf-8")
    fixture_text = "\n".join(path.read_text(encoding="utf-8") for path in _fixture_files())
    assert "locator-addressed" in fixture_text
    assert "No schema or marker semantics are invented" in fixture_text
    for token in _REQUIRED_ASSERTION_TOKENS:
        assert token in reader_text, f"required reader assertion token missing from reader: {token!r}"
        assert token in fixture_text, f"required reader assertion token missing from fixtures: {token!r}"
