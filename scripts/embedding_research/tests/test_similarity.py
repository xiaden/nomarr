"""Unit tests for scripts/embedding_research/similarity.py.

All test data is synthetic numpy arrays built inline.
No ONNX models, no audio files, no filesystem I/O, no network.
Run from project root: pytest scripts/embedding_research/tests/
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from scripts.embedding_research.similarity import (
    DISC_HEAD_GAP,
    DISC_HEAD_WINDOW,
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
# Test 4: disc_head — separated score groups produce non-zero discrimination
# ---------------------------------------------------------------------------


def test_disc_head_score_bins():
    """head_scores (1,4), scores [0.05, 0.05, 0.85, 0.85] → wide score gap → in-set and out-set both non-empty → disc_head != 0."""
    sim = _block_sim(within=0.9, cross=0.1)
    labels = ["A", "A", "B", "B"]
    head_scores = [[0.05, 0.05, 0.85, 0.85]]  # shape (1, 4): n_heads=1, n=4
    m = compute_retrieval_metrics(sim, labels, k=2, head_scores=head_scores)
    assert m["disc_head"] != 0.0


# ---------------------------------------------------------------------------
# Test 5: disc_head — identical scores → skipped → 0.0
# ---------------------------------------------------------------------------


def test_disc_head_constant_bin_skipped():
    """All head scores 0.5 → every song within window of every other → out-set empty for all → disc_head == 0.0."""
    sim = _block_sim()
    labels = ["A", "A", "B", "B"]
    # scores 0.5: |0.5 - 0.5| = 0.0 <= DISC_HEAD_WINDOW, so all songs are in-set; out-set is empty
    head_scores = [[0.5, 0.5, 0.5, 0.5]]
    m = compute_retrieval_metrics(sim, labels, k=2, head_scores=head_scores)
    assert m["disc_head"] == 0.0


def test_disc_head_window_basic():
    """5 songs with spread scores: constants are exported and the window metric produces a non-zero value."""
    assert DISC_HEAD_WINDOW == 0.1
    assert DISC_HEAD_GAP == 0.1

    n = 5
    sim = np.eye(n, dtype=np.float32)
    sim[0, 1] = sim[1, 0] = 0.8
    sim[3, 4] = sim[4, 3] = 0.8
    sim[0, 4] = sim[4, 0] = 0.1
    scores = [0.0, 0.1, 0.5, 0.9, 1.0]
    head_scores = [scores]
    labels = ["A"] * n

    m = compute_retrieval_metrics(sim, labels, k=4, head_scores=head_scores)

    assert m["disc_head"] != 0.0


def test_disc_head_all_same_score():
    """All songs share score 0.5: every song's window covers all others, out-set empty → disc_head == 0.0."""
    n = 5
    sim = _block_sim(within=0.8, cross=0.2, n=n)
    head_scores = [[0.5] * n]
    labels = ["A"] * n

    m = compute_retrieval_metrics(sim, labels, k=4, head_scores=head_scores)

    assert m["disc_head"] == 0.0


# ---------------------------------------------------------------------------
# Test 6: disc_general — mean of all three non-zero components exactly
# ---------------------------------------------------------------------------


def test_disc_general_all_three_components():
    """disc_artist, disc_genre, disc_head all non-zero → disc_general == mean of all three."""
    sim = _block_sim(within=0.8, cross=0.2)
    labels = ["A", "A", "B", "B"]
    genres = ["G1", "G1", "G2", "G2"]
    head_scores = [[0.1, 0.1, 0.9, 0.9]]  # wide score split with valid in/out windows
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
    head_scores = [[0.1, 0.1, 0.9, 0.9]]  # wide score split → disc_head != 0
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
# Test 8: disc_head log levels — None and empty-list → INFO; same-score window → WARNING
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
    """Scores provided but every song shares the same score window → disc_head=0 logged at WARNING."""
    sim = _block_sim()
    labels = ["A", "A", "B", "B"]
    head_scores = [[0.5, 0.5, 0.5, 0.5]]  # all score 0.5 → out-set empty for every song
    with caplog.at_level(logging.INFO, logger="scripts.embedding_research.similarity"):
        m = compute_retrieval_metrics(sim, labels, k=2, head_scores=head_scores)
    assert m["disc_head"] == 0.0
    head_msgs = [(r.levelno, r.message) for r in caplog.records if "disc_head" in r.message]
    assert head_msgs, "expected a disc_head log entry"
    assert all(lvl == logging.WARNING for lvl, _ in head_msgs), "same-score head scores must log WARNING, not INFO"


