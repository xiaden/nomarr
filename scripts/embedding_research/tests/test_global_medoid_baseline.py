"""Observed global-medoid baseline fixtures (Plan B P1-S5/S6; §B, DD L223-239).

Research-only, spec-first: these fixtures pin the S6-owned observed baseline
computation BEFORE the report loader rewiring (P1-S7) consumes it.  They cover:

* silent-region exclusion and absorbed-outlier exclusion from the observed medoid
  population (the medoid depends ONLY on the provided searchable source population,
  never on excluded rows),
* zero-searchable songs (metadata retained, excluded from both a baseline population and
  candidate search -> ``ObservedMedoid(None, None)`` — no baseline vector),
* zero-norm patch exclusion (never selected as medoid; null medoid when no nonzero
  searchable patch exists in scope),
* observed source-index mean-cosine centrality and smallest-source-index tie selection,
* the committed-observation bridge (whole-song non-silent searchable population) over
  synthetic committed stream + mask fixtures (conftest conventions),
* an assertion that NO synthetic medoid vector or coordinate-wise median is ever produced
  (only observed source indices).
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research.baseline import (
    observed_global_medoid_from_observation,
    whole_song_searchable_source_indices,
)
from scripts.embedding_research.helpers.segmentation import ObservedMedoid, observed_global_medoid

_BACKBONE = "effnet"


def _unit_axis(i: int, dim: int = 4) -> np.ndarray:
    v = np.zeros(dim, dtype=np.float32)
    v[i] = 1.0
    return v


def _rows(axes) -> np.ndarray:
    """Stack the requested unit-axis rows into a float32 [n, 4] matrix (one row per axis int)."""
    return np.stack([_unit_axis(a) for a in axes]).astype(np.float32)


# --------------------------------------------------------------------------- #
# Silent / absorbed exclusion from the observed population                     #
# --------------------------------------------------------------------------- #
def test_medoid_depends_only_on_provided_searchable_population():
    # rows = [e0, e0, e1].  Full population medoid is 0 (an e0, tie -> smallest source).
    rows = _rows([0, 0, 1])
    assert observed_global_medoid(rows, [0, 1, 2]).source_index == 0
    # Excluding index 1 (silent) leaves {0, 2}: e0 vs e1 tie -> smallest source 0.
    assert observed_global_medoid(rows, [0, 2]).source_index == 0
    # Excluding index 0 (a would-be medoid row, e.g. a silent region) leaves {1, 2}:
    # both are e0/e1 -> tie -> smallest source index 1.  The excluded row is never consulted.
    medoid = observed_global_medoid(rows, [1, 2])
    assert medoid.source_index == 1
    assert medoid.source_index in {1, 2}


def test_absorbed_outlier_exclusion_changes_medoid():
    # rows = [e0, e1, e1].  Including the outlier (index 0) makes an e1 the medoid; excluding
    # it (absorbed / not searchable) leaves {1, 2} (both e1) -> tie -> smallest source index 1.
    rows = _rows([0, 1, 1])
    # Sanity: the absorbed (excluded) row is never selected even when it would shift the result.
    assert observed_global_medoid(rows, [0, 1]).source_index == 0  # tie {e0, e1} -> smallest 0
    assert observed_global_medoid(rows, [1, 2]).source_index == 1  # absorbed outlier excluded
    # The selected index is always an OBSERVED searchable source index, never a synthetic row.
    medoid = observed_global_medoid(rows, [1, 2])
    assert medoid.source_index in {1, 2}


# --------------------------------------------------------------------------- #
# Zero-searchable songs / no baseline vector                                  #
# --------------------------------------------------------------------------- #
def test_zero_searchable_returns_no_baseline_vector():
    rows = _rows([0, 1])
    medoid = observed_global_medoid(rows, [])
    assert medoid == ObservedMedoid(None, None)
    assert medoid.source_index is None and medoid.centrality is None


def test_whole_song_searchable_indices_empty_for_silent_song():
    mask = np.zeros(6, dtype=np.uint8)
    idx = whole_song_searchable_source_indices(mask, 6)
    assert idx.shape == (0,)


def test_committed_bridge_zero_searchable_song_no_vector():
    obs = _Observation(_rows([0, 1]), np.zeros(2, dtype=np.uint8))
    medoid = observed_global_medoid_from_observation(obs)
    assert medoid == ObservedMedoid(None, None)


# --------------------------------------------------------------------------- #
# Zero-norm exclusion                                                          #
# --------------------------------------------------------------------------- #
def test_zero_norm_patch_never_selected_as_medoid():
    zero = np.zeros(4, dtype=np.float32)
    rows = np.stack([zero, _unit_axis(0)]).astype(np.float32)
    # Both rows searchable: only the nonzero e0 row is a candidate.
    medoid = observed_global_medoid(rows, [0, 1])
    assert medoid.source_index == 1
    # A zero-norm row at the SMALLEST source index is still never selected when a nonzero
    # candidate is in scope.
    assert observed_global_medoid(np.stack([zero, _unit_axis(0), _unit_axis(0)]), [0, 1, 2]).source_index == 1


def test_all_zero_norm_in_scope_yields_null_medoid():
    rows = np.stack([np.zeros(4, dtype=np.float32), np.zeros(4, dtype=np.float32)])
    medoid = observed_global_medoid(rows, [0, 1])
    assert medoid == ObservedMedoid(None, None)


# --------------------------------------------------------------------------- #
# Mean-cosine centrality and smallest-source-index tie selection               #
# --------------------------------------------------------------------------- #
def test_smallest_source_index_wins_exact_tie():
    # Identical rows -> identical mean cosine -> exact tie -> smallest source index.
    rows = _rows([0, 0])
    medoid = observed_global_medoid(rows, [0, 1])
    assert medoid.source_index == 0
    assert medoid.centrality == pytest.approx(1.0)


def test_maximal_mean_cosine_centrality():
    # rows = [e0, e0, e0, e1]: e0 rows dominate the population, so an e0 is the medoid.
    rows = _rows([0, 0, 0, 1])
    medoid = observed_global_medoid(rows, [0, 1, 2, 3])
    # mean cosine including self: e0 -> (1+1+1+0)/4 = 0.75 ; e1 -> (0+0+0+1)/4 = 0.25.
    assert medoid.centrality == pytest.approx(0.75)
    # Two e0 rows tie at 0.75; smallest source index (0) wins.
    assert medoid.source_index == 0


def test_tie_with_distinct_source_positions_returns_smallest():
    # Two rows on the same axis far apart in source index: exact tie -> smallest index wins.
    rows = np.stack([_unit_axis(2), _unit_axis(2)]).astype(np.float32)
    medoid = observed_global_medoid(rows, [0, 1])
    assert medoid.source_index == 0


# --------------------------------------------------------------------------- #
# No synthetic / coordinate-wise median vector                                 #
# --------------------------------------------------------------------------- #
def test_no_synthetic_medoid_vector_or_coordinate_median():
    rows = _rows([0, 0, 1])
    medoid = observed_global_medoid(rows, [0, 1, 2])
    # ObservedMedoid exposes ONLY an observed source index + centrality — never a vector.
    assert not hasattr(medoid, "vector")
    fields = set(getattr(medoid, "__dataclass_fields__", {}))
    assert fields == {"source_index", "centrality"}
    # source_index is one of the ORIGINAL committed-stream rows (an integer in range), and the
    # coordinate-wise median of e0/e1 (= (0.5,0.5,0,0)) is NOT a source row (indices only).
    assert isinstance(medoid.source_index, int)
    assert 0 <= medoid.source_index < len(rows)
    # The selected centrality equals the observed-source mean cosine (never a synthetic value).
    assert medoid.centrality == pytest.approx(2 / 3)


# --------------------------------------------------------------------------- #
# Non-finite input fails closed                                                #
# --------------------------------------------------------------------------- #
def test_non_finite_searchable_row_raises_value_error():
    rows = np.stack([_unit_axis(0), np.array([np.nan, 0.0, 0.0, 0.0], dtype=np.float32)])
    with pytest.raises(ValueError):
        observed_global_medoid(rows, [0, 1])
    inf_rows = np.stack([_unit_axis(0), np.array([np.inf, 0.0, 0.0, 0.0], dtype=np.float32)])
    with pytest.raises(ValueError):
        observed_global_medoid(inf_rows, [0, 1])


# --------------------------------------------------------------------------- #
# Committed-observation bridge (silence-aware, whole-song non-silent population)#
# --------------------------------------------------------------------------- #
class _Observation:
    """Minimal duck-typed committed observation (``CommittedObservation`` shape)."""

    def __init__(self, stream: np.ndarray, mask: np.ndarray) -> None:
        self.stream = np.ascontiguousarray(stream, dtype=np.float32)
        self.mask = np.asarray(mask, dtype=np.uint8)


def _reference_global_medoid(stream: np.ndarray, mask: np.ndarray):
    """Independent oracle: normalize rows, select over mask==1 by mean-cosine/smallest index."""
    arr = np.asarray(stream, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    unit = arr / norms
    searchable = [int(i) for i in np.nonzero(mask == 1)[0]]
    finite = unit[np.asarray(searchable, dtype=int)]
    nonzero = np.linalg.norm(finite, axis=1) > 0
    cand = [s for s, ok in zip(searchable, nonzero, strict=True) if ok]
    if not cand:
        return None
    sub = unit[np.asarray(cand, dtype=int)]
    sims = sub @ sub.T
    means = sims.mean(axis=1)
    return cand[int(np.argmax(means))]


def test_committed_bridge_selects_over_non_silent_population():
    # Four rows: two on axis0 then two on axis1; a SILENT region covers source 1 (an e0 that
    # would otherwise tie/win with source 0).  Committed bridge must ignore it.
    stream = _rows([0, 0, 1, 1])
    mask = np.array([1, 0, 1, 1], dtype=np.uint8)
    obs = _Observation(stream, mask)
    medoid = observed_global_medoid_from_observation(obs)
    assert medoid.source_index == _reference_global_medoid(stream, mask)
    assert medoid.source_index in {int(i) for i in np.nonzero(mask == 1)[0]}
    assert medoid.source_index != 1  # the silent region is never selected


def test_committed_bridge_whole_song_searchable_set_matches_mask():
    mask = np.array([1, 1, 0, 1, 0], dtype=np.uint8)
    idx = whole_song_searchable_source_indices(mask, 5)
    assert idx.tolist() == [0, 1, 3]
    # Rows at/after a shorter mask's length are searchable (mask only runs to patch_count).
    short = np.array([0], dtype=np.uint8)
    assert whole_song_searchable_source_indices(short, 4).tolist() == [1, 2, 3]


# --------------------------------------------------------------------------- #
# Real committed-group integration (conftest build_compact_catalog)           #
# --------------------------------------------------------------------------- #
def test_global_medoid_over_real_committed_group(compact_catalog_factory, con, tmp_path):
    """Compute the global medoid from a real committed observation group + mask (P1-S6 path)."""
    from scripts.embedding_research import catalog as catalog_mod

    cfg = catalog_mod.SegConfigInput(
        backbone=_BACKBONE,
        bin_mode="temporal_global",
        threshold_configured=0.5,
        threshold_effective=0.5,
    )
    stream = _rows([0, 0, 0, 1, 1])
    mask = np.array([1, 1, 0, 1, 1], dtype=np.uint8)  # source 2 is a silent region
    harness = compact_catalog_factory(
        con,
        tmp_path / "out",
        streams={("s1", _BACKBONE): stream},
        configs=[cfg],
        song_ids=["s1"],
        masks={"s1": mask},
        run_id="global-medoid-run",
    )
    try:
        observation = harness.stream_store.load_committed_observation("s1", _BACKBONE)
        medoid = observed_global_medoid_from_observation(observation)
        assert medoid.source_index == _reference_global_medoid(stream, mask)
        assert medoid.source_index in [0, 1, 3, 4]  # never the silent region (2)
    finally:
        harness.close()
