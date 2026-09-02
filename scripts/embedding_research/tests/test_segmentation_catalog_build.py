"""Plan C Phase 3 — the one-pass multi-threshold segmentation catalog build.

Proves the DD R8 one-pass + bounded-lookup contracts implemented by
``scripts.embedding_research/catalog.py``:

* one frozen stream load per ``(song, backbone)`` shared across every explicit or
  generated threshold config in the pass;
* all explicit/generated thresholds are evaluated (no early skip);
* no calibration / optimizer / audio / ONNX / CUDA invocation on the catalog path;
* application id allocation + single-config rebuild scope (``DELETE WHERE config_id=?``
  only) leaves unrelated configs preserved;
* full rebuild and partial-song/config statuses are reported;
* rerun idempotence (same logical config reuses its ``config_id``, never duplicates);
* the four bounded lookups return correct records and add no DuckDB indexes;
* the report carries the arithmetic sizing note, per-config completion counts, and the
  one-load-per-song evidence.
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research import catalog
from scripts.embedding_research.config import discover_audio as config_discover_audio
from scripts.embedding_research.helpers.binning import DIST_FNS
from scripts.embedding_research.helpers.segmentation import (
    authoritative_segmentation,
    validate_full_partition,
)
from scripts.embedding_research.streams.records import StreamNotFoundError
from scripts.embedding_research.streams.store import StreamStore

# Optional ML-stack availability.  The catalog path never imports these; if a platform
# has them installed we still sentinel them (so a regression that reaches them fires);
# if they are absent they cannot be called, which is itself the CPU-only proof.
try:  # pragma: no cover - environment dependent
    import onnxruntime  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    onnxruntime = None  # type: ignore[assignment]

try:  # pragma: no cover - environment dependent
    import torch  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    torch = None  # type: ignore[assignment]


def _unit(rng, n: int, d: int, spread: float = 1.5) -> np.ndarray:
    """Deterministic float32 L2-unit rows (a normalized frozen-stream stand-in)."""
    m = rng.standard_normal((n, d)) * spread
    m[0] += 3.0
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (m / norms).astype(np.float32)


def _seed(con, out, mapping: dict[tuple[str, str], np.ndarray]) -> StreamStore:
    """Publish + reconcile one ready frozen stream per ``(song, backbone)`` in *mapping*."""
    store = StreamStore(con, output_root=out)
    for (song, backbone), arr in mapping.items():
        store.publish(song, backbone, arr, run_id="run-embed")
    store.reconcile()
    return store


def _cfg(threshold: float, *, backbone: str = "effnet", bin_mode: str = "temporal_global") -> catalog.SegConfigInput:
    """A direct-L2 threshold config (configured == effective) over the PTC temporal map."""
    return catalog.SegConfigInput(
        backbone=backbone,
        bin_mode=bin_mode,
        threshold_configured=threshold,
        threshold_effective=threshold,
    )


def _seg_counts(con) -> tuple[int, int]:
    return (
        int(con.execute("SELECT count(*) FROM seg_config").fetchone()[0]),
        int(con.execute("SELECT count(*) FROM seg_membership").fetchone()[0]),
    )


def _membership_count(con, config_id: int) -> int:
    return int(con.execute("SELECT count(*) FROM seg_membership WHERE config_id = ?", [config_id]).fetchone()[0])


def _index_count(con) -> int:
    return int(con.execute("SELECT count(*) FROM duckdb_indexes()").fetchone()[0])


def _assert_report_clean(rep: catalog.CatalogBuildReport) -> None:
    assert rep.verify_ok is True
    assert rep.arithmetic_sizing_note == catalog.ARITHMETIC_SIZING_NOTE
    assert "ARITHMETIC" in rep.arithmetic_sizing_note.upper()


# --------------------------------------------------------------------------- #
# R8 one-pass build semantics                                                  #
# --------------------------------------------------------------------------- #


def test_one_stream_load_per_song_across_many_threshold_configs(con, tmp_path, monkeypatch):
    """Five thresholds share ONE stream load per (song, backbone); report proves it."""
    out = tmp_path / "out"
    rng = np.random.default_rng(3)
    store = _seed(con, out, {("s1", "effnet"): _unit(rng, 5, 4), ("s2", "effnet"): _unit(rng, 6, 4)})

    thresholds = [0.4, 0.5, 0.6, 0.7, 0.8]
    cfgs = [_cfg(t) for t in thresholds]

    # Wrap the real batch_gather with a counting seam: it is the single file-load site.
    original = store.batch_gather
    calls: dict[tuple[str, str], int] = {}

    def counting(song, backbone, indices):
        key = (song, backbone)
        calls[key] = calls.get(key, 0) + 1
        return original(song, backbone, indices)

    monkeypatch.setattr(store, "batch_gather", counting)

    rep = catalog.build_segmentation_catalog(con, store, cfgs, ["s1", "s2"], "run-cat-load")

    # Every threshold config was evaluated and completed for both songs.
    assert len(rep.configs) == 5
    for outcome in rep.configs:
        assert outcome.status == "complete"
        assert outcome.songs_completed == 2
        assert outcome.total_membership_rows > 0

    # The stream was loaded EXACTLY once per (song, backbone) regardless of config count.
    assert calls == {("s1", "effnet"): 1, ("s2", "effnet"): 1}
    assert rep.stream_loads == 2
    assert rep.load_evidence == (("s1", "effnet", 1), ("s2", "effnet", 1))
    assert rep.songs_built == 2
    assert rep.status == "complete"
    _assert_report_clean(rep)
    assert _index_count(con) == 0


def test_all_explicit_and_generated_thresholds_present_no_early_skip(con, tmp_path):
    """Distinct thresholds across backbones all get an outcome (nothing silently skipped)."""
    out = tmp_path / "out"
    rng = np.random.default_rng(5)
    store = _seed(
        con,
        out,
        {
            ("s1", "effnet"): _unit(rng, 5, 4),
            ("t1", "musicnn"): _unit(rng, 5, 4),
            ("t2", "musicnn"): _unit(rng, 6, 4),
        },
    )
    cfgs = [
        _cfg(1.0, backbone="effnet"),
        _cfg(0.8, backbone="effnet"),
        _cfg(1.2, backbone="musicnn", bin_mode="temporal_perdim"),
        _cfg(0.6, backbone="musicnn", bin_mode="temporal_perdim"),
    ]
    rep = catalog.build_segmentation_catalog(con, store, cfgs, ["s1", "t1", "t2"], "run-cat-all")

    # Four distinct canonical configs were evaluated; every song's stream was processed.
    assert len(rep.configs) == 4
    seen = {(o.backbone, o.threshold_effective) for o in rep.configs}
    assert seen == {("effnet", 1.0), ("effnet", 0.8), ("musicnn", 1.2), ("musicnn", 0.6)}
    assert all(o.status == "complete" for o in rep.configs)
    assert rep.status == "complete"
    # effnet stream loaded once; musicnn stream loaded once (shared across 2 musicnn cfgs).
    assert rep.stream_loads == 3
    assert rep.load_evidence == (
        ("s1", "effnet", 1),
        ("t1", "musicnn", 1),
        ("t2", "musicnn", 1),
    )


def test_persisted_membership_matches_authoritative_segmentation(con, tmp_path):
    """Per-song persisted membership equals the pure authoritative segmentation map."""
    out = tmp_path / "out"
    rng = np.random.default_rng(7)
    arr = _unit(rng, 6, 4)
    store = _seed(con, out, {("s1", "effnet"): arr})
    cfg = _cfg(0.7)
    rep = catalog.build_segmentation_catalog(con, store, [cfg], ["s1"], "run-cat-match")

    outcome = rep.configs[0]
    norm = catalog._l2_normalize_rows(arr)
    segments = authoritative_segmentation(norm, cfg.threshold_effective, DIST_FNS[cfg.bin_mode])
    validate_full_partition(segments, len(norm))

    expected = {}
    for seg in segments:
        for idx in seg.member_indices:
            expected[(seg.seg_id, idx)] = None

    persisted = catalog.segments_by_config_song(con, outcome.config_id, "s1")
    assert len(persisted) == len(segments)
    actual = {}
    for meta in persisted:
        assert meta.medoid_source_patch_idx < len(norm)  # observed index, never a vector
        members = catalog.membership_by_config_song_seg(con, meta.config_id, "s1", meta.seg_id)
        for member in members:
            actual[(meta.seg_id, member.member_patch_idx)] = None
    assert set(actual) == set(expected)


# --------------------------------------------------------------------------- #
# CPU / model-boundary (catalog is numpy + DuckDB only)                        #
# --------------------------------------------------------------------------- #


class _RaisingSentinel:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events

    def __call__(self, *_args, **_kwargs):
        self.events.append(self.name)
        raise AssertionError(f"forbidden call during a CPU-only catalog build: {self.name}")


def _install_sentinels(monkeypatch) -> dict[str, int]:
    """Monkeypatch real audio/ONNX/CUDA call sites with raising sentinels."""
    events: list[str] = []
    installed: dict[str, _RaisingSentinel] = {}
    sentinel = _RaisingSentinel("config.discover_audio", events)
    monkeypatch.setattr(config_discover_audio.__module__ + ".discover_audio", sentinel)
    installed["config.discover_audio"] = sentinel
    if onnxruntime is not None:
        sentinel = _RaisingSentinel("onnxruntime.InferenceSession", events)
        monkeypatch.setattr(onnxruntime, "InferenceSession", sentinel)
        installed["onnxruntime.InferenceSession"] = sentinel
    if torch is not None:
        sentinel = _RaisingSentinel("torch.cuda.is_available", events)
        monkeypatch.setattr(torch.cuda, "is_available", sentinel)
        installed["torch.cuda.is_available"] = sentinel
    return {name: len(sentinel.events) for name, sentinel in installed.items()}


def test_catalog_build_completes_with_zero_audio_model_cuda_calls(con, tmp_path, monkeypatch):
    """The catalog pass completes with NO calibration/optimizer/audio/ONNX/CUDA call."""
    out = tmp_path / "out"
    rng = np.random.default_rng(2)
    store = _seed(con, out, {("s1", "effnet"): _unit(rng, 5, 4)})
    counts = _install_sentinels(monkeypatch)

    rep = catalog.build_segmentation_catalog(con, store, [_cfg(0.8)], ["s1"], "run-cat-cpu", verify=True)

    assert rep.status == "complete"
    assert rep.configs[0].songs_completed == 1
    assert counts  # at least config.discover_audio is always guarded
    assert all(count == 0 for count in counts.values()), counts


# --------------------------------------------------------------------------- #
# Identity / rebuild / transaction semantics (P3-S2)                           #
# --------------------------------------------------------------------------- #


def test_config_id_is_application_allocated_and_reused_on_rerun(con, tmp_path):
    """Same logical config reuses its id across runs; distinct configs get distinct ids."""
    out = tmp_path / "out"
    rng = np.random.default_rng(4)
    store = _seed(con, out, {("s1", "effnet"): _unit(rng, 5, 4)})

    rep1 = catalog.build_segmentation_catalog(con, store, [_cfg(0.9)], ["s1"], "run-cat-id-1")
    cfg_id1 = rep1.configs[0].config_id

    rep2 = catalog.build_segmentation_catalog(con, store, [_cfg(0.9), _cfg(0.5)], ["s1"], "run-cat-id-2")
    ids = {o.threshold_effective: o.config_id for o in rep2.configs}
    assert ids[0.9] == cfg_id1  # reused, not re-allocated
    assert ids[0.5] != cfg_id1  # genuinely new logical config -> fresh id
    assert _seg_counts(con)[0] == 2  # still exactly two seg_config rows


def test_rerun_idempotence_no_duplicate_config_or_membership_rows(con, tmp_path):
    """Running the same logical config set twice leaves identical catalog contents."""
    out = tmp_path / "out"
    rng = np.random.default_rng(8)
    store = _seed(
        con,
        out,
        {("s1", "effnet"): _unit(rng, 5, 4), ("s2", "effnet"): _unit(rng, 6, 4)},
    )
    cfgs = [_cfg(0.7), _cfg(1.0)]

    rep1 = catalog.build_segmentation_catalog(con, store, cfgs, ["s1", "s2"], "run-cat-rerun")
    cfg_rows_1, mem_rows_1 = _seg_counts(con)

    rep2 = catalog.build_segmentation_catalog(con, store, cfgs, ["s1", "s2"], "run-cat-rerun", verify=True)
    cfg_rows_2, mem_rows_2 = _seg_counts(con)

    assert rep2.status == "complete"
    assert rep2.verify_ok is True
    assert cfg_rows_2 == cfg_rows_1 == 2  # config rows never duplicated
    assert mem_rows_2 == mem_rows_1  # membership rows never duplicated
    # Same allocated ids across both runs.
    assert {o.threshold_effective: o.config_id for o in rep1.configs} == {
        o.threshold_effective: o.config_id for o in rep2.configs
    }


def test_single_config_rebuild_affects_only_that_config_id(con, tmp_path):
    """Rebuilding one config deletes/rewrites ONLY its rows; the other config survives."""
    out = tmp_path / "out"
    rng = np.random.default_rng(9)
    store = _seed(
        con,
        out,
        {("s1", "effnet"): _unit(rng, 5, 4), ("s2", "effnet"): _unit(rng, 6, 4)},
    )
    cfg_a, cfg_b = _cfg(0.8), _cfg(1.2)

    first = catalog.build_segmentation_catalog(con, store, [cfg_a, cfg_b], ["s1", "s2"], "run-cat-sr-1")
    id_a = {o.threshold_effective: o.config_id for o in first.configs}[0.8]
    id_b = {o.threshold_effective: o.config_id for o in first.configs}[1.2]
    before_a = _membership_count(con, id_a)
    before_b = _membership_count(con, id_b)

    # Single-config rebuild: only cfg_a is in scope.
    rebuild = catalog.build_segmentation_catalog(con, store, [cfg_a], ["s1", "s2"], "run-cat-sr-2")

    # cfg_a rows were replaced at its own config_id; cfg_b rows are byte-for-byte intact.
    assert len(rebuild.configs) == 1
    assert rebuild.configs[0].config_id == id_a
    assert _membership_count(con, id_a) == before_a  # fully rewritten, no dup, same song scope
    assert _membership_count(con, id_b) == before_b  # unrelated config untouched
    assert _seg_counts(con)[0] == 2  # no new/duplicate config row for cfg_a


def test_full_rebuild_and_partial_song_statuses(con, tmp_path, monkeypatch):
    """Full rebuild clears+recreates in-scope configs; partial failures are reported."""
    out = tmp_path / "out"
    rng = np.random.default_rng(6)
    store = _seed(
        con,
        out,
        {("s1", "effnet"): _unit(rng, 5, 4), ("s2", "effnet"): _unit(rng, 6, 4)},
    )
    cfgs = [_cfg(0.6), _cfg(1.1)]

    # Full rebuild over all songs -> both configs complete.
    full = catalog.build_segmentation_catalog(con, store, cfgs, ["s1", "s2"], "run-cat-full-1")
    assert full.status == "complete"
    assert all(o.status == "complete" for o in full.configs)

    # Second full rebuild (new run_id) reuses the same ids, same contents, no duplicates.
    full2 = catalog.build_segmentation_catalog(con, store, cfgs, ["s1", "s2"], "run-cat-full-2", verify=True)
    assert full2.status == "complete"
    assert _seg_counts(con)[1] == full.total_membership_rows

    # Genuine per-song write failure -> partial-song status (never a silent half-write).
    orig_write = catalog._write_song_membership

    def _flaky(con_, *, config_id, song_id, segments):
        if song_id == "s2":
            raise RuntimeError("simulated membership write failure")
        return orig_write(con_, config_id=config_id, song_id=song_id, segments=segments)

    monkeypatch.setattr(catalog, "_write_song_membership", _flaky)
    partial = catalog.build_segmentation_catalog(con, store, [_cfg(0.6)], ["s1", "s2"], "run-cat-partial")
    monkeypatch.undo()
    assert partial.status == "partial"
    outcome = partial.configs[0]
    assert outcome.status == "partial"
    assert outcome.songs_eligible == 2
    assert outcome.excluded_songs == 0
    assert outcome.songs_completed == 1
    assert outcome.failed_songs == ("s2:RuntimeError",)


def test_unrelated_config_preserved_across_builds(con, tmp_path):
    """A config not in the current build scope keeps every row through later builds."""
    out = tmp_path / "out"
    rng = np.random.default_rng(10)
    store = _seed(con, out, {("s1", "effnet"): _unit(rng, 5, 4)})

    keep = _cfg(1.0)
    catalog.build_segmentation_catalog(con, store, [keep, _cfg(0.5)], ["s1"], "run-cat-keep-1")
    keep_id = {o.threshold_effective: o.config_id for o in catalog.configs_by_backbone(con, "effnet")}[1.0]
    before = _membership_count(con, keep_id)

    # Rebuild only the OTHER config several times.
    for i in range(3):
        catalog.build_segmentation_catalog(con, store, [_cfg(0.5)], ["s1"], f"run-cat-keep-{i}")

    assert _membership_count(con, keep_id) == before  # cfg 1.0 never touched
    assert catalog.configs_by_backbone(con, "effnet")[0].config_id == 1  # id 1 preserved


# --------------------------------------------------------------------------- #
# Bounded lookups (P3-S3) + no-index guarantee                                 #
# --------------------------------------------------------------------------- #


def test_bounded_lookups_return_correct_records_and_add_no_indexes(con, tmp_path):
    """The four lookups read correct rows via equality filters; no DuckDB index appears."""
    out = tmp_path / "out"
    rng = np.random.default_rng(12)
    store = _seed(
        con,
        out,
        {("s1", "effnet"): _unit(rng, 5, 4), ("t1", "musicnn"): _unit(rng, 5, 4)},
    )
    cfgs = [
        _cfg(0.7, backbone="effnet"),
        _cfg(0.9, backbone="musicnn", bin_mode="temporal_perdim"),
    ]
    assert _index_count(con) == 0
    catalog.build_segmentation_catalog(con, store, cfgs, ["s1", "t1"], "run-cat-lk")
    assert _index_count(con) == 0

    # configs_by_backbone filters by backbone only.
    eff = catalog.configs_by_backbone(con, "effnet")
    mus = catalog.configs_by_backbone(con, "musicnn")
    assert [c.config_id for c in eff] == [1]
    assert [c.config_id for c in mus] == [2]
    assert eff[0].backbone == "effnet" and mus[0].bin_mode == "temporal_perdim"

    # segments_by_config_song filters by (config_id, song_id).
    segs_s1 = catalog.segments_by_config_song(con, 1, "s1")
    assert segs_s1 and all(m.config_id == 1 and m.song_id == "s1" for m in segs_s1)
    # membership_by_config_song_seg scoped to one segment.
    seg0 = segs_s1[0]
    members = catalog.membership_by_config_song_seg(con, 1, "s1", seg0.seg_id)
    assert members and all(m.seg_id == seg0.seg_id for m in members)
    assert len(members) == seg0.member_count  # row count matches seg_meta member_count
    assert all(0 <= m.member_patch_idx < 5 for m in members)  # observed source indices

    # stream_by_song_backbone returns the ready registry record.
    rec = catalog.stream_by_song_backbone(con, "s1", "effnet")
    assert rec.status == "ready"
    assert rec.patch_count == 5
    # Non-ready / absent identities raise the documented typed errors.
    with pytest.raises(StreamNotFoundError):
        catalog.stream_by_song_backbone(con, "nope", "effnet")

    assert _index_count(con) == 0  # lookups never created an index


# --------------------------------------------------------------------------- #
# QA Round-1 regression paths (eligible/excluded + empty/partial statusing)   #
# --------------------------------------------------------------------------- #


def test_requested_song_lacking_ready_stream_is_excluded_not_failed(con, tmp_path):
    """A requested song with no READY stream is silently excluded and counted, not a failure."""
    out = tmp_path / "out"
    rng = np.random.default_rng(21)
    store = _seed(con, out, {("s1", "effnet"): _unit(rng, 5, 4)})

    rep = catalog.build_segmentation_catalog(con, store, [_cfg(0.8)], ["s1", "missing"], "run-cat-excl")
    outcome = rep.configs[0]
    # s1 has a ready stream (eligible); 'missing' has none -> silently excluded, never a failure.
    assert outcome.songs_eligible == 1
    assert outcome.excluded_songs == 1
    assert outcome.songs_completed == 1
    assert outcome.status == "complete"
    assert outcome.failed_songs == ()
    assert _membership_count(con, outcome.config_id) > 0  # only s1 is present
    assert catalog.segments_by_config_song(con, outcome.config_id, "missing") == ()


def test_no_ready_stream_for_backbone_yields_empty_status(con, tmp_path):
    """A config whose backbone has zero READY streams is 'empty' (excluded-songs-only), not partial."""
    out = tmp_path / "out"
    rng = np.random.default_rng(22)
    # Only musicnn songs are ready; build an effnet-only config with no ready effnet songs.
    store = _seed(con, out, {("m1", "musicnn"): _unit(rng, 5, 4)})

    rep = catalog.build_segmentation_catalog(con, store, [_cfg(0.8)], ["m1"], "run-cat-empty")
    outcome = rep.configs[0]
    assert outcome.backbone == "effnet"
    assert outcome.songs_eligible == 0
    assert outcome.excluded_songs == 1  # the requested song lacks an effnet ready stream
    assert outcome.songs_completed == 0
    assert outcome.status == "empty"  # 'empty' = no ready stream for this backbone
    assert _membership_count(con, outcome.config_id) == 0


def test_subset_scope_rebuild_wipes_out_of_scope_rows_for_same_config(con, tmp_path):
    """A rerun over a narrower song scope replaces (deletes) the config's prior out-of-scope rows."""
    out = tmp_path / "out"
    rng = np.random.default_rng(23)
    store = _seed(
        con,
        out,
        {("s1", "effnet"): _unit(rng, 5, 4), ("s2", "effnet"): _unit(rng, 6, 4)},
    )
    cfg = _cfg(0.9)
    full = catalog.build_segmentation_catalog(con, store, [cfg], ["s1", "s2"], "run-cat-wipe-1")
    cid = full.configs[0].config_id
    assert _membership_count(con, cid) > 0
    assert len(catalog.segments_by_config_song(con, cid, "s2")) > 0

    # Rebuild the SAME logical config over only s1: the prior s2 catalog rows must be gone.
    narrow = catalog.build_segmentation_catalog(con, store, [cfg], ["s1"], "run-cat-wipe-2")
    assert narrow.configs[0].config_id == cid  # id reused (same canonical config)
    assert len(catalog.segments_by_config_song(con, cid, "s1")) > 0
    assert catalog.segments_by_config_song(con, cid, "s2") == ()  # out-of-scope rows deleted


