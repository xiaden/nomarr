"""Compact durable segmentation-catalog build tests (Plan C, P1-S5).

These exercise :func:`catalog.build_segmentation_catalog` against the COMPACT
filesystem snapshot model (catalog_storage ``catalog.duckdb`` staging seams), the
one-load-per-(song, backbone) producer contract, deterministic canonical-hash
``config_id`` allocation, per-(config, song) partial-failure capture, mask-driven
searchable/weight semantics, and post-build ``verify`` drift detection.  The suite is
self-contained: it never touches the disposable research DB, audio, models, or CUDA
(fake current-stream + whole-song-mask loaders drive every build).  The HARD-CUT compact
invariants are asserted directly: no ``seg_membership`` table, no indexes / PK / UNIQUE,
exactly the five compact tables.
"""

from __future__ import annotations

import importlib
import math

import numpy as np
import pytest

from scripts.embedding_research import catalog
from scripts.embedding_research.catalog_storage import connect
from scripts.embedding_research.helpers.segmentation import (
    reconstruct_searchable_indices,
    select_observed_medoid_source_index,
)

COMPACT_TABLES = ("catalog_metadata", "seg_config", "catalog_song", "seg_meta", "run_provenance")


class FakeStreamStore:
    """A duck-typed current-stream loader: ``.load(song, backbone) -> float32[P,D] | None``.

    Mirrors the real ``make_current_stream_resolver(...).load`` seam: missing streams
    return ``None`` (fails closed) instead of raising.
    """

    def __init__(self, streams: dict[tuple[str, str], np.ndarray]) -> None:
        self._streams = streams

    def load(self, song_id: str, backbone: str):
        return self._streams.get((song_id, backbone))


class FakeMaskStore:
    """A duck-typed whole-song mask loader: ``.load(song_id) -> uint8[P] | None``."""

    def __init__(self, masks: dict[str, np.ndarray] | None = None) -> None:
        self._masks = masks or {}

    def load(self, song_id: str):
        return self._masks.get(song_id)  # None => no silence for that song


def _song_mat(patch_counts: list[int], *, dim: int = 4, seed: float = 1.0) -> np.ndarray:
    """Deterministic song stream: alternating ``+x`` / ``-x`` unit blocks.

    Adjacent opposite-sign blocks are distance 2 apart, so a ``threshold_effective`` of
    ``1.0`` hard-splits between blocks while identical rows inside a block never split.
    Every patch is finite and nonzero (segmentation-safe).
    """
    sign = 1.0
    rows: list[np.ndarray] = []
    for count in patch_counts:
        block = np.zeros((count, dim), dtype=np.float32)
        block[:, 0] = sign
        block *= seed
        rows.append(block)
        sign *= -1.0
    return np.concatenate(rows, axis=0)


def _open_snapshot(tmp_path, run_id: str):
    path = tmp_path / "catalogs" / f".staging-{run_id}" / "catalog.duckdb"
    return connect(path, read_only=True), path


def _tables(con) -> set[str]:
    rows = con.execute("SELECT table_name FROM information_schema.tables").fetchall()
    return {r[0] for r in rows}


def _cfg(threshold: float, *, backbone: str = "effnet", bin_mode: str = "direct") -> dict:
    return {
        "backbone": backbone,
        "bin_mode": bin_mode,
        "threshold_configured": threshold,
        "threshold_effective": threshold,
    }


# --------------------------------------------------------------------------- #
# Schema / HARD-CUT invariants                                                #
# --------------------------------------------------------------------------- #


def test_build_persists_only_compact_tables_no_membership_no_indexes(tmp_path):
    fs = FakeStreamStore({("s1", "effnet"): _song_mat([5, 3]), ("s2", "effnet"): _song_mat([4, 5, 4])})
    rep = catalog.build_segmentation_catalog(
        fs, FakeMaskStore(), [_cfg(1.0)], ["s1", "s2"], output_root=str(tmp_path), run_id="run-a", verify=True
    )
    assert rep.verify_ok is True
    with _open_snapshot(tmp_path, "run-a")[0] as con:
        tabs = _tables(con)
        assert set(COMPACT_TABLES) <= tabs
        assert "seg_membership" not in tabs  # HARD-CUT: no per-patch membership table
        assert con.execute("SELECT count(*) FROM seg_config").fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM catalog_song").fetchone()[0] == 2
        # s1 (+x/-x, trailing sign never re-joins): 2 structural segments; s2
        # (+x/-x(5>window)/+x, middle excursion hard-splits): 3 structural segments.
        assert con.execute("SELECT count(*) FROM seg_meta").fetchone()[0] == 5
        assert con.execute("SELECT count(*) FROM catalog_metadata").fetchone()[0] == 1
        # No application indexes / PK / UNIQUE are created (duckdb_indexes stays empty).
        assert con.execute("SELECT * FROM duckdb_indexes()").fetchall() == []


