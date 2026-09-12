"""Clean-checkout proof for the Q2R-B Plan H state/claim reader.

These tests prove the repaired ``tests/sabotage/test_h_state_claim_contracts.py``
module passes with the globally gitignored ``artifacts/`` tree absent, without
moving, deleting, or otherwise touching the real ``artifacts/`` directory
(non-destructive). They also scan the tracked Plan H fixtures for sensitive
tokens and statically guard that the two REQUIRED evidence reads never use an
``artifacts/`` path (that read is confined to the guarded optional test only).

The proof runs the H reader in a subprocess for isolation: the subprocess gets a
clean ``NOMARR_TEST_ROOT`` tree with no ``artifacts/`` directory, so ``_root()``
resolves only the tracked ``tests/`` fixtures. Executing the reader's tests
in-process would instead run them against this repo root, where the ignored
``artifacts/`` tree exists and would mask the regression under test.
"""

from __future__ import annotations

import ast
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
READER = ROOT / "tests" / "sabotage" / "test_h_state_claim_contracts.py"

_REQUIRED_RUNNING_TESTS = (
    "test_broad_resolver_requires_named_allowlist_evidence",
    "test_handoff_evidence_records_missing_named_owner",
)
_GUARDED_OPTIONAL_TEST = "test_h_real_evidence_guarded_when_ignored_docs_present"

_UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_COMMIT40_RE = re.compile(r"\b[0-9a-fA-F]{40}\b")
_COMMIT8_RE = re.compile(r"\b[0-9a-fA-F]{8}\b")
# 32-hex calibration marker tokens (CONTRACTS §9.3.1) and 64-hex SHA-256 digests
# must not slip past the scan; read them at a token boundary with alnum/underscore
# lookarounds (not ``\b``) so a 64-hex hash is caught too (a bare ``\b`` after 40
# hex would let the trailing 24 hex digits continue an alnum token and not match).
_HEX32_RE = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{32}(?![0-9a-fA-F])")
_HEX64_RE = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])")
_ABS_PATH_RE = re.compile(r"""(?:^|[\s'"`(])(/[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+)""")
_CREDENTIAL_RE = re.compile(
    r"(?i)(?:password|passwd|secret|api[_-]?key|access[_-]?token|private[_-]?key|BEGIN [A-Z ]*PRIVATE KEY)"
)

_SENSITIVE_PATTERNS = (_UUID_RE, _COMMIT40_RE, _COMMIT8_RE, _HEX32_RE, _HEX64_RE, _ABS_PATH_RE, _CREDENTIAL_RE)

