"""Spec-first tests for the ACTIVE canonical catalog-scoped head analysis (P1-S1).

Covers ``common.head_analysis.run_shared_catalog_head_analysis`` under the corrective
EXACT ``M_g`` semantics (DD L238 / parts CONTRACTS §E is a cross-consumer invariant):

* membership comes ONLY from each compact segment's exact reconstructed searchable set
  ``M_g = structural[start_idx, end_idx) - absorbed_indices`` reconstructed via
  ``reconstruct_searchable_indices``; ``end_idx`` is exclusive (never inclusive), absorbed
  rows are excluded, and the runner gathers exactly those source indices — never an
  inclusive ``[start_idx, end_idx]`` range and never a ``seg_membership`` table;
* gather happens through ``HeadStreamStore.batch_gather`` over the exact searchable
  source indices, per-head columns sliced by ``dim_by_head`` in canonical head order;
* the class-1 head value is taken from ``act[1]`` (never ``act[0]``);
* config eligibility is canonical/config-keyed (direct-L2 PTC semantics + bin mode +
  strategy version + non-empty ``canonical_config_hash``); ``alias_of_config_id`` /
  durable aliases / calibration columns are never read;
* default ``config_ids=None`` selects the canonical compact configs of the primary
  backbone (effnet);
* the manifest is JSON-safe and carries deterministic per-(config, head) coverage,
  skip/error reasons and a finite status; pooled values are transient (never persisted);
* the legacy ``pool_head_outputs_over_ptc_boundaries`` / ``run_shared_ptc_head_pooling``
  symbols are gone from ``common.head_analysis``.

Runner tests build a real COMPACT snapshot through the shared ``compact_catalog_factory``
fixture (no ``seg_membership`` / ``alias_of_config_id`` / ``calibration_record`` seeding)
and overwrite the compact ``seg_meta`` rows with hand-controlled structural ranges to pin
exact ``M_g`` membership deterministically.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from scripts.embedding_research.catalog import SegConfigInput
from scripts.embedding_research.common import head_analysis as head_mod
from scripts.embedding_research.common.head_analysis import (
    BOUNDARY_SOURCE_CATALOG,
    HeadAnalysisConfigRecord,
    run_shared_catalog_head_analysis,
)
from scripts.embedding_research.helpers.thresholds import PTC_STRATEGY_VERSION

_RESEARCH_DIR = __import__("pathlib").Path(__file__).resolve().parents[1]

_CLASS1 = 1

#: Shared compact snapshot stream: 6 patches x 3 cols (finite rows).
_STREAM = np.array(
    [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ],
    dtype=np.float32,
)
_PATCH_COUNT = 6


def _effnet_config() -> SegConfigInput:
    return SegConfigInput(
        backbone="effnet",
        bin_mode="temporal_global",
        threshold_configured=0.7,
        threshold_effective=0.7,
        semantics="direct_l2",
        outlier_window=3,
        strategy_version=PTC_STRATEGY_VERSION,
    )


# ---------------------------------------------------------------------------
# runner fakes + capture
# ---------------------------------------------------------------------------


class _FakeHeadStore:
    """Ready single-head stream whose gathered rows are the source patch ids (row value
    == its source patch index).  Also records each ``batch_gather`` request."""

    def __init__(self) -> None:
        self.gather_requests: list[list[int]] = []

    def lookup(self, song_id, backbone):  # noqa: ARG002 - interface-parity fake
        import types

        return types.SimpleNamespace(head_ids="mood", dim_by_head="mood=3")

    def batch_gather(self, song_id, backbone, source_patch_indices):  # noqa: ARG002 - interface-parity fake
        self.gather_requests.append([int(i) for i in source_patch_indices])
        return np.asarray(
            [[float(i), float(i) + 1.0, float(i) + 2.0] for i in source_patch_indices],
            dtype=np.float32,
        )


class _MissingStreamHeadStore:
    """Serves a ready frozen ``mood`` head for served songs and NO usable frozen head for
    each ``missing`` song: either an empty-head record (absent stream) or a lookup
    exception (unreadable stream), mirroring partial stream/catalog misalignment.

    Records each ``batch_gather``/``lookup`` request so an affected-but-served song is
    easy to distinguish from a song that never reached the pool path.
    """

    def __init__(self, *, missing=(), raise_on_lookup=False):
        self.missing = set(missing)
        self.raise_on_lookup = raise_on_lookup
        self.gather_requests: list[list[int]] = []
        self.lookup_requests: list[str] = []

    def lookup(self, song_id, backbone):  # noqa: ARG002 - interface-parity fake
        import types

        self.lookup_requests.append(str(song_id))
        if song_id in self.missing:
            if self.raise_on_lookup:
                raise RuntimeError(f"no frozen head stream indexed for {song_id}")
            return types.SimpleNamespace(head_ids="", dim_by_head="")
        return types.SimpleNamespace(head_ids="mood", dim_by_head="mood=3")

    def batch_gather(self, song_id, backbone, source_patch_indices):  # noqa: ARG002 - interface-parity fake
        self.gather_requests.append([int(i) for i in source_patch_indices])
        return np.asarray(
            [[float(i), float(i) + 1.0, float(i) + 2.0] for i in source_patch_indices],
            dtype=np.float32,
        )


class _PoolCapture:
    """Records the per-segment transient pooling inputs AND the pooled class-1 value."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []


def _make_pool_capture(monkeypatch: pytest.MonkeyPatch) -> _PoolCapture:
    cap = _PoolCapture()
    real = head_mod._pool_segment_heads

    def _wrapped(rows, member_patch_indices, *, segment_id):
        pooled = real(rows, member_patch_indices, segment_id=segment_id)
        cap.calls.append(
            (
                int(segment_id),
                tuple(int(i) for i in member_patch_indices),
                pooled.weight,
                np.asarray(rows, dtype=np.float32).copy(),
                pooled.class1,
            )
        )
        return pooled

    monkeypatch.setattr(head_mod, "_pool_segment_heads", _wrapped)
    return cap


def _build_harness(compact_catalog_factory, con, tmp_path):
    """Build ONE compact snapshot over song s1 and return (harness, config_id)."""
    harness = compact_catalog_factory(
        con,
        tmp_path,
        streams={("s1", "effnet"): _STREAM},
        configs=[_effnet_config()],
        song_ids=["s1"],
    )
    from scripts.embedding_research.catalog import compact_configs_by_backbone

    config_rows = compact_configs_by_backbone(harness.con, "effnet")
    return harness, config_rows[0].config_id


def _set_patch_count(harness, config_id, song: str, patch_count: int) -> None:
    harness.con.execute(
        "UPDATE catalog_song SET patch_count = ? WHERE config_id = ? AND song_id = ?",
        [patch_count, config_id, song],
    )


def _craft_segment(
    harness,
    config_id,
    song: str,
    *,
    seg_id: int,
    start_idx: int,
    end_idx: int,
    absorbed=(),
) -> None:
    """Replace the (config, song) seg rows with one exact structural segment."""
    harness.con.execute("DELETE FROM seg_meta WHERE config_id = ? AND song_id = ?", [config_id, song])
    absorbed_text = "[" + ",".join(str(i) for i in sorted(absorbed)) + "]"
    harness.con.execute(
        "INSERT INTO seg_meta (config_id, song_id, seg_id, start_idx, end_idx, absorbed_indices, "
        "absorbed_count, searchable_count, searchable_weight, structural_identity, provenance) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [config_id, song, seg_id, start_idx, end_idx, absorbed_text, len(absorbed), 0, 1.0, "seg", "seed"],
    )


def _run(harness, store, cfg_id, **overrides):
    kwargs = {"config_ids": [cfg_id], "song_ids": ["s1"], "heads": ["mood"], "run_id": "r"}
    kwargs.update(overrides)
    return run_shared_catalog_head_analysis(harness.con, store, **kwargs)


# ---------------------------------------------------------------------------
# exact-M_g membership (absorbed exclusion, end-exclusive range)
# ---------------------------------------------------------------------------


