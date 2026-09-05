"""Regression tests for the retained discrimination invariants.

Locks the non-negotiable contracts that remain live after the corrective-pass
hard cut so they cannot silently regress:

* ``disc_general`` averages only the non-zero valid components (zero components
  are excluded);
* no ``disc_album`` key / SELECT / upsert / schema field exists anywhere in the
  research codebase (docstring/comment mentions are tolerated, code is not).

(The former ``act[1]``/bin-index invariants live under the retained catalog
head-analysis surface; the deleted ``db/stratify.py`` decile formula is
historical-only and is no longer pinned here.)
"""

from __future__ import annotations

import ast
import tokenize
from pathlib import Path

import numpy as np

from scripts.embedding_research.similarity import compute_retrieval_metrics

_RESEARCH_DIR = Path(__file__).resolve().parents[1]


# ── disc_general zero-component exclusion ──────────────────────────────────────


def _block_sim(within: float = 0.8, cross: float = 0.2, n: int = 4) -> np.ndarray:
    half = n // 2
    m = np.full((n, n), cross, dtype=np.float32)
    m[:half, :half] = within
    m[half:, half:] = within
    np.fill_diagonal(m, 1.0)
    return m


def test_disc_general_excludes_zero_components() -> None:
    """disc_general averages only the non-zero disc components.

    All songs share one artist -> disc_artist is 0 and is excluded; only
    disc_genre and disc_head are averaged.
    """
    sim = _block_sim(within=0.8, cross=0.2)
    labels = ["A", "A", "A", "A"]  # single artist -> disc_artist == 0
    genres = ["G1", "G1", "G2", "G2"]
    head_scores = [[0.1, 0.1, 0.9, 0.9]]

    m = compute_retrieval_metrics(sim, labels, k=2, genres=genres, head_scores=head_scores)

    assert m["disc_artist"] == 0.0
    assert m["disc_genre"] != 0.0
    assert m["disc_head"] != 0.0
    expected = float(np.mean([m["disc_genre"], m["disc_head"]]))
    assert abs(m["disc_general"] - expected) < 1e-6
    # the zero artist component must NOT drag the mean down
    assert m["disc_general"] > m["disc_artist"]


def test_disc_general_all_zero_is_zero() -> None:
    """When every component is zero, disc_general is 0.0 (no empty mean)."""
    sim = _block_sim(within=0.8, cross=0.2)
    labels = ["A", "A", "A", "A"]  # single artist -> disc_artist == 0
    m = compute_retrieval_metrics(sim, labels, k=2, genres=None, head_scores=None)
    assert m["disc_artist"] == 0.0
    assert m["disc_genre"] == 0.0
    assert m["disc_head"] == 0.0
    assert m["disc_general"] == 0.0


# ── no disc_album anywhere ─────────────────────────────────────────────────────


def _real_code_references_disc_album(path: Path) -> list[tuple[int, str]]:
    """Return (line_no, line) where ``disc_album`` appears outside comments/docstrings.

    Docstring and comment mentions are tolerated (they describe a legacy metric
    that must NOT be added); any real key/column/SELECT/upsert reference is a
    violation.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))

    # Collect the starting line of every module/class/function docstring.
    docstring_lines: set[int] = set()
    for node in [tree, *ast.walk(tree)]:
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", [])
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            docstring_lines.add(body[0].lineno)

    violations: list[tuple[int, str]] = []
    with path.open("r", encoding="utf-8") as fh:
        for tok in tokenize.generate_tokens(fh.readline):
            if tok.type in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
                continue
            if "disc_album" in tok.string:
                if tok.type == tokenize.STRING and tok.start[0] in docstring_lines:
                    continue
                violations.append((tok.start[0], tok.line.rstrip()))
    return violations


def test_no_disc_album_key_select_or_upsert_anywhere() -> None:
    """The research codebase contains no disc_album key/SELECT/upsert/schema field.

    Only docstring/comment mentions are allowed; a real data key, DB column,
    SELECT or upsert reference must never be added.
    """
    found: dict[str, list[tuple[int, str]]] = {}
    for py in sorted(_RESEARCH_DIR.rglob("*.py")):
        if "__pycache__" in py.parts or "tests" in py.parts:
            # The guard inspects the research codebase, not the test suite itself
            # (which legitimately references "disc_album" in this very test).
            continue
        try:
            bad = _real_code_references_disc_album(py)
        except (SyntaxError, ValueError):
            continue  # non-module scripts may not be parseable as a module; skip
        if bad:
            found[str(py.relative_to(_RESEARCH_DIR))] = bad
    assert not found, f"disc_album used as real code in: {found}"
