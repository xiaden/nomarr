"""Plan C P1-S1 — spec-first semantics for the compact segmentation catalog.

Pins the corrective-pass searchable-membership contract that P1-S4 implements in
``helpers/segmentation.py`` (the DD-designated single canonical home — see DD
"Membership, segmentation, medoids, and weights", line ~234, and the active-module
graph: *"Segmentation and membership | helpers/segmentation.py | The single
implementation of structural range minus absorbed exceptions minus mask"*).

The contract surfaces tested here are §C of ``parts/CONTRACTS.md`` plus the DD's
segmentation/medoid semantics:

* ``reconstruct_searchable_indices(meta, mask, patch_count)`` — exact membership is
  ``{start <= i < end} - absorbed_indices - {mask[i] == 0}``, sorted; the structural
  range is NEVER authoritative membership; absorbed outliers keep their structural
  position/identity but contribute zero searchable mass;
* the spherical segmentation runner (``run_spherical_segmentation``) — unit-vector
  running spherical centroid, strict ``>`` direct-L2 threshold (a vector exactly at
  threshold is NOT an outlier/split), ``OUTLIER_WINDOW=3`` absorption with return,
  hard splitting (an excursion that does not return is an ordinary *searchable*
  structural segment, never absorbed), finite-only input (NaN/Infinity raise);
* mask-aware membership ``M_g = [start,end) - absorbed - silent`` over a full song;
* ``select_observed_medoid_source_index`` medoid edges — zero-norm patches are never
  medoids, a null medoid when no nonzero searchable patch exists, and NaN/Infinity
  are rejected (raise, never silent).

Every helper below lives in ``helpers/segmentation.py`` and does NOT exist at the
current head (the per-patch body there is a Plan C P1-S3/S1-S4 replacement target).
These tests therefore fail with ``NotImplementedError`` now (spec-first red) and go
green once P1-S4 implements the pinned homes. They are synthetic numpy-only: no
DuckDB, no audio, no model, no corpus.

Pinned API homes (recorded in the P1-S1 plan annotation under ``API-HOME``):
``reconstruct_searchable_indices`` / ``select_observed_medoid_source_index`` /
``run_spherical_segmentation`` all live in ``helpers/segmentation.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from scripts.embedding_research.helpers import segmentation as seg_mod

#: Intended compact ``seg_meta`` / ``catalog_song`` table set (no per-patch membership
#: table, no per-patch rows).  Recorded for P1-S3 so the schema is built to this shape.
COMPACT_TABLES = ("catalog_metadata", "seg_config", "catalog_song", "seg_meta", "run_provenance")


@dataclass(frozen=True)
class _CompactMeta:
    """Duck-typed :class:`SegMetaRecord` view exposing the §C reconstruction fields.

    ``reconstruct_searchable_indices`` reads exactly ``start_idx``, ``end_idx``
    (exclusive structural range) and ``absorbed_indices`` (canonical sparse absorbed
    outlier source indices) from its ``meta`` argument; the rebuilt catalog
    ``SegMetaRecord`` carries these same fields, so this lightweight view keeps the
    P1-S1 tests independent of the not-yet-rebuilt ``catalog.py`` DTO.
    """

    start_idx: int
    end_idx: int
    absorbed_indices: tuple[int, ...] = ()


def _future(name: str):
    """Return a not-yet-implemented §C helper or raise NotImplementedError (spec-first red).

    Collection stays clean (the ``helpers/segmentation`` module imports fine); each
    dependent test fails at RUN time with a precise "P1-S4 must implement" message
    until P1-S4 lands the compact bodies at the pinned home.
    """
    fn = getattr(seg_mod, name, None)
    if fn is None:
        raise NotImplementedError(f"P1-S4 must implement {name} in scripts.embedding_research.helpers.segmentation")
    return fn


def _reconstruct(meta: _CompactMeta, mask: np.ndarray, patch_count: int) -> np.ndarray:
    return _future("reconstruct_searchable_indices")(meta, mask, patch_count)


def _ones(patch_count: int, *, silent: tuple[int, ...] = ()) -> np.ndarray:
    mask = np.ones(patch_count, dtype=np.uint8)
    for idx in silent:
        mask[idx] = 0
    return mask


# --------------------------------------------------------------------------- #
# Mask-aware membership:  M_g = {start <= i < end} - absorbed - silent          #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_reconstruct_full_structural_range_when_no_absorbed_or_silent():
    mask = _ones(10)
    got = _reconstruct(_CompactMeta(2, 8), mask, 10)
    np.testing.assert_array_equal(got, np.asarray([2, 3, 4, 5, 6, 7], dtype=int))


@pytest.mark.unit
def test_reconstruct_excludes_absorbed_outliers_and_stays_sorted():
    """Absorbed outliers retain structural position but are not searchable members."""
    mask = _ones(10)
    got = _reconstruct(_CompactMeta(2, 9, (3, 5, 8)), mask, 10)
    np.testing.assert_array_equal(got, np.asarray([2, 4, 6, 7], dtype=int))


@pytest.mark.unit
def test_reconstruct_excludes_silent_mask_patches():
    mask = _ones(10, silent=(1, 4, 6))
    got = _reconstruct(_CompactMeta(0, 8), mask, 10)
    np.testing.assert_array_equal(got, np.asarray([0, 2, 3, 5, 7], dtype=int))


@pytest.mark.unit
def test_reconstruct_exact_set_for_absorbed_plus_silent_combinations():
    """Exact set equality for structural range minus absorbed minus silent, sorted."""
    mask = _ones(10, silent=(6,))
    got = _reconstruct(_CompactMeta(2, 8, (3, 5)), mask, 10)
    # {2..7} - {3,5} - {6} = {2,4,7}
    np.testing.assert_array_equal(got, np.asarray([2, 4, 7], dtype=int))
    assert got.dtype.kind == "i"


@pytest.mark.unit
def test_reconstruct_ignores_absorbed_indices_outside_structural_range():
    """Membership is range-driven: an absorbed index outside [start, end) is a no-op."""
    mask = _ones(10)
    # absorbed 9 is outside [4,7) and must not change the result; absorbed 4 is removed.
    got = _reconstruct(_CompactMeta(4, 7, (4, 9)), mask, 10)
    np.testing.assert_array_equal(got, np.asarray([5, 6], dtype=int))


@pytest.mark.unit
def test_reconstruct_fully_silent_segment_is_empty():
    mask = _ones(10, silent=(3, 4, 5, 6, 7))
    got = _reconstruct(_CompactMeta(3, 8), mask, 10)
    assert got.size == 0


@pytest.mark.unit
def test_reconstruct_empty_structural_range_is_empty():
    """A structural range with no patches (end <= start) yields empty membership."""
    mask = _ones(10)
    assert _reconstruct(_CompactMeta(5, 5), mask, 10).size == 0
    assert _reconstruct(_CompactMeta(7, 4), mask, 10).size == 0


@pytest.mark.unit
def test_reconstruct_membership_partitions_searchable_mass_of_a_song():
    """Composing per-segment reconstruction reproduces the non-silent searchable set."""
    # Song with patch_count 10, three structural segments; absorbed + silent excluded.
    song_mask = _ones(10, silent=(2, 9))
    metas = (
        _CompactMeta(0, 4, (1,)),  # searchable {0, 3}
        _CompactMeta(4, 7),  # searchable {4, 5, 6} (2 silent)
        _CompactMeta(7, 10, (8,)),  # searchable {7} (9 silent, 8 absorbed)
    )
    recovered: list[int] = []
    for meta in metas:
        recovered.extend(int(i) for i in _reconstruct(meta, song_mask, 10))
    assert recovered == sorted(recovered)
    assert recovered == [0, 3, 4, 5, 6, 7]


# --------------------------------------------------------------------------- #
# Spherical segmentation runner: strict >, OUTLIER_WINDOW=3, absorbed, hard split #
# --------------------------------------------------------------------------- #


def _unit_rows(*vectors) -> np.ndarray:
    return np.asarray(list(vectors), dtype=np.float32)


@pytest.mark.unit
def test_spherical_segmentation_exactly_at_threshold_is_not_a_split():
    """Strict ``>``: a patch whose distance equals the threshold is NOT a boundary."""
    a = np.array([1.0, 0.0])
    b = np.array([0.0, 1.0])
    patches = _unit_rows(a, b)
    threshold = float(np.linalg.norm(b - a))  # distance == threshold exactly
    segments = _future("run_spherical_segmentation")(patches, threshold)
    assert len(segments) == 1
    seg = segments[0]
    assert (seg.start_idx, seg.end_idx) == (0, 2)
    assert tuple(seg.absorbed_indices) == ()


@pytest.mark.unit
def test_spherical_segmentation_strictly_above_threshold_splits_tail():
    """Only a distance STRICTLY greater than the threshold is a boundary (hard tail split)."""
    a = np.array([1.0, 0.0])
    b = np.array([0.0, 1.0])
    patches = _unit_rows(a, b)
    threshold = float(np.linalg.norm(b - a)) - 1e-6
    segments = _future("run_spherical_segmentation")(patches, threshold)
    assert len(segments) == 2
    assert (segments[0].start_idx, segments[0].end_idx) == (0, 1)
    assert (segments[1].start_idx, segments[1].end_idx) == (1, 2)


@pytest.mark.unit
def test_spherical_segmentation_absorbs_window3_return_and_excludes_from_searchable():
    """An <=3-outlier excursion that returns is absorbed; structural position retained.

    Exact 2-D geometry (unit ``+x`` / ``-x``): four ``+x`` in-range patches, then three
    ``-x`` outliers (window 3) that return to ``+x`` — all absorbed outliers stay inside
    the single structural segment but are excluded from searchable membership.
    """
    x = np.array([1.0, 0.0])
    nx = np.array([-1.0, 0.0])
    patches = _unit_rows(x, x, x, x, nx, nx, nx, x)  # 8 patches
    segments = _future("run_spherical_segmentation")(patches, 1.0)
    assert len(segments) == 1
    seg = segments[0]
    assert (seg.start_idx, seg.end_idx) == (0, 8)
    assert tuple(seg.absorbed_indices) == (4, 5, 6)
    # Reconstruct over an all-searchable mask: only the absorbed outliers are excluded.
    searchable = _reconstruct(_CompactMeta(seg.start_idx, seg.end_idx, tuple(seg.absorbed_indices)), _ones(8), 8)
    np.testing.assert_array_equal(searchable, np.asarray([0, 1, 2, 3, 7], dtype=int))


@pytest.mark.unit
def test_spherical_segmentation_hard_split_excursion_is_ordinary_searchable_segment():
    """An excursion that exceeds the window (no return) is a HARD split, not absorbed.

    Four ``+x`` then four ``-x`` (window 3 exceeded, no return): the second excursion
    becomes an ordinary *searchable* structural segment — it is never absorbed and never
    excluded from searchable membership.
    """
    x = np.array([1.0, 0.0])
    nx = np.array([-1.0, 0.0])
    patches = _unit_rows(x, x, x, x, nx, nx, nx, nx)  # 8 patches
    segments = _future("run_spherical_segmentation")(patches, 1.0)
    assert len(segments) == 2
    first, second = segments
    assert (first.start_idx, first.end_idx) == (0, 4)
    assert tuple(first.absorbed_indices) == ()
    assert (second.start_idx, second.end_idx) == (4, 8)
    assert tuple(second.absorbed_indices) == ()
    # The hard-split excursion is fully searchable (its own segment), never absorbed.
    searchable = _reconstruct(
        _CompactMeta(second.start_idx, second.end_idx, tuple(second.absorbed_indices)), _ones(8), 8
    )
    np.testing.assert_array_equal(searchable, np.asarray([4, 5, 6, 7], dtype=int))


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
@pytest.mark.unit
def test_spherical_segmentation_rejects_non_finite_input(bad):
    """No NaN or infinity is admitted: segmentation raises, never silently proceeds."""
    a = np.array([1.0, 0.0])
    patch = np.array([bad, 0.0], dtype=np.float32)
    patches = _unit_rows(a, patch)
    with pytest.raises(ValueError):
        _future("run_spherical_segmentation")(patches, 1.0)


# --------------------------------------------------------------------------- #
# Observed-source medoid edges: zero-norm / non-finite / null                    #
# --------------------------------------------------------------------------- #


def _select(unit_patches: np.ndarray, source_indices) -> tuple:
    return _future("select_observed_medoid_source_index")(unit_patches, source_indices)


@pytest.mark.unit
def test_observed_medoid_null_when_no_nonzero_searchable_patch():
    """Null medoid (None) when every searchable row is zero-norm (nothing finite+nonzero)."""
    rows = np.zeros((3, 4), dtype=np.float32)
    idx, centrality = _select(rows, (0, 1, 2))
    assert idx is None
    assert centrality is None


@pytest.mark.unit
def test_observed_medoid_never_selects_zero_norm_when_nonzero_searchable_exists():
    """Zero-norm patches are never medoids; a finite nonzero searchable row is chosen."""
    x = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    zero = np.zeros(4, dtype=np.float32)
    rows = np.stack([x, zero, x])
    idx, _ = _select(rows, (0, 1, 2))
    assert idx in (0, 2)  # never the zero-norm source index 1


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
@pytest.mark.unit
def test_observed_medoid_rejects_non_finite_candidate_row(bad):
    """NaN/Infinity among the searchable candidate rows raises (never a silent medoid)."""
    x = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    bad_row = np.array([bad, 0.0, 0.0, 0.0], dtype=np.float32)
    rows = np.stack([x, bad_row])
    with pytest.raises(ValueError):
        _select(rows, (0, 1))


# --------------------------------------------------------------------------- #
# Durable compact-shape guards (self-contained, green now)                      #
# --------------------------------------------------------------------------- #


def test_compact_catalog_has_no_per_patch_membership_table_name():
    """The intended compact table set never includes a per-patch membership table."""
    assert "seg_membership" not in COMPACT_TABLES
    # The five compact scalar tables are the complete durable catalog surface.
    assert sorted(COMPACT_TABLES) == sorted(
        ("catalog_metadata", "seg_config", "catalog_song", "seg_meta", "run_provenance")
    )
