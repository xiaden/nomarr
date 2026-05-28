"""Unit tests for scripts/embedding_research/similarity.py.

All test data is synthetic numpy arrays built inline.
No ONNX models, no audio files, no filesystem I/O, no network.
Run from project root: pytest scripts/embedding_research/tests/
"""

from __future__ import annotations

import logging

import numpy as np

from scripts.embedding_research.similarity import (
    _rankings_from_sim,
    compute_retrieval_metrics,
    cosine_matrix,
    l2_normalise,
)
from scripts.embedding_research.vector_types import RawTensor

# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------


def _block_sim(
    within: float = 0.8,
    cross: float = 0.2,
    n: int = 4,
) -> np.ndarray:
    """4x4 float32 sim matrix with two equal-size groups (diagonal=1)."""
    half = n // 2
    m = np.full((n, n), cross, dtype=np.float32)
    m[:half, :half] = within
    m[half:, half:] = within
    np.fill_diagonal(m, 1.0)
    return m


# ---------------------------------------------------------------------------
# Test 1: disc_artist — perfect separation gives exactly 1.0
# ---------------------------------------------------------------------------


def test_disc_artist_positive():
    """4 songs, artists A A B B, within-sim=1, cross-sim=0 → disc_artist==1.0."""
    sim = np.array(
        [
            [1.0, 1.0, 0.0, 0.0],
            [1.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 1.0],
            [0.0, 0.0, 1.0, 1.0],
        ],
        dtype=np.float32,
    )
    labels = ["A", "A", "B", "B"]
    m = compute_retrieval_metrics(sim, labels, k=2)
    assert m["disc_artist"] == 1.0


# ---------------------------------------------------------------------------
# Test 2: disc_genre — nonzero when genres separate groups
# ---------------------------------------------------------------------------


def test_disc_genre_nonzero():
    """2 genres with separating sim matrix → disc_genre > 0."""
    sim = _block_sim(within=0.9, cross=0.1)
    labels = ["A", "A", "B", "B"]
    genres = ["G1", "G1", "G2", "G2"]
    m = compute_retrieval_metrics(sim, labels, k=2, genres=genres)
    assert m["disc_genre"] > 0.0


# ---------------------------------------------------------------------------
# Test 3: disc_genre — None input → 0.0, no exception
# ---------------------------------------------------------------------------


def test_disc_genre_none_input():
    """genres=None → disc_genre == 0.0 with no exception raised."""
    sim = _block_sim()
    labels = ["A", "A", "B", "B"]
    m = compute_retrieval_metrics(sim, labels, k=2, genres=None)
    assert m["disc_genre"] == 0.0


# ---------------------------------------------------------------------------
# Test 4: disc_head — two bin groups produce non-zero discrimination
# ---------------------------------------------------------------------------


def test_disc_head_score_bins():
    """head_scores (1,4), bins [0,0,8,8] with separating sim → disc_head != 0.

    Scores [0.05, 0.05, 0.85, 0.85]:
      bin = min(int(score*10), 9) → [0, 0, 8, 8]
    Two songs per bin allows within-group vs cross-group discrimination.
    """
    sim = _block_sim(within=0.9, cross=0.1)
    labels = ["A", "A", "B", "B"]
    head_scores = [[0.05, 0.05, 0.85, 0.85]]  # shape (1, 4): n_heads=1, n=4
    m = compute_retrieval_metrics(sim, labels, k=2, head_scores=head_scores)
    assert m["disc_head"] != 0.0


# ---------------------------------------------------------------------------
# Test 5: disc_head — constant bin → skipped → 0.0
# ---------------------------------------------------------------------------


def test_disc_head_constant_bin_skipped():
    """All head scores 0.5 → bin 5 for every song → disc_head == 0.0."""
    sim = _block_sim()
    labels = ["A", "A", "B", "B"]
    # 0.5 * 10 = 5.0 → int32 = 5 → min(5, 9) = 5 for all four songs
    head_scores = [[0.5, 0.5, 0.5, 0.5]]
    m = compute_retrieval_metrics(sim, labels, k=2, head_scores=head_scores)
    assert m["disc_head"] == 0.0


# ---------------------------------------------------------------------------
# Test 6: disc_general — mean of all three non-zero components exactly
# ---------------------------------------------------------------------------