def test_runner_pools_exact_searchable_mg_never_inclusive(con, tmp_path, compact_catalog_factory, monkeypatch) -> None:
    """Membership is exact ``M_g``; ``end_idx`` is exclusive and absorbed rows excluded.

    Segment ``[0, 5)`` with absorbed index 1 => ``M_g = {0, 2, 3, 4}`` (index 5 is outside
    the end-exclusive range and never gathered).  The runner must gather exactly those
    four source indices and pool them once with weight 4.
    """
    harness, cfg_id = _build_harness(compact_catalog_factory, con, tmp_path)
    try:
        _set_patch_count(harness, cfg_id, "s1", _PATCH_COUNT)
        _craft_segment(harness, cfg_id, "s1", seg_id=0, start_idx=0, end_idx=5, absorbed=(1,))

        cap = _make_pool_capture(monkeypatch)
        store = _FakeHeadStore()
        manifest = _run(harness, store, cfg_id)

        assert manifest.done == 1 and manifest.errors == 0 and manifest.finite is True
        # gather request is the exact searchable M_g — absorbed 1 and the exclusive end 5 absent.
        assert store.gather_requests == [[0, 2, 3, 4]]
        # exactly one segment pooled over M_g.
        assert len(cap.calls) == 1
        seg_id, indices, weight, rows, _class1 = cap.calls[0]
        assert seg_id == 0
        assert indices == (0, 2, 3, 4), "absorbed(1) excluded and end_idx(5) not inclusive"
        assert weight == 4, "weight is the searchable count |M_g|"
        np.testing.assert_allclose(
            rows,
            np.array([[0.0, 1.0, 2.0], [2.0, 3.0, 4.0], [3.0, 4.0, 5.0], [4.0, 5.0, 6.0]], np.float32),
            rtol=1e-6,
        )
    finally:
        harness.close()


def test_runner_class1_is_act1_never_act0(con, tmp_path, compact_catalog_factory, monkeypatch) -> None:
    """The pooled head value is the mean of ``act[1]`` (never ``act[0]``)."""
    harness, cfg_id = _build_harness(compact_catalog_factory, con, tmp_path)
    try:
        _set_patch_count(harness, cfg_id, "s1", _PATCH_COUNT)
        _craft_segment(harness, cfg_id, "s1", seg_id=0, start_idx=0, end_idx=6, absorbed=())

        cap = _make_pool_capture(monkeypatch)
        store = _FakeHeadStore()
        manifest = _run(harness, store, cfg_id)

        assert manifest.done == 1 and manifest.errors == 0
        _seg, _indices, weight, rows, class1 = cap.calls[0]
        assert weight == 6
        # class-1 is the mean of the act[1] channel of the exact member rows.
        assert class1 == pytest.approx(float(np.asarray(rows)[:, _CLASS1].mean()))
        # act[1] mean != act[0] mean for this store, proving act[1] was selected.
        assert class1 != pytest.approx(float(np.asarray(rows)[:, 0].mean()))
    finally:
        harness.close()


def test_runner_default_configs_select_effnet_eligible(con, tmp_path, compact_catalog_factory) -> None:
    """config_ids=None selects the canonical compact effnet configs and pools over them."""
    harness, cfg_id = _build_harness(compact_catalog_factory, con, tmp_path)
    try:
        _set_patch_count(harness, cfg_id, "s1", _PATCH_COUNT)
        _craft_segment(harness, cfg_id, "s1", seg_id=0, start_idx=0, end_idx=6, absorbed=())

        store = _FakeHeadStore()
        manifest = run_shared_catalog_head_analysis(harness.con, store, run_id="r-default")

        assert cfg_id in manifest.config_ids
        assert manifest.done >= 1 and manifest.errors == 0
        assert manifest.backbones == ("effnet",)
        assert store.gather_requests  # at least one gather happened
    finally:
        harness.close()


def test_runner_skips_unknown_requested_config(con, tmp_path, compact_catalog_factory) -> None:
    """A requested config id with no seg_config row is a deterministic skip, never an error."""
    harness, cfg_id = _build_harness(compact_catalog_factory, con, tmp_path)
    try:
        _set_patch_count(harness, cfg_id, "s1", _PATCH_COUNT)
        _craft_segment(harness, cfg_id, "s1", seg_id=0, start_idx=0, end_idx=6, absorbed=())

        store = _FakeHeadStore()
        manifest = _run(harness, store, cfg_id, config_ids=[cfg_id, 999])

        assert manifest.errors == 0
        assert manifest.config_ids == (cfg_id,)
        reasons = dict(manifest.skip_reasons)
        assert "config:999" in reasons
        # the valid config still produced a done result.
        assert manifest.done >= 1
        for r in manifest.results:
            assert r.config_id == cfg_id
            assert r.status == "done"
    finally:
        harness.close()