# --------------------------------------------------------------------------- #
# One-load-per-(song, backbone) pass + evidence                               #
# --------------------------------------------------------------------------- #


def test_one_stream_load_per_song_shared_across_threshold_configs(tmp_path):
    """Two thresholds for one backbone => one stream load per (song, backbone), not per config."""
    fs = FakeStreamStore({("s1", "effnet"): _song_mat([5, 3]), ("s2", "effnet"): _song_mat([8])})
    rep = catalog.build_segmentation_catalog(
        fs,
        FakeMaskStore(),
        [_cfg(0.4), _cfg(0.9)],
        ["s1", "s2"],
        output_root=str(tmp_path),
        run_id="run-b",
        verify=True,
    )
    assert rep.verify_ok is True
    assert rep.stream_loads == 2  # two (song, backbone) pairs, each loaded once
    assert dict(rep.load_evidence) == {("s1", "effnet"): 1, ("s2", "effnet"): 1}
    assert rep.songs_built == 2
    # Both configs built both songs (configs share the single load).
    assert rep.total_catalog_songs == 4
    with _open_snapshot(tmp_path, "run-b")[0] as con:
        assert con.execute("SELECT count(*) FROM catalog_song").fetchone()[0] == 4
        assert con.execute("SELECT count(*) FROM seg_config").fetchone()[0] == 2
        assert "seg_membership" not in _tables(con)


def test_all_explicit_configs_present_with_deterministic_config_ids(tmp_path):
    fs = FakeStreamStore({("s1", "effnet"): _song_mat([8])})
    thresholds = (0.4, 0.6, 0.9)
    rep = catalog.build_segmentation_catalog(
        fs,
        FakeMaskStore(),
        [_cfg(t) for t in thresholds],
        ["s1"],
        output_root=str(tmp_path),
        run_id="run-c",
        verify=True,
    )
    assert len(rep.configs) == 3
    assert [o.config_id for o in rep.configs] == [1, 2, 3]
    assert len({o.canonical_config_hash for o in rep.configs}) == 3
    with _open_snapshot(tmp_path, "run-c")[0] as con:
        rows = con.execute(
            "SELECT config_id, threshold_effective, canonical_config_hash FROM seg_config ORDER BY config_id"
        ).fetchall()
        assert [r[0] for r in rows] == [1, 2, 3]
        assert {float(r[1]) for r in rows} == set(thresholds)
        assert len({r[2] for r in rows}) == 3


def test_duplicate_canonical_config_collapses_to_single_row(tmp_path):
    """Two descriptors with identical canonical identity (differing only in semantics text) collapse."""
    base = _cfg(0.7)
    a = dict(base, semantics="direct_l2")
    b = dict(base, semantics="whatever-cosmetic")
    fs = FakeStreamStore({("s1", "effnet"): _song_mat([6, 4])})
    rep = catalog.build_segmentation_catalog(
        fs, FakeMaskStore(), [a, b], ["s1"], output_root=str(tmp_path), run_id="run-d", verify=True
    )
    assert len(rep.configs) == 1
    with _open_snapshot(tmp_path, "run-d")[0] as con:
        assert con.execute("SELECT count(*) FROM seg_config").fetchone()[0] == 1
        assert con.execute("SELECT count(*) FROM catalog_song").fetchone()[0] == 1


