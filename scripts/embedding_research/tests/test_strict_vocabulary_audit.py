"""Strict whole-tree vocabulary audit for the geometry-era research package.

The geometry pipeline has a single vocabulary: geometry identities, committed
observations, streams, masks, heads, geometry analysis, and the seven phases.
Retired ownership/format names must not survive anywhere in the research tree —
not in executable code, strings, docstrings, comments, tests, fixtures, docs,
generated evidence, or configuration. This audit asserts the strong form of
that invariant: ZERO case-insensitive occurrences anywhere.

The audited tokens are assembled from fragments at runtime so that this module
never itself contains the substrings it forbids (otherwise the audit would be
its own first violation).
"""

from __future__ import annotations

from pathlib import Path

import pytest

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]

# Directories that are tool caches / compiled output, not authored research text.
_SKIP_DIR_NAMES = frozenset({"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"})

# Binary or non-authored payload suffixes that cannot carry meaningful text.
_SKIP_SUFFIXES = frozenset(
    {
        ".pyc",
        ".pyo",
        ".db",
        ".duckdb",
        ".npy",
        ".npz",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".pdf",
        ".whl",
        ".so",
        ".dylib",
        ".dll",
        ".bin",
    }
)


def _forbidden_tokens() -> tuple[str, ...]:
    """Retired vocabulary roots, assembled from fragments (never literal here)."""
    return (
        "cat" + "alog",
        "search" + "_" + "view",
        "search" + " " + "view",
        "search" + "-" + "view",
        "current" + "_" + "selector",
        "current" + " " + "selector",
        "current" + "-" + "selector",
        "latest" + "_" + "selector",
        "latest" + " " + "selector",
        "latest" + "-" + "selector",
        "leg" + "acy",
        "ali" + "as",
        "fall" + "back",
    )


def _iter_text_files() -> list[Path]:
    files: list[Path] = []
    for path in _PACKAGE_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.suffix.lower() in _SKIP_SUFFIXES:
            continue
        files.append(path)
    return sorted(files)


def _scan(text: str, tokens: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    return [token for token in tokens if token in lowered]


def test_research_tree_has_zero_retired_vocabulary() -> None:
    tokens = _forbidden_tokens()
    violations: list[str] = []
    for path in _iter_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        found = _scan(text, tokens)
        if found:
            rel = path.relative_to(_PACKAGE_ROOT)
            violations.append(f"{rel}: {sorted(set(found))}")
    assert not violations, "retired vocabulary found in the research tree:\n" + "\n".join(violations)


def test_audit_itself_contains_no_forbidden_substring() -> None:
    """The audit must not smuggle the tokens it forbids (fragment assembly works)."""
    tokens = _forbidden_tokens()
    source = Path(__file__).read_text(encoding="utf-8").lower()
    leaked = [token for token in tokens if token in source]
    assert not leaked, f"audit implementation leaks forbidden substrings: {leaked}"


@pytest.mark.parametrize("token", _forbidden_tokens())
def test_audit_token_is_nonempty(token: str) -> None:
    assert token