def test_disc_general_all_three_components():
    """disc_artist, disc_genre, disc_head all non-zero → disc_general == mean of all three."""
    sim = _block_sim(within=0.8, cross=0.2)
    labels = ["A", "A", "B", "B"]
    genres = ["G1", "G1", "G2", "G2"]
    head_scores = [[0.1, 0.1, 0.9, 0.9]]  # bins [1, 1, 9, 9]
    m = compute_retrieval_metrics(sim, labels, k=2, genres=genres, head_scores=head_scores)
    assert m["disc_artist"] != 0.0
    assert m["disc_genre"] != 0.0
    assert m["disc_head"] != 0.0
    expected = float(np.mean([m["disc_artist"], m["disc_genre"], m["disc_head"]]))
    assert abs(m["disc_general"] - expected) < 1e-6


# ---------------------------------------------------------------------------
# Test 7: disc_general — zero component triggers WARNING, correct mean
# ---------------------------------------------------------------------------


def test_disc_general_zero_component_warning(caplog):
    """genres=None → disc_genre excluded; disc_general==mean(artist,head); INFO (not WARNING) logged."""
    sim = _block_sim(within=0.8, cross=0.2)
    labels = ["A", "A", "B", "B"]
    head_scores = [[0.1, 0.1, 0.9, 0.9]]  # bins [1, 1, 9, 9] → disc_head != 0
    with caplog.at_level(logging.INFO, logger="scripts.embedding_research.similarity"):
        m = compute_retrieval_metrics(sim, labels, k=2, genres=None, head_scores=head_scores)
    assert m["disc_genre"] == 0.0
    assert m["disc_artist"] != 0.0
    assert m["disc_head"] != 0.0
    expected = (m["disc_artist"] + m["disc_head"]) / 2.0
    assert abs(m["disc_general"] - expected) < 1e-6
    # genres=None → INFO-level message (no genre data provided, not a suspicious zero)
    disc_genre_msgs = [(r.levelno, r.message) for r in caplog.records if "disc_genre" in r.message]
    assert disc_genre_msgs, "expected a disc_genre log entry"
    assert all(lvl == logging.INFO for lvl, _ in disc_genre_msgs), (
        "disc_genre=0 with no genre data must log INFO, not WARNING"
    )


# ---------------------------------------------------------------------------
# Test 8: disc_head log levels — None and empty-list → INFO; constant bin → WARNING
# ---------------------------------------------------------------------------


def test_disc_head_none_logs_info(caplog):
    """head_scores=None → disc_head=0 logged at INFO, not WARNING."""
    sim = _block_sim()
    labels = ["A", "A", "B", "B"]
    with caplog.at_level(logging.INFO, logger="scripts.embedding_research.similarity"):
        m = compute_retrieval_metrics(sim, labels, k=2, head_scores=None)
    assert m["disc_head"] == 0.0
    head_msgs = [(r.levelno, r.message) for r in caplog.records if "disc_head" in r.message]
    assert head_msgs, "expected a disc_head log entry"
    assert all(lvl == logging.INFO for lvl, _ in head_msgs), "head_scores=None must log INFO, not WARNING"


def test_disc_head_empty_list_logs_info(caplog):
    """head_scores=[] (classify not run / no heads) → disc_head=0 logged at INFO, not WARNING."""
    sim = _block_sim()
    labels = ["A", "A", "B", "B"]
    with caplog.at_level(logging.INFO, logger="scripts.embedding_research.similarity"):
        m = compute_retrieval_metrics(sim, labels, k=2, head_scores=[])
    assert m["disc_head"] == 0.0
    head_msgs = [(r.levelno, r.message) for r in caplog.records if "disc_head" in r.message]
    assert head_msgs, "expected a disc_head log entry"
    assert all(lvl == logging.INFO for lvl, _ in head_msgs), "head_scores=[] must log INFO, not WARNING"


def test_disc_head_constant_bin_logs_warning(caplog):
    """Scores provided but all in same bin → disc_head=0 logged at WARNING."""
    sim = _block_sim()
    labels = ["A", "A", "B", "B"]
    head_scores = [[0.5, 0.5, 0.5, 0.5]]  # all bin 5
    with caplog.at_level(logging.INFO, logger="scripts.embedding_research.similarity"):
        m = compute_retrieval_metrics(sim, labels, k=2, head_scores=head_scores)
    assert m["disc_head"] == 0.0
    head_msgs = [(r.levelno, r.message) for r in caplog.records if "disc_head" in r.message]
    assert head_msgs, "expected a disc_head log entry"
    assert all(lvl == logging.WARNING for lvl, _ in head_msgs), "constant-bin head scores must log WARNING, not INFO"