def test_bin_mode_direct_is_accepted_without_dist_fn_validation(tmp_path):
    """'direct' bin_mode is a legal compact config (NOT validated against DIST_FNS)."""
    fs = FakeStreamStore({("s1", "effnet"): _song_mat([8])})
    rep = catalog.build_segmentation_catalog(
        fs,
        FakeMaskStore(),
        [_cfg(1.0, bin_mode="direct")],
        ["s1"],
        output_root=str(tmp_path),
        run_id="run-e",
        verify=True,
    )
    assert rep.total_catalog_songs == 1
    with _open_snapshot(tmp_path, "run-e")[0] as con:
        assert con.execute("SELECT bin_mode FROM seg_config").fetchone()[0] == "direct"


# --------------------------------------------------------------------------- #
# Exclusion / empty / partial-failure semantics                               #
# --------------------------------------------------------------------------- #


def test_song_lacking_ready_stream_is_excluded_not_failed(tmp_path):
    """A requested song with no ready stream is excluded (counted), never a failure."""
    fs = FakeStreamStore({("s1", "effnet"): _song_mat([8])})  # s2 has no ready stream
    rep = catalog.build_segmentation_catalog(
        fs, FakeMaskStore(), [_cfg(1.0)], ["s1", "s2"], output_root=str(tmp_path), run_id="run-f", verify=True
    )
    assert len(rep.configs) == 1
    outcome = rep.configs[0]
    assert outcome.songs_eligible == 1
    assert outcome.excluded_songs == 1
    assert outcome.songs_completed == 1
    assert outcome.failed_songs == ()
    assert outcome.status == "complete"
    with _open_snapshot(tmp_path, "run-f")[0] as con:
        songs = {r[0] for r in con.execute("SELECT song_id FROM catalog_song").fetchall()}
        assert songs == {"s1"}  # excluded s2 never written


def test_no_ready_stream_for_backbone_yields_empty_status(tmp_path):
    """Zero ready streams for a backbone => empty outcome; config identity still persists."""
    fs = FakeStreamStore({})  # nothing ready for 'effnet'
    rep = catalog.build_segmentation_catalog(
        fs, FakeMaskStore(), [_cfg(1.0)], ["s1"], output_root=str(tmp_path), run_id="run-g", verify=True
    )
    outcome = rep.configs[0]
    assert outcome.status == "empty"
    assert outcome.songs_eligible == 0
    assert outcome.songs_completed == 0
    assert rep.status == "partial"
    with _open_snapshot(tmp_path, "run-g")[0] as con:
        assert con.execute("SELECT count(*) FROM seg_config").fetchone()[0] == 1  # identity independent of readiness
        assert con.execute("SELECT count(*) FROM catalog_song").fetchone()[0] == 0


def test_per_song_failure_is_captured_and_status_partial(tmp_path, monkeypatch):
    """A raising per-(config, song) persistence leaves a failed_songs entry, never empty."""
    fs = FakeStreamStore({("s1", "effnet"): _song_mat([8]), ("s2", "effnet"): _song_mat([8])})
    original = catalog._build_and_persist_song

    def flaky(con, **kwargs):
        if kwargs["song_id"] == "s2":
            raise RuntimeError("simulated persistence failure")
        return original(con, **kwargs)

    monkeypatch.setattr(catalog, "_build_and_persist_song", flaky)
    rep = catalog.build_segmentation_catalog(
        fs, FakeMaskStore(), [_cfg(1.0)], ["s1", "s2"], output_root=str(tmp_path), run_id="run-h", verify=True
    )
    assert rep.status == "partial"
    outcome = rep.configs[0]
    assert outcome.status == "partial"
    assert outcome.songs_eligible == 2
    assert outcome.songs_completed == 1
    assert outcome.failed_songs == ("s2:RuntimeError",)
    with _open_snapshot(tmp_path, "run-h")[0] as con:
        songs = {r[0] for r in con.execute("SELECT song_id FROM catalog_song").fetchall()}
        assert songs == {"s1"}  # s2's partial write never landed


# --------------------------------------------------------------------------- #
# Mask semantics / metadata-only songs                                        #
# --------------------------------------------------------------------------- #