# The exact assertion tokens the H reader must keep: a future paired weakening of
# a reader assertion plus a fixture edit must not stay green.
_REQUIRED_ASSERTION_TOKENS = (
    "exact L/N/P allowlist",
    "HydrateSongInput(song_id: int, ...)",
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
def test_h_fixtures_are_tracked_and_clean_checkout_safe() -> None:
    """The H reader's required evidence lives under tracked ``tests/``, not the
    globally gitignored ``artifacts/`` tree (Q2R-A/D3B precedent)."""
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
def test_h_required_reads_use_no_artifacts_path_outside_guarded_optional() -> None:
    """Static source guard: the two REQUIRED H evidence reads must not use an
    ``artifacts/`` path.

    The subprocess proof redirects ``_root()``-relative reads only, and it runs
    with ``cwd=repo root`` where the ignored ``artifacts/`` tree exists, so a
    regression that restored a cwd-relative read (``Path("artifacts/...")``,
    ``Path("artifacts") / "designs"``, ``"artifacts" + "/designs"``, or an
    f-string) for a required read would still pass that proof. Here every
    artifacts path construction in the reader source must fall inside the guarded
    optional test function, so the two required reads resolve under ``tests/``
    (tracked fixtures) instead.
    """
    reader_source = READER.read_text(encoding="utf-8")
    tree = ast.parse(reader_source, filename=str(READER))
    top_level_functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    guarded = next((node for node in top_level_functions if node.name == _GUARDED_OPTIONAL_TEST), None)
    assert guarded is not None, f"guarded optional test {_GUARDED_OPTIONAL_TEST!r} not defined in {READER.name}"
    docstrings = {
        id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    # Attach parent links so path-construction context (BinOp / Call / Subscript /
    # JoinedStr) can be inspected.
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child.parent = parent  # type: ignore[attr-defined]

    # Collect the ``"artifacts"`` string constants that take part in path
    # construction, and the offset of the *enclosing* node whose location we check.
    # This catches:
    #   * ``Path("artifacts/...")``                       (direct call arg, value starts with artifacts/)
    #   * ``Path("artifacts") / "designs"``               (call arg -> enclosing BinOp)
    #   * ``"artifacts" + "/designs"``                     (BinOp operand)
    #   * ``f"artifacts/{sub}"``                           (JoinedStr value)
    #   * ``parts["artifacts"]``                           (subscript slice)
    # The legitimate containment assertion ``"artifacts" not in rel.parts`` is a
    # Compare operand, not path construction, and is deliberately NOT flagged.
    artifacts_constants: list[ast.Constant] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings):
            continue
        if node.value.startswith("artifacts/") or node.value.startswith("artifacts\\"):
            artifacts_constants.append(node)
            continue
        if node.value != "artifacts":
            continue
        parent = getattr(node, "parent", None)
        if (
            isinstance(parent, ast.Subscript)
            or (isinstance(parent, ast.BinOp) and isinstance(parent.op, (ast.Div, ast.Add)))
            or isinstance(parent, ast.JoinedStr)
        ):
            artifacts_constants.append(node)
        elif isinstance(parent, ast.Call):
            func = parent.func
            func_name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if func_name in {"Path", "PurePath", "joinpath"}:
                artifacts_constants.append(node)

    assert artifacts_constants, f"expected the guarded optional test to reference artifacts/ in {READER.name}"
    guarded_end = guarded.end_lineno or guarded.lineno
    for node in artifacts_constants:
        parent = getattr(node, "parent", None)
        flagged = parent if parent is not None else node
        lineno = getattr(flagged, "lineno", node.lineno)
        assert guarded.lineno <= lineno <= guarded_end, (
            f"artifacts path construction outside the guarded optional test at {READER.name}:{lineno}: {node.value!r}"
        )


@pytest.mark.sabotage_check
@pytest.mark.unit
def test_h_required_reader_evidence_paths_are_under_tests_not_artifacts() -> None:
    """No REQUIRED H reader evidence path resolves under ``artifacts/``.

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
def test_h_tracked_fixtures_contain_no_sensitive_tokens(path: Path) -> None:
    """Fixture-sensitivity scan: no real UUID, commit-like token, 32-hex
    calibration marker, 64-hex SHA-256 digest, absolute path, or credential-like
    token is present in the tracked H fixtures."""
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
def test_h_sensitive_patterns_match_crafted_poisoned_samples(pattern: re.Pattern[str], sample: str) -> None:
    """Positive control for the H fixture-sensitivity scan.

    Each pattern must actually match a crafted poisoned sample; otherwise a
    regex typo would silently disable the guard while the suite stays green.
    """
    assert pattern.search(sample) is not None, f"pattern failed to match poisoned sample: {sample!r}"


@pytest.mark.sabotage_check
@pytest.mark.unit
def test_h_sensitive_patterns_ignore_clean_contract_vocabulary() -> None:
    """Negative control: ordinary contract vocabulary must not trip the scan."""
    clean = "HydrateSongInput(song_id: int, ...) and the opaque nom1 locator token are contract vocabulary."
    for pattern in _SENSITIVE_PATTERNS:
        assert pattern.search(clean) is None, f"pattern false-positived on clean sample: {pattern.pattern!r}"


@pytest.mark.sabotage_check
@pytest.mark.unit
def test_h_reader_passes_in_subprocess_tree_without_artifacts(tmp_path: Path) -> None:
    """Run the H reader against a tree that contains only tracked fixtures (no
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
    # The formerly ignored-artifact-reading tests must actually RUN and pass, not
    # be skipped or silently absent on a clean checkout.
    for node in _REQUIRED_RUNNING_TESTS:
        assert node in combined, f"required H reader test did not appear in the run:\n{combined}"
        assert f"{node} PASSED" in combined, f"required H reader test did not pass:\n{combined}"
    # The guarded optional provenance test must be reported SKIPPED, not passed:
    # absence of ignored evidence must never read as LOCAL_PASS.
    assert "1 skipped" in combined, f"guarded optional H test was not reported skipped:\n{combined}"
    assert _GUARDED_OPTIONAL_TEST in combined, f"guarded optional H test missing from the run:\n{combined}"
    assert f"{_GUARDED_OPTIONAL_TEST} SKIPPED" in combined, (
        f"guarded optional H test was not reported SKIPPED explicitly:\n{combined}"
    )


@pytest.mark.sabotage_check
@pytest.mark.unit
def test_h_reader_keeps_required_assertion_tokens() -> None:
    """Pin the exact assertion tokens the H reader must keep.

    Guards against a future paired weakening of a reader assertion plus a fixture
    edit: both the reader source and the tracked fixtures must still carry every
    required token.
    """
    reader_text = READER.read_text(encoding="utf-8")
    fixture_text = "\n".join(path.read_text(encoding="utf-8") for path in _fixture_files())
    assert "HydrateSongInput(song_id: int, ...)" in fixture_text
    assert "No schema or marker semantics are invented" in fixture_text
    for token in _REQUIRED_ASSERTION_TOKENS:
        assert token in reader_text, f"required H reader assertion token missing from reader: {token!r}"
        assert token in fixture_text, f"required H reader assertion token missing from fixtures: {token!r}"