def test_all_writes_fail_is_partial_not_empty(con, tmp_path, monkeypatch):
    """A config with eligible songs whose EVERY write fails reads 'partial', never 'empty'."""
    out = tmp_path / "out"
    rng = np.random.default_rng(24)
    store = _seed(
        con,
        out,
        {("s1", "effnet"): _unit(rng, 5, 4), ("s2", "effnet"): _unit(rng, 6, 4)},
    )

    def _all_fail(con_, *, config_id, song_id, segments):
        # Every (config, song) write fails so the outcome must read 'partial', not 'empty'.
        del con_, config_id, song_id, segments
        raise RuntimeError("simulated total write failure")

    monkeypatch.setattr(catalog, "_write_song_membership", _all_fail)
    rep = catalog.build_segmentation_catalog(con, store, [_cfg(0.7)], ["s1", "s2"], "run-cat-allfail")
    monkeypatch.undo()

    outcome = rep.configs[0]
    assert outcome.songs_eligible == 2  # both ready streams: not 'empty'
    assert outcome.songs_completed == 0
    # failed-first ordering: every write failed => genuine failures, so 'partial' not 'empty'.
    assert outcome.status == "partial"
    assert set(outcome.failed_songs) == {"s1:RuntimeError", "s2:RuntimeError"}