def test_mask_silence_reduces_searchable_total_and_persists_weight(tmp_path):
    """Masked (silent) patches are searchable-excluded; weights reflect remaining mass."""
    mat = _song_mat([5])
    mask = np.ones(5, dtype=np.uint8)
    mask[2] = 0  # one silent patch inside the single segment
    fs = FakeStreamStore({("s1", "effnet"): mat})
    rep = catalog.build_segmentation_catalog(
        fs, FakeMaskStore({"s1": mask}), [_cfg(1.0)], ["s1"], output_root=str(tmp_path), run_id="run-i", verify=True
    )
    assert rep.total_segments == 1
    with _open_snapshot(tmp_path, "run-i")[0] as con:
        assert con.execute("SELECT total_searchable_count FROM catalog_song").fetchone()[0] == 4
        seg = con.execute(
            "SELECT searchable_count, search_medoid_source_patch_idx, searchable_weight FROM seg_meta"
        ).fetchone()
        assert seg[0] == 4  # patch 2 masked out
        assert seg[1] == 0  # smallest source index among the +x block
        assert seg[2] == pytest.approx(1.0)  # 4/4 mass in this single segment


def test_fully_silent_song_is_metadata_only_no_seg_rows(tmp_path):
    """A fully masked stream persists a catalog_song row (metadata_only), never searchable."""
    fs = FakeStreamStore({("s1", "effnet"): _song_mat([5])})
    mask = np.zeros(5, dtype=np.uint8)  # fully silent
    rep = catalog.build_segmentation_catalog(
        fs, FakeMaskStore({"s1": mask}), [_cfg(1.0)], ["s1"], output_root=str(tmp_path), run_id="run-j", verify=True
    )
    assert rep.verify_ok is True
    assert rep.total_segments == 0
    with _open_snapshot(tmp_path, "run-j")[0] as con:
        row = con.execute("SELECT total_searchable_count, status FROM catalog_song").fetchone()
        assert row[0] == 0
        assert row[1] == "metadata_only"
        assert con.execute("SELECT count(*) FROM seg_meta").fetchone()[0] == 0


# --------------------------------------------------------------------------- #
# Validation / verification error paths                                       #
# --------------------------------------------------------------------------- #


def test_validation_errors_raise_and_error_chain(tmp_path):
    fs = FakeStreamStore({("s1", "effnet"): _song_mat([8])})
    fm = FakeMaskStore()
    with pytest.raises(catalog.CatalogValidationError):
        catalog.build_segmentation_catalog(fs, fm, [], ["s1"], output_root=str(tmp_path), run_id="r")
    with pytest.raises(catalog.CatalogValidationError):
        catalog.build_segmentation_catalog(fs, fm, [_cfg(1.0)], [], output_root=str(tmp_path), run_id="r")
    with pytest.raises(catalog.CatalogValidationError):
        catalog.build_segmentation_catalog(fs, fm, [_cfg(1.0)], ["s1"], output_root=str(tmp_path), run_id="   ")
    assert issubclass(catalog.CatalogValidationError, catalog.CatalogError)
    assert issubclass(catalog.CatalogError, RuntimeError)
    assert issubclass(catalog.CatalogVerificationError, catalog.CatalogError)


def test_verify_drift_raises_catalog_verification_error(tmp_path, monkeypatch):
    """verify=True raises CatalogVerificationError when the snapshot is internally inconsistent."""
    fs = FakeStreamStore({("s1", "effnet"): _song_mat([5, 3])})
    original = catalog._write_catalog_song_row

    def corrupt_total(con, **kwargs):
        result = original(con, **kwargs)
        con.execute(
            "UPDATE catalog_song SET total_searchable_count = total_searchable_count + 1 "
            "WHERE config_id = ? AND song_id = ?",
            [kwargs["config_id"], kwargs["song_id"]],
        )
        return result

    monkeypatch.setattr(catalog, "_write_catalog_song_row", corrupt_total)
    with pytest.raises(catalog.CatalogVerificationError):
        catalog.build_segmentation_catalog(
            fs, FakeMaskStore(), [_cfg(1.0)], ["s1"], output_root=str(tmp_path), run_id="run-k", verify=True
        )


# --------------------------------------------------------------------------- #
# Deterministic rerun equivalence                                             #
# --------------------------------------------------------------------------- #