# ---------------------------------------------------------------------------
# Test 9: head_scores auto-transpose — (n, n_heads) same result as (n_heads, n)
# ---------------------------------------------------------------------------


def test_head_scores_shape_transposed():
    """(n_heads, n) and (n, n_heads) layouts produce identical disc_head and head MAP."""
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
    assert abs(m_nh["map_k_head"] - m_hn["map_k_head"]) < 1e-7


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


# ---------------------------------------------------------------------------
# Test 14: disc_head — isolated scores leave no in-set neighbors
# ---------------------------------------------------------------------------


def test_disc_head_score_isolation_no_inset_neighbors():
    """Two songs with scores [0.0, 1.0]: after self-exclusion, each song has no in-set neighbor (distance > DISC_HEAD_WINDOW) → in_mask all-False → all songs skipped → disc_head == 0.0."""
    sim = np.eye(2, dtype=np.float32)
    labels = ["A", "B"]
    head_scores = [[0.0, 1.0]]

    m = compute_retrieval_metrics(sim, labels, k=1, head_scores=head_scores)

    assert m["disc_head"] == 0.0


# ---------------------------------------------------------------------------
# Test 15: disc_head — single-song corpus skips cleanly
# ---------------------------------------------------------------------------


def test_disc_head_single_song_corpus():
    """n=1 corpus: single song has no neighbors after self-exclusion → disc_head == 0.0 and the Phase 4 payload keys are present."""
    sim = np.eye(1, dtype=np.float32)
    labels = ["A"]
    head_scores = [[0.5]]

    m = compute_retrieval_metrics(sim, labels, head_scores=head_scores)

    assert m["disc_head"] == 0.0
    assert set(m) == {
        "ap_k_genre",
        "ap_k_head",
        "disc_artist",
        "disc_general",
        "disc_genre",
        "disc_head",
        "disc_score",
        "map_k_artist",
        "map_k_genre",
        "map_k_head",
        "mean_cross",
        "mean_cross_artist",
        "mean_cross_genre",
        "mean_cross_head",
        "mean_within",
        "mean_within_artist",
        "mean_within_genre",
        "mean_within_head",
        "mrr",
        "mrr_genre",
        "mrr_head",
        "ndcg_k_artist",
        "ndcg_k_genre",
        "ndcg_k_head",
        "per_head_corr",
        "per_song",
        "precision_k_genre",
        "recall_k_artist",
        "recall_k_genre",
        "recall_k_head",
        "var_cross_artist",
        "var_cross_genre",
        "var_cross_head",
        "var_within_artist",
        "var_within_genre",
        "var_within_head",
    }


# ---------------------------------------------------------------------------
# Phase 5 additions: retrieval-family and within/cross coverage
# ---------------------------------------------------------------------------


def test_map_k_genre_nonzero():
    """Balanced two-genre corpus with block similarity should produce non-zero genre retrieval metrics."""
    sim = _block_sim(within=0.9, cross=0.1)
    labels = ["A", "A", "B", "B"]
    genres = ["G1", "G1", "G2", "G2"]

    m = compute_retrieval_metrics(sim, labels, k=2, genres=genres)

    assert m["map_k_genre"] > 0
    assert m["mrr_genre"] > 0
    assert m["ndcg_k_genre"] > 0


