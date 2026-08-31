"""Regression tests for the frozen head/bin/discrimination invariants.

Locks the non-negotiable contracts from ``_contracts_part_*.md`` and the Part-A
ledger so they cannot silently regress:

* ``act[1]`` is the class-1 probability and is the score used everywhere
  (``act[0]`` is never the score);
* the bin index is frozen at ``np.minimum((h_scores * 10).astype(np.int32), 9)``
  (10 bins, score 1.0 -> bin 9);
* ``disc_general`` averages only the non-zero valid components (zero components
  are excluded);
* no ``disc_album`` key / SELECT / upsert / schema field exists anywhere in the
  research codebase (docstring/comment mentions are tolerated, code is not).
"""

from __future__ import annotations

import ast
import tokenize
from pathlib import Path

import numpy as np
import pytest

from scripts.embedding_research.common.stratify import _score_to_decile
from scripts.embedding_research.db import songs as db_songs
from scripts.embedding_research.similarity import compute_retrieval_metrics

_RESEARCH_DIR = Path(__file__).resolve().parents[1]


# ── act[1] is the class-1 score ────────────────────────────────────────────────


def test_load_song_head_scores_uses_act1_not_act0(monkeypatch) -> None:
    """db.songs.load_song_head_scores takes act[1] (class-1) as the score."""
    import scripts.embedding_research.cache.flat_heads as fh_mod

    monkeypatch.setattr(fh_mod, "list_all_heads", lambda _backbone: ["mood"])

    def _load_bulk(_backbone, _head, _strategy, _pathway, _sids):
        # act = [p0, p1]; act[1] is the positive-class score.
        return {
            "s1": np.array([0.10, 0.90]),
            "s2": np.array([0.70, 0.30]),
        }

    monkeypatch.setattr(fh_mod, "load_bulk", _load_bulk)

    matrix, heads = db_songs.load_song_head_scores("effnet", ["s1", "s2"])

    assert heads == ["mood"]
    np.testing.assert_allclose(matrix[:, 0], [0.90, 0.30], atol=1e-6)
    np.testing.assert_allclose(matrix[0, 0], 0.90, atol=1e-6)
    np.testing.assert_allclose(matrix[1, 0], 0.30, atol=1e-6)


# ── Frozen bin-index formula ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "score,expected_bin",
    [
        (0.0, 0),
        (0.05, 0),
        (0.09, 0),
        (0.10, 1),
        (0.199, 1),
        (0.5, 5),
        (0.899, 8),
        (0.90, 9),
        (0.999, 9),
        (1.0, 9),  # score 1.0 must clamp to bin 9, never 10
    ],
)
def test_bin_index_scalar_formula_frozen(score: float, expected_bin: int) -> None:
    """_score_to_decile is truncate-then-clamp: max(0, min(int(score*10), 9))."""
    assert _score_to_decile(score) == max(0, min(int(score * 10), 9)) == expected_bin


def test_bin_index_frozen_numpy_formula() -> None:
    """The frozen vectorized formula np.minimum((h*10).astype(int32), 9) clamps to <=9."""
    h_scores = np.array([0.0, 0.1, 0.5, 0.9, 1.0, 1.5], dtype=np.float32)
    bins = np.minimum((h_scores * 10).astype(np.int32), 9)
    assert bins.dtype == np.int32
    assert bins.max() <= 9
    assert bins[-2] == 9  # score 1.0 -> bin 9 (clamped from 10)
    assert bins[-1] == 9  # 1.5 also clamps to 9


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