def test_rerun_produces_deterministic_equivalent_snapshot(tmp_path):
    """Two identical builds into distinct staging snapshots produce equal content hashes."""
    streams = {("s1", "effnet"): _song_mat([5, 3]), ("s2", "effnet"): _song_mat([8])}
    fs = FakeStreamStore(streams)
    rep_a = catalog.build_segmentation_catalog(
        fs,
        FakeMaskStore(),
        [_cfg(0.5), _cfg(0.9)],
        ["s1", "s2"],
        output_root=str(tmp_path),
        run_id="run-A",
        verify=True,
    )
    rep_b = catalog.build_segmentation_catalog(
        fs,
        FakeMaskStore(),
        [_cfg(0.5), _cfg(0.9)],
        ["s1", "s2"],
        output_root=str(tmp_path),
        run_id="run-B",
        verify=True,
    )
    assert rep_a.exact_hash == rep_b.exact_hash
    assert rep_a.search_hash == rep_b.search_hash

    with _open_snapshot(tmp_path, "run-A")[0] as con_a, _open_snapshot(tmp_path, "run-B")[0] as con_b:
        # Content-deterministic rows are run_id-free for catalog_song; compare them wholesale.
        assert (
            con_a.execute("SELECT * FROM catalog_song ORDER BY config_id, song_id").fetchall()
            == con_b.execute("SELECT * FROM catalog_song ORDER BY config_id, song_id").fetchall()
        )
        # seg_config/seg_meta carry run-scoped identity/provenance; compare everything else.
        assert (
            con_a.execute(
                "SELECT config_id, backbone, bin_mode, threshold_configured, threshold_effective, "
                "threshold_semantics, outlier_window, strategy_version, canonical_config_hash "
                "FROM seg_config ORDER BY config_id"
            ).fetchall()
            == con_b.execute(
                "SELECT config_id, backbone, bin_mode, threshold_configured, threshold_effective, "
                "threshold_semantics, outlier_window, strategy_version, canonical_config_hash "
                "FROM seg_config ORDER BY config_id"
            ).fetchall()
        )
        assert (
            con_a.execute(
                "SELECT config_id, song_id, seg_id, start_idx, end_idx, absorbed_indices, absorbed_count, "
                "searchable_count, search_medoid_source_patch_idx, searchable_weight, structural_identity "
                "FROM seg_meta ORDER BY config_id, song_id, seg_id"
            ).fetchall()
            == con_b.execute(
                "SELECT config_id, song_id, seg_id, start_idx, end_idx, absorbed_indices, absorbed_count, "
                "searchable_count, search_medoid_source_patch_idx, searchable_weight, structural_identity "
                "FROM seg_meta ORDER BY config_id, song_id, seg_id"
            ).fetchall()
        )


# --------------------------------------------------------------------------- #
# Model / audio / CUDA call guard                                             #
# --------------------------------------------------------------------------- #


def test_build_completes_with_zero_audio_model_cuda_calls(tmp_path, monkeypatch):
    """The compact producer never reaches audio discovery, ONNX, or CUDA, even under verify."""
    from scripts.embedding_research import config as _config

    def boom(*_args, **_kwargs):  # pragma: no cover - asserts the path is never reached
        raise AssertionError("audio/model/CUDA path must never run during a compact catalog build")

    monkeypatch.setattr(_config, "discover_audio", boom, raising=False)
    for mod_name in ("onnxruntime", "torch"):
        try:
            mod = importlib.import_module(mod_name)
        except Exception:  # not installed -> cannot be reached anyway
            continue
        if mod_name == "onnxruntime" and hasattr(mod, "InferenceSession"):
            monkeypatch.setattr(mod, "InferenceSession", boom, raising=False)
        if mod_name == "torch" and hasattr(mod, "cuda"):
            monkeypatch.setattr(mod.cuda, "is_available", boom, raising=False)
    fs = FakeStreamStore({("s1", "effnet"): _song_mat([8])})
    rep = catalog.build_segmentation_catalog(
        fs, FakeMaskStore(), [_cfg(1.0)], ["s1"], output_root=str(tmp_path), run_id="run-l", verify=True
    )
    assert rep.verify_ok is True


# --------------------------------------------------------------------------- #
# Persisted catalog rows: no NaN/Infinity anywhere + medoid == observed recompute #
# --------------------------------------------------------------------------- #


def _finite(value) -> bool:
    """True when *value* is None or a finite float/int."""
    return value is None or math.isfinite(float(value))