def _build_two_song_harness(compact_catalog_factory, con, tmp_path):
    """One compact snapshot over s1 + s2 (same config) and return (harness, cfg_id)."""
    harness = compact_catalog_factory(
        con,
        tmp_path,
        streams={("s1", "effnet"): _STREAM, ("s2", "effnet"): _STREAM},
        configs=[_effnet_config()],
        song_ids=["s1", "s2"],
    )
    from scripts.embedding_research.catalog import compact_configs_by_backbone

    config_rows = compact_configs_by_backbone(harness.con, "effnet")
    cfg_id = config_rows[0].config_id
    _set_patch_count(harness, cfg_id, "s1", _PATCH_COUNT)
    _set_patch_count(harness, cfg_id, "s2", _PATCH_COUNT)
    _craft_segment(harness, cfg_id, "s1", seg_id=0, start_idx=0, end_idx=_PATCH_COUNT, absorbed=())
    _craft_segment(harness, cfg_id, "s2", seg_id=0, start_idx=0, end_idx=_PATCH_COUNT, absorbed=())
    return harness, cfg_id


def test_runner_reports_missing_frozen_head_stream_with_reason(con, tmp_path, compact_catalog_factory) -> None:
    """A song with NO frozen head stream is reported, never a bare silent ``continue``.

    Partially-misaligned catalog: s2 has a carved compact segment but the frozen head store
    serves only s1, so s2 cannot be pooled.  The runner must (a) still pool s1 with correct
    attempted/done accounting (``n_songs == n_pooled == 1`` on the done record), (b) surface
    the s2 omission as an explicit JSON-safe ``skip_reasons`` entry scoped
    ``config:<id>:song:s2`` instead of silently undercounting, and (c) leave the healthy
    song free of spurious reasons.
    """
    harness, cfg_id = _build_two_song_harness(compact_catalog_factory, con, tmp_path)
    try:
        store = _MissingStreamHeadStore(missing={"s2"})
        manifest = run_shared_catalog_head_analysis(
            harness.con, store, config_ids=[cfg_id], song_ids=["s1", "s2"], heads=["mood"], run_id="r"
        )

        # s1 still pools; the aggregated coverage record counts only songs that pooled.
        assert manifest.done == 1 and manifest.errors == 0
        assert all(r.status == "done" and r.n_songs == r.n_pooled == 1 for r in manifest.results)

        reasons = dict(manifest.skip_reasons)
        scope = f"config:{cfg_id}:song:s2"
        assert scope in reasons
        assert "no frozen head stream" in reasons[scope]
        # the healthy song is never misreported.
        assert f"config:{cfg_id}:song:s1" not in reasons

        # only s1 may reach the pool path (gather of 6 searchable rows for the served song).
        assert store.gather_requests and all(len(req) == _PATCH_COUNT for req in store.gather_requests)

        # the manifest (with the new reason entry) stays JSON-safe.
        payload = json.loads(manifest.to_json())
        assert any(s == scope for s, _ in payload["skip_reasons"])
    finally:
        harness.close()


def test_runner_reports_head_lookup_failure_reason(con, tmp_path, compact_catalog_factory) -> None:
    """A lookup exception (unreadable frozen stream) surfaces a reason, not a bare continue."""
    harness, cfg_id = _build_two_song_harness(compact_catalog_factory, con, tmp_path)
    try:
        store = _MissingStreamHeadStore(missing={"s2"}, raise_on_lookup=True)
        manifest = run_shared_catalog_head_analysis(
            harness.con, store, config_ids=[cfg_id], song_ids=["s1", "s2"], heads=["mood"], run_id="r"
        )

        assert manifest.done == 1 and manifest.errors == 0
        reasons = dict(manifest.skip_reasons)
        scope = f"config:{cfg_id}:song:s2"
        assert scope in reasons
        assert "head stream lookup failed" in reasons[scope]
        assert f"config:{cfg_id}:song:s1" not in reasons
    finally:
        harness.close()


