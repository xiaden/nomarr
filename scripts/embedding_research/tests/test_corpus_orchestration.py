"""Orchestration tests for Part C: threading weights + ordered representations through PTC/CTP analysis.

Covers the Phase-1 contracts:

* ``validate_binned_weights`` rejects misaligned / non-positive / dropped weight
  arrays (P1-S1 ordering + validation contract);
* per-song per-bin patch-count weights reach ``compute_agg_mats`` for every
  ordered pair and are NOT dropped or silently replaced by uniform weights,
  even across songs with unequal bin counts (P1-S2 / P1-S3);
* reverse directions are computed from the actual reverse arrays and are NOT
  copied/mirrored from the forward direction (P1-S3);
* PTC and CTP retrieval rows stay distinct even when their threshold text
  matches (e.g. both ``0.50``) because the strategy key retains the pathway
  (P1-S3 / P1-S2 persistence identity).
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research import db
from scripts.embedding_research import run as run_mod
from scripts.embedding_research.common.analyze import (
    _coerce_binned_pair_payload,
    _filter_binned_pairs,
    _load_head_scores_and_names,
    _normalise_binned_pairs,
    validate_binned_weights,
)
from scripts.embedding_research.report._base import _decode_strategy_key
from scripts.embedding_research.strategy_binned._process import compute_agg_mats
from scripts.embedding_research.vector_types import UnitTensor

# ── P1-S1: validate_binned_weights ordering contract ──────────────────────────


def test_validate_binned_weights_accepts_aligned_positive() -> None:
    weights = [np.array([2, 3], dtype=np.int32), np.array([1, 10, 1], dtype=np.int32)]
    # No exception raised for correctly co-indexed, strictly-positive arrays.
    validate_binned_weights(weights, weights, [2, 3])


def test_validate_binned_weights_rejects_song_count_mismatch() -> None:
    weights = [np.array([2, 3], dtype=np.int32)]  # only one per-song array
    with pytest.raises(ValueError, match="co-indexed"):
        validate_binned_weights(weights, weights, [2, 3])


def test_validate_binned_weights_rejects_bin_length_mismatch() -> None:
    # weights_a[0] has length 3 but song 0 has 2 bins -> misalignment.
    weights_a = [np.array([1, 1, 1], dtype=np.int32), np.array([1, 1], dtype=np.int32)]
    weights_b = [np.array([2, 2], dtype=np.int32), np.array([1, 1, 1], dtype=np.int32)]
    with pytest.raises(ValueError, match="ordering"):
        validate_binned_weights(weights_a, weights_b, [2, 2])


def test_validate_binned_weights_rejects_zero_weight() -> None:
    # Patch counts are never zero; a zeroed weight array is a corruption signal.
    weights = [np.array([0, 3], dtype=np.int32)]
    with pytest.raises(ValueError, match="strictly positive"):
        validate_binned_weights(weights, weights, [2])


def test_validate_binned_weights_rejects_2d_weight_array() -> None:
    weights = [np.array([[1, 2], [3, 4]], dtype=np.int32)]
    with pytest.raises(ValueError, match="1-D"):
        validate_binned_weights(weights, weights, [2])


def test_coerce_binned_pair_payload_validates_weights() -> None:
    payload = {
        "norm_a_all": [UnitTensor(np.array([[1.0, 0.0], [0.0, 1.0]]))],
        "norm_b_all": [UnitTensor(np.array([[1.0, 0.0], [0.0, 1.0]]))],
        "bin_counts": [2],
        # weights_a length 3 != bin count 2 -> must be rejected at coercion.
        "weights_a": [np.array([1, 1, 1], dtype=np.int32)],
        "weights_b": [np.array([1, 1], dtype=np.int32)],
    }
    with pytest.raises(ValueError, match="ordering"):
        _coerce_binned_pair_payload(payload, {})


def test_normalise_binned_pairs_carries_explicit_weights_a_b() -> None:
    payload = {
        "norm_a_all": [UnitTensor(np.array([[1.0, 0.0], [0.0, 1.0]]))],
        "norm_b_all": [UnitTensor(np.array([[1.0, 0.0], [0.0, 1.0]]))],
        "bin_counts": [2],
        "weights_a": [np.array([2, 3], dtype=np.int32)],
        "weights_b": [np.array([2, 3], dtype=np.int32)],
    }
    pairs = _normalise_binned_pairs({"pairs": [payload]}, {})
    assert len(pairs) == 1
    np.testing.assert_array_equal(pairs[0]["weights_a"][0], [2, 3])
    np.testing.assert_array_equal(pairs[0]["weights_b"][0], [2, 3])


# ── P1-S3: weights flow into compute_agg_mats, not dropped ────────────────────


def _unit(matrix: list[list[float]]) -> UnitTensor:
    return UnitTensor(np.asarray(matrix, dtype=np.float32))


# Two songs with UNEQUAL bin counts per song (song0 = 2 bins, song1 = 3 bins).
# rep_a and rep_b are distinct representations of the same bins per song.
# All rows are unit vectors (UnitTensor re-normalises rows on construction).
_NORM_A = [_unit([[1.0, 0.0], [0.0, 1.0]]), _unit([[1.0, 0.0], [0.0, 1.0], [0.6, 0.8]])]
_NORM_B = [_unit([[1.0, 0.0], [0.0, 1.0]]), _unit([[1.0, 0.0], [0.6, 0.8], [0.0, 1.0]])]
_BIN_COUNTS = [2, 3]
_WEIGHTS = [np.array([2, 3], dtype=np.int32), np.array([1, 10, 1], dtype=np.int32)]
_UNIFORM_WEIGHTS = [np.ones(2, dtype=np.float32), np.ones(3, dtype=np.float32)]


def test_unequal_bin_counts_weights_not_dropped_hand_computed() -> None:
    """Per-song weights with unequal bin counts reach target_weighted and match a hand computation."""
    mats = compute_agg_mats(_NORM_A, _NORM_B, _WEIGHTS, _WEIGHTS, "cosine")
    target = mats["target_weighted"]

    # Forward pair (0 -> 1): a0 @ b1.T with b1 = [[1,0],[0.6,0.8],[0,1]] gives
    #   S = [[1, 0.6, 0], [0, 0.8, 1]]; target weights [1,10,1] (sum 12).
    #   row0 = (1 + 6)/12 = 7/12; row1 = (8 + 1)/12 = 9/12; score = (7/12 + 9/12)/2 = 2/3.
    np.testing.assert_allclose(target[0, 1], 2.0 / 3.0, atol=1e-5)

    # Reverse pair (1 -> 0): a1 @ b0.T with a1 = [[1,0],[0,1],[0.6,0.8]] gives
    #   S = [[1, 0], [0, 1], [0.6, 0.8]]; target weights [2,3] (sum 5).
    #   row0 = 2/5; row1 = 3/5; row2 = 3.6/5; score = (2 + 3 + 3.6)/15 = 8.6/15.
    np.testing.assert_allclose(target[1, 0], 8.6 / 15.0, atol=1e-5)

    # normalized_mean_pair_weighted forward: sum_ab(wA[a]wB[b]S[a,b]) / (sum wA * sum wB)
    #   = 41 / (5 * 12) = 41/60
    nmpw = mats["normalized_mean_pair_weighted"]
    np.testing.assert_allclose(nmpw[0, 1], 41.0 / 60.0, atol=1e-5)


def test_weights_are_not_silently_replaced_by_uniform() -> None:
    """The real patch-count weights change the score vs. uniform weights -> not dropped."""
    real = compute_agg_mats(_NORM_A, _NORM_B, _WEIGHTS, _WEIGHTS, "cosine")["target_weighted"]
    uniform = compute_agg_mats(_NORM_A, _NORM_B, _UNIFORM_WEIGHTS, _UNIFORM_WEIGHTS, "cosine")["target_weighted"]
    # Forward (0 -> 1) with uniform weights = ((1+0.6+0)/3 + (0+0.8+1)/3)/2 = (1.6/3 + 1.8/3)/2.
    np.testing.assert_allclose(uniform[0, 1], ((1.6 / 3.0) + (1.8 / 3.0)) / 2.0, atol=1e-5)
    assert real[0, 1] != uniform[0, 1]


def test_reverse_directions_not_copied() -> None:
    """Reverse scores come from the actual reverse arrays, never mirrored from forward."""
    mats = compute_agg_mats(_NORM_A, _NORM_B, _WEIGHTS, _WEIGHTS, "cosine")
    target = mats["target_weighted"]

    # Forward (0->1)=2/3, reverse (1->0)=8.6/15 — genuinely different, so a mirroring
    # implementation (reverse := forward.T) would have failed this assertion.
    assert target[0, 1] != target[1, 0]
    np.testing.assert_allclose(target[0, 1], 2.0 / 3.0, atol=1e-5)
    np.testing.assert_allclose(target[1, 0], 8.6 / 15.0, atol=1e-5)

    # bidirectional_weighted is the only symmetric reduction by construction.
    bidir = mats["bidirectional_weighted"]
    np.testing.assert_allclose(bidir[0, 1], (target[0, 1] + target[1, 0]) / 2.0, atol=1e-6)


# ── P1-S3: PTC and CTP rows distinct even with identical threshold text ───────


def _row_dict(key: str, stype: str) -> dict[str, object]:
    return {"strategy_key": key, "strategy_type": stype, "sim_metric": "cosine", "k": 10, "metric": "mrr", "value": 0.5}


def test_ptc_ctp_strategy_keys_distinct_same_threshold() -> None:
    """Same threshold text (0.50) but distinct pathway -> keys and decoded configs differ."""
    shared = {"std_thresh": 0.5, "rep_a": "mean", "rep_b": "max", "agg_method": "target_weighted"}

    ptc_key = run_mod._ptc_strategy_key("effnet", "ptc_temporal_global_0.5", {"bin_mode": "temporal_global", **shared})
    ctp_key = run_mod._ctp_strategy_key("effnet", "ctp_mood_0.5", {"head": "mood", **shared})

    assert "0.50" in ptc_key and "0.50" in ctp_key
    assert ptc_key != ctp_key
    assert ptc_key.startswith("ptc:") and ctp_key.startswith("ctp:")

    import pandas as pd

    df = _decode_strategy_key(
        pd.DataFrame(
            {
                "strategy_key": [ptc_key, ctp_key],
                "strategy_type": ["ptc", "ctp"],
                "sim_metric": ["cosine", "cosine"],
                "k": [10, 10],
            }
        )
    )
    ptc_row = df[df["strategy_type"] == "ptc"].iloc[0]
    ctp_row = df[df["strategy_type"] == "ctp"].iloc[0]
    assert ptc_row["bin_mode"] == "temporal_global"
    assert ctp_row["head"] == "mood"
    assert ptc_row["rep_a"] == ctp_row["rep_a"] == "mean"
    assert ptc_row["rep_b"] == ctp_row["rep_b"] == "max"
    assert ptc_row["agg_method"] == ctp_row["agg_method"] == "target_weighted"
    assert ptc_row["std_thresh"] == ctp_row["std_thresh"] == 0.5


def test_ptc_ctp_rows_remain_distinct_in_db(con) -> None:
    """Persisting both same-threshold configs yields two distinct analyze_metrics rows."""
    shared = {"std_thresh": 0.5, "rep_a": "mean", "rep_b": "max", "agg_method": "target_weighted"}
    ptc_key = run_mod._ptc_strategy_key("effnet", "ptc_temporal_global_0.5", {"bin_mode": "temporal_global", **shared})
    ctp_key = run_mod._ctp_strategy_key("effnet", "ctp_mood_0.5", {"head": "mood", **shared})

    db.write_analyze_metrics(con, ptc_key, "ptc", "cosine", 10, {"mrr": 0.42})
    db.write_analyze_metrics(con, ctp_key, "ctp", "cosine", 10, {"mrr": 0.61})

    df = db.load_analyze_metrics(con)
    assert sorted(df["strategy_key"].tolist()) == sorted([ptc_key, ctp_key])
    assert sorted(df["strategy_type"].tolist()) == sorted(["ptc", "ctp"])


# ── P1-S4: invariants preserved through the binned analysis path ─────────────


def test_filter_binned_pairs_keeps_metadata_aligned() -> None:
    """Flat/binned metadata alignment: filtering keeps norm arrays, bin_counts, and weights co-indexed."""
    import numpy as _np

    payload = {
        "rep_a": "mean",
        "rep_b": "max",
        "norm_a_all": [
            UnitTensor(_np.array([[1.0, 0.0]])),
            UnitTensor(_np.array([[0.0, 1.0]])),
            UnitTensor(_np.array([[0.5, 0.5]])),
        ],
        "norm_b_all": [
            UnitTensor(_np.array([[1.0, 0.0]])),
            UnitTensor(_np.array([[0.0, 1.0]])),
            UnitTensor(_np.array([[0.5, 0.5]])),
        ],
        "bin_counts": [1, 1, 1],
        "weights_a": [
            _np.array([2], dtype=_np.int32),
            _np.array([3], dtype=_np.int32),
            _np.array([4], dtype=_np.int32),
        ],
        "weights_b": [
            _np.array([2], dtype=_np.int32),
            _np.array([3], dtype=_np.int32),
            _np.array([4], dtype=_np.int32),
        ],
    }
    filtered = _filter_binned_pairs({"pairs": [payload]}, [0, 2], {})
    assert len(filtered) == 1
    out = filtered[0]
    # Same keep indices applied to every per-song list -> still mutually aligned.
    assert [int(p["bin_counts"][0]) for p in [out]] == [1]
    assert len(out["norm_a_all"]) == 2 and len(out["norm_b_all"]) == 2
    assert len(out["weights_a"]) == 2 and len(out["weights_b"]) == 2
    # The kept songs (0 and 2) and their weights line up exactly.
    assert out["weights_a"][0].item() == 2 and out["weights_a"][1].item() == 4
    assert out["weights_b"][0].item() == 2 and out["weights_b"][1].item() == 4


def test_load_head_scores_uses_act1_in_binned_path(monkeypatch) -> None:
    """The binned analysis head-score plumbing reads act[1] (class-1), never act[0]."""
    import scripts.embedding_research.common.analyze as analyze_mod

    monkeypatch.setattr(analyze_mod, "HEADS", {"bb": {"mood": object()}})

    def _load_bulk(_backbone, _head, _strategy, _pathway, _sids):
        # act = [p0, p1]; act[1] is the class-1 score the pipeline uses everywhere.
        return {"s1": np.array([0.10, 0.90]), "s2": np.array([0.70, 0.30])}

    monkeypatch.setattr(analyze_mod._flat_heads_cache, "load_bulk", _load_bulk)

    matrix, head_names = _load_head_scores_and_names("bb", ["s1", "s2"])
    assert head_names == ["mood"]
    np.testing.assert_allclose(matrix[0], [0.90, 0.30], atol=1e-6)


def test_no_disc_album_in_touched_modules() -> None:
    """Guard: none of the modules changed by this phase contains a disc_album code path.

    The authoritative whole-research guard lives in ``test_frozen_invariants.py``; this
    is a focused guard over exactly the files edited in Phase 1.
    """
    import ast
    from pathlib import Path

    import scripts.embedding_research.common.analyze as analyze_mod
    import scripts.embedding_research.db.flat as flat_mod

    modules = {
        "analyze": Path(analyze_mod.__file__),
        "db.flat": Path(flat_mod.__file__),
        "run": Path(run_mod.__file__),
    }
    offenders = [
        f"{label}:{node.lineno}"
        for label, path in modules.items()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if (isinstance(node, ast.Name) and node.id == "disc_album")
        or (isinstance(node, ast.Attribute) and node.attr == "disc_album")
    ]
    assert not offenders, f"disc_album code reference in: {offenders}"