def test_map_k_genre_none_when_no_genres():
    """Missing genre labels should disable genre retrieval metrics cleanly."""
    sim = _block_sim(within=0.9, cross=0.1)
    labels = ["A", "A", "B", "B"]

    m = compute_retrieval_metrics(sim, labels, k=2, genres=None)

    assert m["map_k_genre"] is None


def test_map_k_head_nonzero():
    """Separated head score groups should produce a positive head MAP@k value."""
    sim = _block_sim(within=0.9, cross=0.1)
    labels = ["A", "A", "B", "B"]
    head_scores = [[0.1, 0.1, 0.9, 0.9]]

    m = compute_retrieval_metrics(sim, labels, k=2, head_scores=head_scores)

    assert m["map_k_head"] is not None
    assert m["map_k_head"] > 0


def test_map_k_head_none_when_no_head_scores():
    """Missing head scores should leave head retrieval metrics unset."""
    sim = _block_sim(within=0.9, cross=0.1)
    labels = ["A", "A", "B", "B"]

    m = compute_retrieval_metrics(sim, labels, k=2, head_scores=None)

    assert m["map_k_head"] is None


def test_var_within_cross_artist_nonneg():
    """Artist within/cross variance metrics should be non-negative and preserve the back-compat alias."""
    sim = _block_sim(within=0.9, cross=0.1)
    labels = ["A", "A", "B", "B"]

    m = compute_retrieval_metrics(sim, labels, k=2)

    assert m["var_within_artist"] >= 0
    assert m["var_cross_artist"] >= 0
    assert m["mean_within_artist"] == m["mean_within"]


def test_var_within_cross_genre_nonneg():
    """Genre within/cross variance metrics should be populated and non-negative when genre tags are present."""
    sim = _block_sim(within=0.9, cross=0.1)
    labels = ["A", "A", "B", "B"]
    genres = ["G1", "G1", "G2", "G2"]

    m = compute_retrieval_metrics(sim, labels, k=2, genres=genres)

    assert m["var_within_genre"] >= 0
    assert m["var_cross_genre"] >= 0


def test_var_genre_none_when_no_genres():
    """Genre within/cross metrics should be None when no genre labels are provided."""
    sim = _block_sim(within=0.9, cross=0.1)
    labels = ["A", "A", "B", "B"]

    m = compute_retrieval_metrics(sim, labels, k=2, genres=None)

    assert m["mean_within_genre"] is None
    assert m["var_within_genre"] is None


def test_head_within_cross_present_when_head_scores():
    """Separated head scores should populate all head within/cross summary metrics."""
    sim = _block_sim(within=0.9, cross=0.1)
    labels = ["A", "A", "B", "B"]
    head_scores = [[0.1, 0.1, 0.9, 0.9]]

    m = compute_retrieval_metrics(sim, labels, k=2, head_scores=head_scores)

    assert m["mean_within_head"] is not None
    assert m["var_within_head"] is not None
    assert m["mean_cross_head"] is not None
    assert m["var_cross_head"] is not None


def test_head_within_cross_none_when_no_head_scores():
    """Missing head scores should leave head within/cross summaries unset."""
    sim = _block_sim(within=0.9, cross=0.1)
    labels = ["A", "A", "B", "B"]

    m = compute_retrieval_metrics(sim, labels, k=2, head_scores=None)

    assert m["mean_within_head"] is None
    assert m["var_within_head"] is None
    assert m["mean_cross_head"] is None
    assert m["var_cross_head"] is None


# ---------------------------------------------------------------------------
# Gap coverage: ndcg_k_genre None, ndcg_k_head nonzero, recall_k_genre/head,
# ap_k_genre/head list lengths, per_song mrr_genre list length
# ---------------------------------------------------------------------------


def test_ndcg_k_genre_is_none_when_no_genres():
    """ndcg_k_genre must be None when genres=None (mirrors map_k_genre/mrr_genre behaviour)."""
    sim = _block_sim(within=0.9, cross=0.1)
    labels = ["A", "A", "B", "B"]

    m = compute_retrieval_metrics(sim, labels, k=2, genres=None)

    assert m["ndcg_k_genre"] is None