def test_runner_full_coverage_has_no_spurious_skip_reasons(con, tmp_path, compact_catalog_factory) -> None:
    """Normal full-coverage runs are unaffected: no skip/error reasons are emitted."""
    harness, cfg_id = _build_two_song_harness(compact_catalog_factory, con, tmp_path)
    try:
        store = _FakeHeadStore()
        manifest = run_shared_catalog_head_analysis(
            harness.con, store, config_ids=[cfg_id], song_ids=["s1", "s2"], heads=["mood"], run_id="r"
        )

        assert manifest.skip_reasons == ()
        assert manifest.done == 1 and manifest.errors == 0 and manifest.finite is True
        record = manifest.results[0]
        assert record.status == "done"
        assert record.n_songs == record.n_pooled == 2
    finally:
        harness.close()


def test_runner_manifest_is_json_safe_with_coverage_and_finite(con, tmp_path, compact_catalog_factory) -> None:
    """The manifest is JSON-safe and carries deterministic coverage/finite + record types."""
    harness, cfg_id = _build_harness(compact_catalog_factory, con, tmp_path)
    try:
        _set_patch_count(harness, cfg_id, "s1", _PATCH_COUNT)
        _craft_segment(harness, cfg_id, "s1", seg_id=0, start_idx=0, end_idx=6, absorbed=())

        store = _FakeHeadStore()
        manifest = _run(harness, store, cfg_id)
        d = json.loads(manifest.to_json())
        assert d["run_id"] == "r"
        assert d["config_ids"] == [cfg_id]
        assert d["finite"] is True
        assert d["boundary_source"] == BOUNDARY_SOURCE_CATALOG
        assert d["done"] >= 1 and d["errors"] == 0
        assert all(isinstance(r, HeadAnalysisConfigRecord) for r in manifest.results)
        record = manifest.results[0]
        assert record.head == "mood"
        assert record.boundary_source == BOUNDARY_SOURCE_CATALOG
        assert record.n_pooled == record.n_songs == 1
        assert record.status == "done"
    finally:
        harness.close()


def test_common_head_analysis_legacy_symbols_removed() -> None:
    """The inclusive-range helper and old-runner symbols are gone from the active module."""
    assert not hasattr(head_mod, "pool_head_outputs_over_ptc_boundaries")
    assert not hasattr(head_mod, "run_shared_ptc_head_pooling")
    assert not hasattr(head_mod, "HeadBoundaryPoolResult")


# ---------------------------------------------------------------------------
# CPU-boundary source guard (no persistence / model / membership-table calls)
# ---------------------------------------------------------------------------

_FORBIDDEN = {
    "temporal_segment",
    "segment_fn",
    "binned_ctp",
    "strategy_ctp",
    "onnx",
    "sklearn",
    "torch",
    "ml_session_comp",
    "write_head_phase_provenance",
    "append_head_phase_archival_rows",
    "alias_of_config_id",
    "calibration_record",
    "seg_membership",
    "search_view_hash",
    "ann_recall_sweep",
}


def _function_body_code_names(path: str, name: str) -> set[str]:
    source = (_RESEARCH_DIR / path).read_text(encoding="utf-8")
    tree = __import__("ast").parse(source)
    for node in __import__("ast").walk(tree):
        if isinstance(node, __import__("ast").FunctionDef) and node.name == name:
            ids: set[str] = set()
            for n in __import__("ast").walk(node):
                if isinstance(n, __import__("ast").Name):
                    ids.add(n.id)
                elif isinstance(n, __import__("ast").Attribute):
                    ids.add(n.attr)
            return ids
    raise AssertionError(f"function {name!r} not found in {path}")


def test_active_runner_is_cpu_boundary_no_persistence_no_forbidden_calls() -> None:
    """run_shared_catalog_head_analysis never reaches forbidden/derived/persistence surfaces."""
    names = _function_body_code_names("common/head_analysis.py", "run_shared_catalog_head_analysis")
    overlap = _FORBIDDEN & names
    assert not overlap, f"forbidden tokens referenced by the active runner: {sorted(overlap)}"
