"""Tests for per-song retrieval metrics from ``similarity.compute_retrieval_metrics``.

(The analyze-common orchestration and ``db.write_song_retrieval_metrics``
persistence surfaces those per-song metrics fed from were deleted with the
flat/binned analyze pipeline in the corrective-pass hard cut; only the
retrieval-metric computation that survives is covered here.)
"""

from __future__ import annotations

import numpy as np

from scripts.embedding_research.similarity import compute_retrieval_metrics


def _five_song_sim_matrix() -> np.ndarray:
    return np.array(
        [
            [1.0, 0.95, 0.10, 0.10, 0.20],
            [0.95, 1.0, 0.10, 0.10, 0.20],
            [0.10, 0.10, 1.0, 0.93, 0.25],
            [0.10, 0.10, 0.93, 1.0, 0.25],
            [0.20, 0.20, 0.25, 0.25, 1.0],
        ],
        dtype=np.float32,
    )


def test_per_song_dict_all_keys_present():
    result = compute_retrieval_metrics(
        _five_song_sim_matrix(),
        ["A", "A", "B", "B", "C"],
        k=3,
        genres=["Rock", "Rock", "Jazz", "Jazz", "Pop"],
        head_scores=[[0.05, 0.10, 0.85, 0.90, 0.45]],
        head_names=["mood"],
        sids=["s1", "s2", "s3", "s4", "s5"],
    )

    assert "per_song" in result
    assert set(result["per_song"]) == {
        "song_ids",
        "ap_k",
        "mrr",
        "recall_k",
        "disc_artist_contrib",
        "disc_genre_contrib",
        "disc_head_contrib",
        "ap_k_genre",
        "mrr_genre",
        "ap_k_head",
        "mrr_head",
    }


def test_per_song_song_ids_match_sids():
    sids = ["song-c", "song-a", "song-e", "song-b"]

    result = compute_retrieval_metrics(
        np.array(
            [
                [1.0, 0.94, 0.10, 0.10],
                [0.94, 1.0, 0.10, 0.10],
                [0.10, 0.10, 1.0, 0.91],
                [0.10, 0.10, 0.91, 1.0],
            ],
            dtype=np.float32,
        ),
        ["A", "A", "B", "B"],
        k=2,
        sids=sids,
    )

    assert result["per_song"]["song_ids"] == sids


def test_per_song_singleton_artist_is_none():
    result = compute_retrieval_metrics(
        np.array(
            [
                [1.0, 0.2, 0.3],
                [0.2, 1.0, 0.4],
                [0.3, 0.4, 1.0],
            ],
            dtype=np.float32,
        ),
        ["A", "B", "C"],
        k=2,
        sids=["s1", "s2", "s3"],
    )

    assert result["per_song"]["disc_artist_contrib"] == [None, None, None]


def test_per_song_song_ids_fallback_to_indices_when_sids_missing():
    result = compute_retrieval_metrics(
        np.array(
            [
                [1.0, 0.92, 0.10],
                [0.92, 1.0, 0.15],
                [0.10, 0.15, 1.0],
            ],
            dtype=np.float32,
        ),
        ["A", "A", "B"],
        k=2,
    )

    assert result["per_song"]["song_ids"] == ["0", "1", "2"]