def test_validation_and_verification_error_paths_raise(con, tmp_path, monkeypatch):
    """CatalogValidationError (bad input) and CatalogVerificationError (verify drift) propagate."""
    out = tmp_path / "out"
    rng = np.random.default_rng(25)
    store = _seed(con, out, {("s1", "effnet"): _unit(rng, 5, 4)})

    # No configs.
    with pytest.raises(catalog.CatalogValidationError):
        catalog.build_segmentation_catalog(con, store, [], ["s1"], "run-cat-val-1")
    # No song ids.
    with pytest.raises(catalog.CatalogValidationError):
        catalog.build_segmentation_catalog(con, store, [_cfg(0.8)], [], "run-cat-val-2")
    # Blank run_id.
    with pytest.raises(catalog.CatalogValidationError):
        catalog.build_segmentation_catalog(con, store, [_cfg(0.8)], ["s1"], "  ")
    # All the validation errors derive from the shared CatalogError base.
    assert issubclass(catalog.CatalogValidationError, catalog.CatalogError)
    assert issubclass(catalog.CatalogError, RuntimeError)

    # verify=True with simulated post-build drift raises CatalogVerificationError.
    monkeypatch.setattr(catalog, "_post_build_verify", lambda *_, **__: ("simulated drift",))
    with pytest.raises(catalog.CatalogVerificationError):
        catalog.build_segmentation_catalog(con, store, [_cfg(0.8)], ["s1"], "run-cat-ver", verify=True)
    monkeypatch.undo()
    assert issubclass(catalog.CatalogVerificationError, catalog.CatalogError)


