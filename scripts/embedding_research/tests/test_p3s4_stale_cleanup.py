"""Plan E P3-S4 — stale optimizer/cache cleanup + obsolete-writer removal (locked).

Covers the four obligations of P3-S4 after the caller audit:

1. Stale optimizer vocabulary: the coordinate-wise synthetic ``median`` rep is REJECTED
   pointing at ``medoid``, and the optimizer's ``rep_type="medoid"`` path resolves to an
   OBSERVED source row (never a synthetic centroid) — and a default catalog+analyze run
   proceeds with ``[optimization]`` disabled / absent (no optimizer output required).
2. Stale cache artifacts: ``pool_medoid_raw``/``pool_medoid_norm`` copied-vector fields are
   historical archival npz payload fields with no surviving default-path writer; the only
   medoid representation the live code emits is an observed source row (asserted via the
   binned/optimizer medoid path).
3. Obsolete writer removal: the audited zero-caller writers are absent from the live tree
   (``_process._compute_song_stats``/``_process_group``, ``strategy_binned/_calibrate.py``,
   ``strategy_binned/_features.py``, ``db/patch.py``), and a default-path catalog+analyze run
   produces no rows in ``binned_song_stats`` / ``binned_calibration`` / ``patch_features``.
"""

from __future__ import annotations

import importlib.util

import numpy as np
import pytest

from scripts.embedding_research import db as _db
from scripts.embedding_research.strategy_binned import _constants as _const
from scripts.embedding_research.strategy_binned._pool import _pool_segment
from scripts.embedding_research.vector_types import RawTensor, UnitTensor

# --------------------------------------------------------------------------- #
# 3. Obsolete writers removed / absent
# --------------------------------------------------------------------------- #


def test_obsolete_dead_writers_removed_from_process_module() -> None:
    """The audited zero-caller binned writers are gone; live helpers remain."""
    from scripts.embedding_research.strategy_binned import _process as pm

    assert not hasattr(pm, "_compute_song_stats")
    assert not hasattr(pm, "_process_group")
    # The live shared analysis helpers are retained.
    assert hasattr(pm, "compute_agg_mats")
    assert hasattr(pm, "compute_retrieval_rows")


@pytest.mark.parametrize(
    "module",
    [
        "scripts.embedding_research.strategy_binned._calibrate",
        "scripts.embedding_research.strategy_binned._features",
        "scripts.embedding_research.db.patch",
    ],
)
def test_obsolete_dead_modules_removed(module: str) -> None:
    """The fully-dead module files (dead-table producers/readers) are no longer importable."""
    assert importlib.util.find_spec(module) is None


def test_db_no_longer_exports_patch_features_done() -> None:
    """The patch_features reader export is dropped from the db facade."""
    assert not hasattr(_db, "patch_features_done")
    assert "patch_features_done" not in _db.__all__


# --------------------------------------------------------------------------- #
# 1a. Stale synthetic "median" optimizer rep rejected (repair message -> medoid)
# --------------------------------------------------------------------------- #


def test_stale_synthetic_median_optimizer_rep_rejected_with_repair_message() -> None:
    """A stale ``rep_type="median"`` is rejected loudly, never silently accepted.

    Ground: R7 / optimizer vocabulary. The message must point the user at the observed
    source rep ``medoid`` (never a coordinate-wise synthetic bin vector).
    """
    with pytest.raises(ValueError, match="medoid"):
        _const.validate_optimizer_representation("median")
    # The observed-source medoid is the accepted labelled form on the optimizer path.
    assert _const.validate_optimizer_representation("medoid") == "medoid"


# --------------------------------------------------------------------------- #
# 1b. Medoid = observed source row on the optimizer/rep path (no synthetic)
# --------------------------------------------------------------------------- #


def test_optimizer_rep_medoid_is_observed_source_row_not_synthetic() -> None:
    """The optimizer ``rep_type="medoid"`` payload is an ACTUAL observed row.

    The optimizer selects its bin rep via ``_pool_segment(...)[rep_type]``. With the default
    config ``rep_types=["medoid"]`` the only emitted rep is ``medoid``, whose ``vec_raw`` equals
    the observed source patch at ``selected_global_idx`` and is NOT the coordinate-wise median.
    """
    raw_rows = np.asarray(
        [
            [1.0, 0.0, 0.0],
            [0.9, 0.1, 0.0],
            [0.2, 0.8, 0.1],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )
    raw = RawTensor(raw_rows)
    unit = UnitTensor(raw_rows.copy())
    indices = [0, 1, 2, 3]

    pooled = _pool_segment(raw, unit, indices)
    # Default rep set is the observed medoid only (config [pooling] rep_types=["medoid"]).
    assert set(pooled) == {"medoid"}

    m = pooled["medoid"]
    gi = m["selected_global_idx"]
    assert gi in indices
    assert np.allclose(m["vec_raw"].data, raw.data[gi])
    # It is an observed row, never the coordinate-wise synthetic median of the segment.
    median = np.median(raw.data[indices], axis=0)
    assert not np.allclose(m["vec_raw"].data, median)


# --------------------------------------------------------------------------- #
# 1c + 4. Default catalog+analyze run: no optimizer prerequisite, no dead rows
# --------------------------------------------------------------------------- #


def _unit_rows(rng: np.random.Generator, n: int, d: int) -> np.ndarray:
    """Deterministic float32 L2-unit rows (frozen-stream stand-in)."""
    m = rng.standard_normal((n, d)) * 1.5
    m[0] += 3.0
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (m / norms).astype(np.float32)


def test_default_catalog_analyze_run_needs_no_optimizer_and_writes_no_dead_rows(con, tmp_path) -> None:
    """A default catalog+analyze run (optimizer disabled/absent) succeeds and writes no dead rows.

    The shipped ``[optimization] enabled=false`` means the default path must not require optimizer
    output or artifacts. Running the catalog-first analyze path to completion on a fresh store proves
    the no-prerequisite property, and asserts the three audited dead tables stay empty (their only
    writers were removed in P3-S4).
    """
    from scripts.embedding_research import catalog
    from scripts.embedding_research.common import catalog_analysis as ca
    from scripts.embedding_research.streams.store import StreamStore

    song_ids = ["s1", "s2", "s3", "s4"]
    artists = {"s1": "A", "s2": "A", "s3": "B", "s4": "B"}

    out = tmp_path / "out"
    store = StreamStore(con, output_root=str(out))
    rng = np.random.default_rng(7)
    for sid in song_ids:
        store.publish(sid, "effnet", _unit_rows(rng, 10, 6), run_id="run-embed")
    store.reconcile()

    rep = catalog.build_segmentation_catalog(
        con,
        store,
        [
            catalog.SegConfigInput(
                backbone="effnet",
                bin_mode="temporal_global",
                threshold_configured=0.7,
                threshold_effective=0.7,
            )
        ],
        song_ids,
        "run-cat",
        verify=True,
    )
    assert rep.verify_ok is True

    cfg = ca.CatalogAnalysisConfig(run_id="run-an", backbone="effnet", song_ids=song_ids, artists=artists)
    result = ca.analyze_catalog_corpus(store, con, cfg)
    assert result.finite is True

    for table in ("binned_song_stats", "binned_calibration", "patch_features"):
        count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert count == 0, f"{table} should have zero rows on a default-path run, got {count}"