# ---------------------------------------------------------------------------
# Test 9 (was 8): bin_idx formula — boundary and edge values
# ---------------------------------------------------------------------------


def test_bin_idx_formula():
    """Verify bin = min(int(score * 10), 9) for boundary scores."""
    scores = np.array([0.0, 0.09, 0.10, 0.99, 1.0], dtype=np.float64)
    bins = np.minimum((scores * 10).astype(np.int32), 9)
    assert list(bins) == [0, 0, 1, 9, 9]


# ---------------------------------------------------------------------------
# Test 9: head_scores auto-transpose — (n, n_heads) same result as (n_heads, n)
# ---------------------------------------------------------------------------


def test_head_scores_shape_transposed():
    """(n_heads, n) and (n, n_heads) layouts produce identical disc_head and precision."""
    sim = _block_sim(within=0.9, cross=0.1)
    labels = ["A", "A", "B", "B"]
    # n=4, n_heads=2 (distinct sizes avoid the ambiguous n==n_heads case)
    # (2, 4): shape[1]==n=4 → treated as (n_heads, n)
    head_scores_nh = [[0.1, 0.1, 0.9, 0.9], [0.2, 0.2, 0.8, 0.8]]
    # (4, 2): shape[0]==n=4 → transposed to (2, 4)
    head_scores_hn = [[0.1, 0.2], [0.1, 0.2], [0.9, 0.8], [0.9, 0.8]]
    m_nh = compute_retrieval_metrics(sim, labels, k=2, head_scores=head_scores_nh)
    m_hn = compute_retrieval_metrics(sim, labels, k=2, head_scores=head_scores_hn)
    assert abs(m_nh["disc_head"] - m_hn["disc_head"]) < 1e-7
    assert abs(m_nh["precision_k_head_mean"] - m_hn["precision_k_head_mean"]) < 1e-7


# ---------------------------------------------------------------------------
# Test 10: precision_k_genre — in valid range, not None
# ---------------------------------------------------------------------------


def test_precision_k_genre():
    """4 songs, 2 genres, k=2 → precision_k_genre in [0.0, 1.0]."""
    sim = _block_sim(within=0.9, cross=0.1)
    labels = ["A", "A", "B", "B"]
    genres = ["G1", "G1", "G2", "G2"]
    m = compute_retrieval_metrics(sim, labels, k=2, genres=genres)
    assert m["precision_k_genre"] is not None
    assert 0.0 <= m["precision_k_genre"] <= 1.0


# ---------------------------------------------------------------------------
# Test 11: _rankings_from_sim — self-index never in results
# ---------------------------------------------------------------------------


def test_rankings_no_self_in_results():
    """For every song i, index i must not appear in rankings[i]."""
    rng = np.random.RandomState(0)
    raw = rng.randn(6, 8).astype(np.float32)
    sim = cosine_matrix(RawTensor(raw))
    rankings = _rankings_from_sim(sim)
    n = sim.shape[0]
    for i in range(n):
        assert i not in rankings[i], f"self-index {i} found in rankings[{i}]"


# ---------------------------------------------------------------------------
# Test 12: cosine_matrix — diagonal is 1.0 for unit vectors
# ---------------------------------------------------------------------------


def test_cosine_matrix_self_similarity():
    """cosine_matrix of identity (unit) vectors → all diagonal entries == 1.0."""
    vecs = RawTensor(np.eye(4, dtype=np.float32))
    mat = cosine_matrix(vecs)
    np.testing.assert_allclose(np.diag(mat), 1.0, atol=1e-6)


# ---------------------------------------------------------------------------
# Test 13: l2_normalise — all output rows have unit L2 norm
# ---------------------------------------------------------------------------


def test_l2_normalise():
    """l2_normalise output rows all satisfy ||v||_2 == 1.0."""
    rng = np.random.RandomState(42)
    raw = rng.randn(5, 8).astype(np.float32)
    normed = l2_normalise(RawTensor(raw))
    norms = np.linalg.norm(np.array(normed), axis=1)
    np.testing.assert_allclose(norms, 1.0, atol=1e-6)