def test_built_snapshot_rows_finite_and_medoid_is_observed_source_index(tmp_path):
    """Every durable numeric catalog row is finite, and each persisted medoid equals the
    independently-recomputed max-centrality observed source index over the segment's
    reconstructed searchable set (real silence mask, not the structural range).

    Mirrors the DD no-NaN/Infinity ledger item at the compact snapshot level (families
    (i)/(h)): nothing in seg_config / catalog_song / seg_meta may carry NaN/Infinity, and
    the persisted ``search_medoid_source_patch_idx`` must be the OBSERVED source index
    recomputed from the same frozen stream + mask + absorbed exceptions — never a
    synthetic/geometry-derived value.
    """
    mat = _song_mat([5, 3])  # +x block [0,5), -x block [5,8); each row unit length
    mask = np.ones(8, dtype=np.uint8)
    mask[2] = 0  # silent inside seg [0,5)
    mask[6] = 0  # silent inside seg [5,8)
    fs = FakeStreamStore({("s1", "effnet"): mat})
    rep = catalog.build_segmentation_catalog(
        fs,
        FakeMaskStore({"s1": mask}),
        [_cfg(1.0)],
        ["s1"],
        output_root=str(tmp_path),
        run_id="run-medoid",
        verify=True,
    )
    assert rep.verify_ok is True
    unit_matrix = catalog._l2_normalize_rows(mat)

    with _open_snapshot(tmp_path, "run-medoid")[0] as con:
        # --- No NaN/Infinity in the durable seg_config numeric columns. ---
        for row in con.execute(
            "SELECT threshold_configured, threshold_effective, outlier_window, strategy_version FROM seg_config"
        ).fetchall():
            assert all(_finite(v) for v in row)
        # configured == effective exactly (single direct-L2 contract).
        cfg_row = con.execute("SELECT threshold_configured, threshold_effective FROM seg_config").fetchone()
        assert float(cfg_row[0]) == float(cfg_row[1]) == 1.0

        # --- No NaN/Infinity in catalog_song numeric columns; total agrees. ---
        song_rows = con.execute("SELECT patch_count, total_searchable_count FROM catalog_song").fetchall()
        assert len(song_rows) == 1
        assert all(_finite(v) for v in song_rows[0])
        assert int(song_rows[0][1]) == 6  # 8 patches - 2 silent

        # --- config_id + per-(config, song) structural rows. ---
        config_id = catalog.compact_configs_by_backbone(con, "effnet")[0].config_id
        segs = catalog.compact_segments_by_config_song(con, config_id, "s1")

        seg_rows = con.execute(
            "SELECT start_idx, end_idx, absorbed_count, searchable_count, "
            "search_medoid_source_patch_idx, searchable_weight FROM seg_meta ORDER BY seg_id"
        ).fetchall()
        # --- No NaN/Infinity in any seg_meta numeric column. ---
        for row in seg_rows:
            assert all(_finite(v) for v in row)

        total_searchable = int(song_rows[0][1])
        assert sum(int(r[3]) for r in seg_rows) == total_searchable
        # weights sum to one over the searchable mass.
        assert sum(float(r[5]) for r in seg_rows) == pytest.approx(1.0)
        assert all(0.0 <= float(r[5]) <= 1.0 for r in seg_rows)

        # --- Persisted medoid == independent observed-medoid recompute over the real mask. ---
        expected = {
            # seg [0,5): searchable {0,1,3,4} (patch 2 silent) -> smallest-index +x row 0.
            # seg [5,8): searchable {5,7} (patch 6 silent) -> smallest-index -x row 5.
            0: 0,
            1: 5,
        }
        for seg in segs:
            searchable = reconstruct_searchable_indices(seg, mask, patch_count=int(mat.shape[0]))
            recomputed_medoid, _centrality = select_observed_medoid_source_index(unit_matrix, searchable)
            assert seg.search_medoid_source_patch_idx == recomputed_medoid == expected[int(seg.seg_id)]
            assert seg.searchable_count == len(searchable)
            # recomputed medoid is an OBSERVED, finite, in-range source index.
            assert recomputed_medoid is not None
            assert 0 <= recomputed_medoid < int(mat.shape[0])
