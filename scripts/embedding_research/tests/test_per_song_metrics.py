"""Tests for per-song retrieval metrics and persistence."""

from __future__ import annotations

import numpy as np

from scripts.embedding_research.common import analyze as common_analyze_mod
from scripts.embedding_research.common.analyze import AnalyzeCfg, _var_kurt
from scripts.embedding_research.common.analyze import analyze as analyze_common
from scripts.embedding_research.db import write_song_retrieval_metrics
from scripts.embedding_research.similarity import compute_retrieval_metrics
from scripts.embedding_research.vector_types import RawTensor


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


def _raw_tensor(rows: list[list[float]]) -> RawTensor:
    return RawTensor(np.asarray(rows, dtype=np.float32))


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


def test_write_read_roundtrip(con):
    per_song_dict = {
        "song_ids": ["s1", "s2", "s3"],
        "ap_k": [1.0, 0.5, 0.0],
        "mrr": [1.0, 0.5, 0.3333333333333333],
        "recall_k": [1.0, 1.0, 0.0],
        "disc_artist_contrib": [0.8, 0.6, None],
        "disc_genre_contrib": [0.7, 0.4, None],
        "disc_head_contrib": [0.3, None, 0.1],
    }

    write_song_retrieval_metrics(con, "s", "cosine", 10, per_song_dict)

    rows = con.execute("SELECT * FROM song_retrieval_metrics").fetchall()

    assert len(rows) == len(per_song_dict["song_ids"])


def test_var_kurt_rows_written(con, monkeypatch):
    sids = ["s1", "s2", "s3", "s4"]
    artists = ["A", "A", "B", "B"]
    albums = ["Album A", "Album A", "Album B", "Album B"]
    genres = ["Rock", "Rock", "Jazz", "Jazz"]
    vecs = _raw_tensor(
        [
            [1.0, 0.0, 0.0],
            [0.9, 0.1, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.9, 0.1],
        ]
    )

    cfg: AnalyzeCfg = {
        "strategy_names": ["mean"],
        "load_vecs_fn": lambda _bb, _strategy, _con, _extra: (
            vecs,
            list(sids),
            list(artists),
            list(albums),
            list(genres),
        ),
        "db_write_fn": lambda con, strategy_key, strategy_type, sim_metric, k, metrics: (
            common_analyze_mod.db.write_analyze_metrics(
                con,
                strategy_key,
                strategy_type,
                sim_metric,
                k,
                {name: value for name, value in metrics.items() if not isinstance(value, (list, dict))},
            )
        ),
        "strategy_key_fn": lambda backbone, strategy_name, _extra: f"{backbone}:{strategy_name}",
        "strategy_type": "global_pool",
        "extra_cfg": {},
    }

    monkeypatch.setattr(common_analyze_mod.db, "query_analysis_done", lambda _con: set())
    monkeypatch.setattr(common_analyze_mod, "_load_head_scores_and_names", lambda _bb, _sids: (None, None))

    analyze_common(con, cfg, backbones=["bb"], k=2)

    rows = con.execute("SELECT metric FROM analyze_metrics WHERE metric IN ('var_ap_k', 'kurt_ap_k')").fetchall()
    metrics_written = {row[0] for row in rows}

    assert "var_ap_k" in metrics_written
    assert "kurt_ap_k" in metrics_written


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


def test_write_song_retrieval_metrics_skips_insert_for_empty_per_song(con):
    write_song_retrieval_metrics(con, "s", "cosine", 10, {})

    row_count = con.execute("SELECT COUNT(*) FROM song_retrieval_metrics").fetchone()[0]

    assert row_count == 0


def test_var_kurt_returns_none_for_insufficient_values_and_values_for_valid_input():
    assert _var_kurt([]) == (None, None)
    assert _var_kurt([None, None]) == (None, None)
    assert _var_kurt([1.5]) == (None, None)

    variance, kurtosis = _var_kurt([1.0, 2.0, 3.0])

    assert variance is not None
    assert kurtosis is not None