def test_post_build_verify_set_based_catches_same_drift_classes(con, tmp_path):
    """The set-based ``_post_build_verify`` catches the same drift classes as the old per-row loops.

    Pins the Phase-round-2 rewrite of ``_post_build_verify``: orphaned seg_meta (a built config
    row missing), orphaned membership (a seg_meta row missing under its membership), a membership
    row count that disagrees with ``seg_meta.member_count``, and a member index outside the
    verified stream all remain detectable through the set-based anti-joins / grouped-count query
    (per built config scope).  Scoping means rows belonging to configs outside the caller's
    ``outcomes`` set are intentionally not flagged.
    """
    out = tmp_path / "out"
    rng = np.random.default_rng(77)
    store = _seed(
        con,
        out,
        {("s1", "effnet"): _unit(rng, 5, 4), ("s2", "effnet"): _unit(rng, 6, 4)},
    )

    def _build(run_id_: str):
        return catalog.build_segmentation_catalog(con, store, [_cfg(0.7)], ["s1", "s2"], run_id_, verify=False)

    # Clean DB: the set-based verifier reports no drift on just-built configs.
    clean = _build("run-clean")
    assert catalog._post_build_verify(con, outcomes=clean.configs, run_id="run-clean") == ()

    # (a) Orphaned seg_meta: the built config's seg_config row is gone.
    rep = _build("run-a")
    cid = rep.configs[0].config_id
    con.execute("DELETE FROM seg_config WHERE config_id = ?", [cid])
    assert any(
        "seg_config missing for built config_id" in e
        for e in catalog._post_build_verify(con, outcomes=rep.configs, run_id="run-a")
    )

    # (b) Orphaned membership: a seg_meta row is removed, orphaning its membership rows.
    rep = _build("run-b")
    cid = rep.configs[0].config_id
    seg = con.execute("SELECT song_id, seg_id FROM seg_meta WHERE config_id = ? LIMIT 1", [cid]).fetchone()
    assert seg is not None  # a ready stream always yields >= 1 segment for these configs
    song_id, seg_id = seg
    assert (
        con.execute(
            "SELECT count(*) FROM seg_membership WHERE config_id = ? AND song_id = ? AND seg_id = ?",
            [cid, song_id, seg_id],
        ).fetchone()[0]
        > 0
    )
    con.execute(
        "DELETE FROM seg_meta WHERE config_id = ? AND song_id = ? AND seg_id = ?",
        [cid, song_id, seg_id],
    )
    assert any(
        "references a seg_meta row that does not exist" in e
        for e in catalog._post_build_verify(con, outcomes=rep.configs, run_id="run-b")
    )

    # (c) Membership count drift: persisted membership rows disagree with seg_meta.member_count.
    rep = _build("run-c")
    cid = rep.configs[0].config_id
    con.execute("UPDATE seg_meta SET member_count = member_count + 1 WHERE config_id = ?", [cid])
    assert any(
        "!=" in e and "member_count" in e for e in catalog._post_build_verify(con, outcomes=rep.configs, run_id="run-c")
    )

    # (d) Member index outside the verified stream's patch_count.
    rep = _build("run-d")
    cid = rep.configs[0].config_id
    patch_cap = int(con.execute("SELECT max(patch_count) FROM stream_registry").fetchone()[0])
    row = con.execute(
        "SELECT song_id, seg_id, member_patch_idx FROM seg_membership WHERE config_id = ? LIMIT 1",
        [cid],
    ).fetchone()
    con.execute(
        "UPDATE seg_membership SET member_patch_idx = ? "
        "WHERE config_id = ? AND song_id = ? AND seg_id = ? AND member_patch_idx = ?",
        [patch_cap + 50, cid, row[0], row[1], row[2]],
    )
    assert any(
        "outside the verified frozen source stream" in e
        for e in catalog._post_build_verify(con, outcomes=rep.configs, run_id="run-d")
    )