def test_ndcg_k_head_nonzero_when_head_scores_present():
    """Separated head-score groups must produce a non-None, positive ndcg_k_head."""
    sim = _block_sim(within=0.9, cross=0.1)
    labels = ["A", "A", "B", "B"]
    head_scores = [[0.1, 0.1, 0.9, 0.9]]

    m = compute_retrieval_metrics(sim, labels, k=2, head_scores=head_scores)

    assert m["ndcg_k_head"] is not None
    assert m["ndcg_k_head"] > 0


def test_recall_k_genre_exact_value_for_perfect_block_sim():
    """Two-genre block-sim: every song's top-1 neighbour is same-genre → recall_k_genre == 1.0."""
    sim = _block_sim(within=0.9, cross=0.1)
    labels = ["A", "A", "B", "B"]
    genres = ["G1", "G1", "G2", "G2"]

    m = compute_retrieval_metrics(sim, labels, k=2, genres=genres)

    # With within=0.9, cross=0.1, k=2, each song's genre_rel_set has size 1.
    # The single same-genre song always ranks first → recall == 1/min(2,1) == 1.0.
    assert m["recall_k_genre"] == pytest.approx(1.0)


def test_recall_k_genre_is_none_when_no_genres():
    """recall_k_genre must be None when genres=None."""
    sim = _block_sim(within=0.9, cross=0.1)
    labels = ["A", "A", "B", "B"]

    m = compute_retrieval_metrics(sim, labels, k=2, genres=None)

    assert m["recall_k_genre"] is None


def test_recall_k_head_exact_value_for_separated_scores():
    """Separated head scores: each song's single in-window peer ranks first → recall_k_head == 1.0."""
    sim = _block_sim(within=0.9, cross=0.1)
    labels = ["A", "A", "B", "B"]
    # Scores [0.1, 0.1, 0.9, 0.9]: within-window peers are {0↔1} and {2↔3}.
    head_scores = [[0.1, 0.1, 0.9, 0.9]]

    m = compute_retrieval_metrics(sim, labels, k=2, head_scores=head_scores)

    assert m["recall_k_head"] is not None
    assert m["recall_k_head"] == pytest.approx(1.0)


def test_ap_k_genre_list_length_matches_n_when_genres_present():
    """Top-level ap_k_genre is a per-song list of length n when genre tags cover all songs."""
    sim = _block_sim(within=0.9, cross=0.1)
    labels = ["A", "A", "B", "B"]
    genres = ["G1", "G1", "G2", "G2"]
    n = 4

    m = compute_retrieval_metrics(sim, labels, k=2, genres=genres)

    assert isinstance(m["ap_k_genre"], list)
    assert len(m["ap_k_genre"]) == n


def test_ap_k_head_list_length_matches_n_when_head_scores_present():
    """Top-level ap_k_head is a per-song list of length n when head_scores are provided."""
    sim = _block_sim(within=0.9, cross=0.1)
    labels = ["A", "A", "B", "B"]
    head_scores = [[0.1, 0.1, 0.9, 0.9]]
    n = 4

    m = compute_retrieval_metrics(sim, labels, k=2, head_scores=head_scores)

    assert isinstance(m["ap_k_head"], list)
    assert len(m["ap_k_head"]) == n


def test_per_song_mrr_genre_list_length_matches_n_when_genres_present():
    """per_song['mrr_genre'] must be a list of length n when genre tags cover all songs."""
    sim = _block_sim(within=0.9, cross=0.1)
    labels = ["A", "A", "B", "B"]
    genres = ["G1", "G1", "G2", "G2"]
    n = 4

    m = compute_retrieval_metrics(sim, labels, k=2, genres=genres)

    assert isinstance(m["per_song"]["mrr_genre"], list)
    assert len(m["per_song"]["mrr_genre"]) == n
