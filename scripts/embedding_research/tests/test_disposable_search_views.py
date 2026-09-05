"""Plan D Phase 1 (P1-S1) — spec-first tests for the §D DISPOSABLE search-view surface.

These tests were authored as the spec-first RED set pinning the TARGET contract of
``scripts/embedding_research/CONTRACTS.md`` §D ("disposable analysis and scoring contracts") and
of DD-frozen-observation-corrective-pass requirements 8-10 / 12-13, BEFORE the P1-S2 rewrite of
``search_views.py`` — at which point ``materialize_search_view`` had a KEYSET signature (took a
corpus + ``query_keyset``) and each test called the TARGET signature below, failing with
``TypeError``.  P1-S2 then rewrote ``materialize_search_view`` to the catalog-first signature
below and removed ``search_view_hash``, so these tests now pass against the landed surface.

Pinned target surface (what P1-S2 must provide in ``scripts/embedding_research/search_views.py``):

* ``materialize_search_view(catalog, stream_store, *, song_ids, backbone, run_id,
  working_memory) -> SearchViewRecord`` — ``catalog`` is a compact CatalogHandle / snapshot
  connection (duck-typed via ``getattr(con, "con", con)``); ``stream_store`` is a
  ``StreamStore``; gathers ONLY observed source medoids; writes disposable views; never touches
  audio/model/ONNX/CUDA; NO ``search_view_hash`` anywhere in the signature or record.
* ``SearchViewRecord.row_addresses`` — ordered ascending ``(config_id, song_id, seg_id,
  source_patch_idx)`` 4-tuples; ``source_patch_idx == seg_meta.search_medoid_source_patch_idx``.
  Segments whose medoid is ``None`` (no searchable mass) contribute NO row.
* ``SearchViewRecord.vectors`` / ``SearchViewRecord.weights`` — gathered observed-medoid rows
  and per-row ``searchable_count / total_searchable_song`` weights aligned to ``row_addresses``.
* Materialization ALWAYS regenerates (gathers + rewrites); a view file's existence never
  authorizes reuse.
* Finite-only outputs: non-finite gathered source data fails closed.

``collapse_search_representations`` / ``SearchRepresentationClass`` / ``analyze_catalog_corpus``
/ ``CatalogAnalysisResult`` belong to later P1-S1..P1-S4/P1-S5 scope and are NOT exercised here.
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts.embedding_research import catalog
from scripts.embedding_research import search_views as sv
from scripts.embedding_research.helpers.segmentation import (
    reconstruct_searchable_indices,
)

# Optional CPU seams — attach sentinels only when the underlying symbol is importable, so
# module-level collection never depends on torch / onnxruntime / ml_session_comp presence.
try:  # pragma: no cover - environment dependent
    import onnxruntime  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    onnxruntime = None
try:  # pragma: no cover - environment dependent
    import torch  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    torch = None
try:  # pragma: no cover - environment dependent
    from nomarr.components.ml.onnx import ml_session_comp  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    ml_session_comp = None
try:  # pragma: no cover - environment dependent
    from scripts.embedding_research import config as _config
except Exception:  # pragma: no cover
    _config = None


pytestmark = pytest.mark.unit

# Song roles shared by the fixtures:
_S_SEARCHABLE = "s1"  # fully searchable -> several rows, weights sum to 1
_S_PARTIAL = "ps"  # one searchable segment + one null-medoid (silenced) segment
_S_ZERO = "zs"  # fully silenced -> zero total searchable, metadata-only (no candidate)

_N = 10
_D = 6


# --------------------------------------------------------------------------- #
# Matrix / fixture helpers (synthetic numpy streams only)                      #
# --------------------------------------------------------------------------- #


def _unit_rows(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (mat / norms).astype(np.float32)


def _noisy_block(center: int, n: int, rng) -> np.ndarray:
    """n unit rows clustered around basis ``e_center``."""
    a = np.zeros(_D, dtype=np.float32)
    a[center] = 1.0
    rows = [a + 0.05 * rng.standard_normal(_D) for _ in range(n)]
    return _unit_rows(np.asarray(rows, dtype=np.float32))


def _random_unit_song(seed: int) -> np.ndarray:
    """A fully-searchable song that segments into several rows (medoids all present)."""
    rng = np.random.default_rng(seed)
    mat = rng.standard_normal((_N, _D)) * 1.5
    mat[0] += 3.0
    return _unit_rows(mat)


def _two_cluster_partial() -> np.ndarray:
    """Two separated clusters so segmentation yields two segments; test silences the 2nd."""
    rng = np.random.default_rng(11)
    first = _noisy_block(0, 5, rng)
    second = _noisy_block(1, 5, rng)
    return _unit_rows(np.vstack([first, second]))


def _one_config() -> list:
    return [
        catalog.SegConfigInput(
            backbone="effnet",
            bin_mode="temporal_global",
            threshold_configured=0.7,
            threshold_effective=0.7,
        )
    ]


def _partial_mask() -> np.ndarray:
    mask = np.ones(_N, dtype=np.uint8)
    mask[5:] = 0  # silence the second cluster -> its segment becomes null-medoid
    return mask


def _zero_mask() -> np.ndarray:
    return np.zeros(_N, dtype=np.uint8)


def _build_harness(factory, con, out, run_id):
    """Publish ready effnet streams + build ONE compact snapshot; return the harness."""
    streams = {
        (_S_SEARCHABLE, "effnet"): _random_unit_song(7),
        (_S_PARTIAL, "effnet"): _two_cluster_partial(),
        (_S_ZERO, "effnet"): _random_unit_song(3),
    }
    masks = {
        _S_PARTIAL: _partial_mask(),
        _S_ZERO: _zero_mask(),
    }
    return factory(
        con,
        out,
        streams=streams,
        configs=_one_config(),
        song_ids=[_S_SEARCHABLE, _S_PARTIAL, _S_ZERO],
        masks=masks,
        run_id=run_id,
    )


def _config_id(harness) -> int:
    return catalog.compact_configs_by_backbone(harness.con, "effnet")[0].config_id


def _mask_array(harness, song: str) -> np.ndarray | None:
    loaded = harness.mask(song)
    if loaded is None:
        return np.ones(_N, dtype=np.uint8) if song == _S_SEARCHABLE else None
    return np.asarray(loaded, dtype=np.uint8)


def _patch_count(harness, config_id: int, song: str) -> int:
    rec = catalog.compact_catalog_song(harness.con, config_id, song)
    return int(rec.patch_count)


def _materialize(harness, *, run_id, song_ids=None, working_memory=2**20, **kw):
    """Call the TARGET §D signature (RED until P1-S2 rewrites search_views.py)."""
    return sv.materialize_search_view(
        harness.con,
        harness.stream_store,
        song_ids=tuple(song_ids or [_S_SEARCHABLE, _S_PARTIAL, _S_ZERO]),
        backbone="effnet",
        run_id=run_id,
        working_memory=working_memory,
        **kw,
    )


# --------------------------------------------------------------------------- #
# Catalog-truth expectation helpers (independent of the materialize impl)      #
# --------------------------------------------------------------------------- #


def _catalog_rows(harness, config_id: int, song: str):
    """The disposable rows a correct §D materialization MUST produce for one song.

    One row per compact seg_meta with a non-null ``search_medoid_source_patch_idx``; rows are
    derived purely from the compact catalog, never from any view code.
    """
    rows = [
        (config_id, song, int(seg.seg_id), int(seg.search_medoid_source_patch_idx))
        for seg in catalog.compact_segments_by_config_song(harness.con, config_id, song)
        if seg.search_medoid_source_patch_idx is not None
    ]
    rows.sort()
    return rows


def _expected_view(harness, config_id: int, songs):
    """``(expected_row_addresses, expected_weights)`` for the requested songs (ordered)."""
    addresses: list[tuple[int, str, int, int]] = []
    weights: list[float] = []
    for song in sorted(songs):  # canonical ascending song order, matching the view contract
        segs = list(catalog.compact_segments_by_config_song(harness.con, config_id, song))
        total = float(sum(int(s.searchable_count) for s in segs))
        for seg in segs:
            if seg.search_medoid_source_patch_idx is None:
                continue  # null medoid -> no row, no candidate weight mass
            addresses.append((config_id, song, int(seg.seg_id), int(seg.search_medoid_source_patch_idx)))
            weights.append(float(seg.searchable_weight) if total > 0 else 0.0)
    return tuple(addresses), np.asarray(weights, dtype=np.float32)


def _segs(harness, config_id: int, song: str):
    return list(catalog.compact_segments_by_config_song(harness.con, config_id, song))


# --------------------------------------------------------------------------- #
# 1. Rows are ONLY observed medoid source indices                             #
# --------------------------------------------------------------------------- #


def test_rows_only_observed_medoid_source_indices(compact_catalog_factory, con, tmp_path):
    """View row addresses are (config_id, song_id, seg_id, source_patch_idx) with the source
    index equal to the catalog's stored medoid; null-medoid segments contribute no row;
    absorbed/silent source patches never appear as addresses or gathered vectors."""
    harness = _build_harness(compact_catalog_factory, con, tmp_path / "out", run_id="run-spec-1")
    try:
        cfg = _config_id(harness)
        expected, _weights = _expected_view(harness, cfg, [_S_SEARCHABLE, _S_PARTIAL, _S_ZERO])

        # ---- precondition: the fixture really exercises all three behaviours ----
        # s1: fully searchable (total > 0, >= 1 medoid row).
        s1_segs = _segs(harness, cfg, _S_SEARCHABLE)
        assert sum(int(s.searchable_count) for s in s1_segs) > 0
        assert any(s.search_medoid_source_patch_idx is not None for s in s1_segs)
        # ps: a null-medoid segment coexists with a searchable segment.
        ps_segs = _segs(harness, cfg, _S_PARTIAL)
        assert sum(int(s.searchable_count) for s in ps_segs) > 0
        assert any(s.search_medoid_source_patch_idx is None for s in ps_segs)
        # zs: zero total searchable -> metadata-only, contributes nothing.
        zs_rec = catalog.compact_catalog_song(harness.con, cfg, _S_ZERO)
        assert int(zs_rec.total_searchable_count) == 0
        zs_expected, zs_weights = _expected_view(harness, cfg, [_S_ZERO])
        assert zs_expected == ()
        assert zs_weights.size == 0

        # ---- target materialization (RED until P1-S2) ----
        record = _materialize(harness, run_id="run-spec-1")

        assert tuple(record.row_addresses) == expected, (
            f"row_addresses must equal the catalog-derived observed-medoid rows; "
            f"got {len(record.row_addresses)} rows, expected {len(expected)}"
        )
        for row in record.row_addresses:
            assert len(row) == 4, "row address must be (config_id, song_id, seg_id, source_patch_idx)"
            config_id, song, seg_id, source_idx = row
            matched = [s for s in _segs(harness, int(config_id), song) if int(s.seg_id) == int(seg_id)]
            assert len(matched) == 1, "each row must resolve to exactly one compact seg_meta"
            seg = matched[0]
            assert int(seg.search_medoid_source_patch_idx) == int(source_idx)
            # source patch must be an OBSERVED (non-absorbed, non-silent) searchable member.
            mask = _mask_array(harness, song)
            patch_count = _patch_count(harness, int(config_id), song)
            members = reconstruct_searchable_indices(seg, mask, patch_count)
            assert int(source_idx) in {int(i) for i in members}, (
                f"row source index {source_idx} of seg {seg_id} is not an observed searchable "
                f"member (absorbed/silent indices must never appear)"
            )
        assert tuple(record.row_addresses) == tuple(sorted(record.row_addresses)), (
            "row_addresses must be ordered ascending"
        )
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# 2. Candidate weights are searchable-count normalized                         #
# --------------------------------------------------------------------------- #


def test_weights_are_searchable_count_normalized_and_sum_to_one(compact_catalog_factory, con, tmp_path):
    """Each row weight == seg_meta.searchable_weight == searchable_count / total_searchable_song,
    and per searchable song the present-row weights sum to 1."""
    harness = _build_harness(compact_catalog_factory, con, tmp_path / "out", run_id="run-spec-2")
    try:
        cfg = _config_id(harness)
        songs = [_S_SEARCHABLE, _S_PARTIAL]
        expected_addresses, expected_weights = _expected_view(harness, cfg, songs)

        # Precondition: each searchable segment's stored weight equals count/total.
        for song in songs:
            segs = _segs(harness, cfg, song)
            total = float(sum(int(s.searchable_count) for s in segs))
            assert total > 0
            for seg in segs:
                expected = int(seg.searchable_count) / total if total > 0 else 0.0
                assert seg.searchable_weight == pytest.approx(expected, abs=1e-6)
        assert expected_weights.size > 0

        record = _materialize(harness, run_id="run-spec-2", song_ids=songs)

        got = np.asarray(record.weights, dtype=np.float64)
        assert got.shape == (len(record.row_addresses),), "weights must be per-row, aligned to row_addresses"
        assert tuple(record.row_addresses) == expected_addresses
        np.testing.assert_allclose(got, np.asarray(expected_weights, dtype=np.float64), atol=1e-6)

        # Per-song the present-row weights sum to 1 (silenced segments carry weight 0 / no row).
        row_weights = dict.fromkeys(songs, 0.0)
        for row, w in zip(record.row_addresses, got, strict=True):
            row_weights[row[1]] += float(w)
        for song in songs:
            assert row_weights[song] == pytest.approx(1.0, abs=1e-6), (
                f"weights for {song} must sum to 1 over its disposable rows"
            )
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# 3. Zero-searchable candidates are excluded                                   #
# --------------------------------------------------------------------------- #


def test_zero_searchable_candidate_excluded_metadata_only(compact_catalog_factory, con, tmp_path):
    """A song whose total searchable count is 0 stays metadata-only: it produces no view row,
    no gathered vector, and never appears as a candidate address."""
    harness = _build_harness(compact_catalog_factory, con, tmp_path / "out", run_id="run-spec-3")
    try:
        cfg = _config_id(harness)
        zs_rec = catalog.compact_catalog_song(harness.con, cfg, _S_ZERO)
        assert int(zs_rec.total_searchable_count) == 0
        assert int(zs_rec.patch_count) == _N  # stream still present -> metadata only

        record = _materialize(harness, run_id="run-spec-3", song_ids=[_S_SEARCHABLE, _S_PARTIAL, _S_ZERO])

        assert all(row[1] != _S_ZERO for row in record.row_addresses), (
            "zero-searchable song must never appear as a disposable row/candidate"
        )
        assert not any(row[1] == _S_ZERO for row in record.row_addresses)
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# 4. Vectors come from CURRENT immutable stream gathers on observed indices    #
# --------------------------------------------------------------------------- #


def test_gather_requests_only_observed_source_indices(compact_catalog_factory, con, tmp_path, monkeypatch):
    """Gathering goes through StreamStore.batch_gather restricted to the observed medoid source
    indices of each song — never a whole-matrix / range gather of non-medoid rows, and each
    gathered vector equals the row's own medoid from the current stream."""
    harness = _build_harness(compact_catalog_factory, con, tmp_path / "out", run_id="run-spec-4")
    try:
        cfg = _config_id(harness)
        expected_addresses, _ = _expected_view(harness, cfg, [_S_SEARCHABLE, _S_PARTIAL, _S_ZERO])

        real_gather = harness.stream_store.batch_gather
        calls: list[tuple[str, object]] = []

        def _recording_gather(song, backbone, indices, **kw):
            calls.append((song, tuple(int(i) for i in indices)))
            return real_gather(song, backbone, indices, **kw)

        monkeypatch.setattr(harness.stream_store, "batch_gather", _recording_gather)

        record = _materialize(harness, run_id="run-spec-4")
        assert calls, "materialization must gather through StreamStore.batch_gather"

        # expected medoid set per song (across rows that appear)
        expected_sources: dict[str, set[int]] = {}
        for _cfg_loop, song, _seg_id, source_idx in expected_addresses:
            expected_sources.setdefault(song, set()).add(int(source_idx))

        got_sources: dict[str, set[int]] = {}
        for song, indices in calls:
            for i in indices:
                got_sources.setdefault(song, set()).add(int(i))

        assert set(got_sources) == set(expected_sources), (
            "gathers must be restricted to songs that actually contribute observed rows"
        )
        for song, indices in got_sources.items():
            medoids = expected_sources[song]
            assert indices <= medoids, (
                f"gather for {song} requested indices {sorted(indices)} not all within the "
                f"observed medoid set {sorted(medoids)} — no whole-matrix/range gather allowed"
            )
            assert indices == medoids, f"gather for {song} must cover exactly the observed medoid source indices"

        # Row vectors equal the current-stream gather at each row's address.
        vectors = _record_vectors(harness, record)
        assert vectors.shape[0] == len(record.row_addresses)
        for i, (_cfg_loop, song, _seg_id, source_idx) in enumerate(record.row_addresses):
            (gathered,) = real_gather(song, "effnet", [int(source_idx)])
            np.testing.assert_array_equal(vectors[i], gathered)
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# 5. Per-run regeneration — file existence never authorizes reuse              #
# --------------------------------------------------------------------------- #


def test_materialize_always_regenerates(compact_catalog_factory, con, tmp_path, monkeypatch):
    """Materializing twice for the SAME run re-gathers and rewrites; a pre-existing disposable
    view file never short-circuits gathering."""
    harness = _build_harness(compact_catalog_factory, con, tmp_path / "out", run_id="run-spec-5")
    try:
        cfg = _config_id(harness)
        _expected_view(harness, cfg, [_S_SEARCHABLE, _S_PARTIAL, _S_ZERO])

        first = _materialize(harness, run_id="run-spec-5")

        # Record how many view files exist after the first pass.
        view_root = harness.stream_store.output_root

        def _disposable_files(record):
            if getattr(record, "view_ref", None):
                d = view_root / record.view_ref
                if d.exists():
                    return sorted(p.name for p in d.iterdir() if p.is_file())
            return []

        files_after_first = _disposable_files(first)

        real_gather = harness.stream_store.batch_gather
        n_calls = [0]

        def _counting_gather(song, backbone, indices, **kw):
            n_calls[0] += 1
            return real_gather(song, backbone, indices, **kw)

        monkeypatch.setattr(harness.stream_store, "batch_gather", _counting_gather)

        second = _materialize(harness, run_id="run-spec-5")
        assert n_calls[0] > 0, "second materialization must re-gather even though a view already exists"
        # Same logical identity (keyset/content), freshly regenerated.
        assert tuple(first.row_addresses) == tuple(second.row_addresses)
        files_after_second = _disposable_files(second)
        assert files_after_second, "materialization must write a disposable view payload"
        assert files_after_second == files_after_first
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# 6. Finite outputs only; non-finite source data fails closed                  #
# --------------------------------------------------------------------------- #


def test_vectors_and_weights_are_finite(compact_catalog_factory, con, tmp_path):
    """Gathered vectors and normalized weights carry no NaN/Infinity."""
    harness = _build_harness(compact_catalog_factory, con, tmp_path / "out", run_id="run-spec-6")
    try:
        record = _materialize(harness, run_id="run-spec-6")
        vectors = _record_vectors(harness, record)
        weights = np.asarray(record.weights, dtype=np.float64)
        assert np.all(np.isfinite(vectors)), "view vectors must all be finite"
        assert np.all(np.isfinite(weights)), "view weights must all be finite"
    finally:
        harness.close()


def test_nonfinite_source_data_fails_closed(compact_catalog_factory, con, tmp_path, monkeypatch):
    """If the CURRENT stream gather returns a non-finite observed-medoid row, materialization
    must fail closed (raise) rather than persist a NaN/Inf disposable view."""
    harness = _build_harness(compact_catalog_factory, con, tmp_path / "out", run_id="run-spec-6b")
    try:
        real_gather = harness.stream_store.batch_gather

        def _poisoned_gather(song, backbone, indices, **kw):
            out = real_gather(song, backbone, indices, **kw)
            out = np.array(out, dtype=np.float64, copy=True)
            if out.ndim == 2 and out.shape[0]:
                out[0] = np.nan
            return out.astype(np.float32)

        monkeypatch.setattr(harness.stream_store, "batch_gather", _poisoned_gather)
        with pytest.raises((ValueError, FloatingPointError)):
            _materialize(harness, run_id="run-spec-6b")
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# 7. No audio / model / ONNX / CUDA seams are touched during materialization  #
# --------------------------------------------------------------------------- #


class _RaisingSentinel:
    def __init__(self, name: str):
        self.name = name

    def __call__(self, *args, **kwargs):  # noqa: ARG002
        raise AssertionError(
            f"CPU sentinel {self.name} was called during materialization — materializing a "
            "search view must never touch audio/model/ONNX/CUDA seams"
        )


def _install_sentinels(monkeypatch) -> list[str]:
    """Patch audio/model/ONNX/CUDA seams so any call fails the test; return installed names."""
    targets: list[str] = []
    if _config is not None and hasattr(_config, "discover_audio"):
        targets.append(f"{_config.__name__}.discover_audio")
    if onnxruntime is not None:
        targets.append("onnxruntime.InferenceSession")
    if torch is not None:
        targets.append("torch.cuda.is_available")
    if ml_session_comp is not None:
        if hasattr(ml_session_comp, "create_session"):
            targets.append(f"{ml_session_comp.__name__}.create_session")
        if hasattr(ml_session_comp, "_run_in_batches"):
            targets.append(f"{ml_session_comp.__name__}._run_in_batches")
    installed: list[str] = []
    for dotted in targets:
        # Sentinel installation must tolerate import-resolution failures on env-dependent seams
        # (e.g. ``nomarr.components.ml`` pulls ``psutil`` which may be absent): a seam that cannot
        # even be imported in this environment simply is not installed, leaving the other seams to
        # keep the guard non-vacuous.  A seam that IS installed must never be called.
        try:
            monkeypatch.setattr(dotted, _RaisingSentinel(dotted))
        except (ImportError, AttributeError, ModuleNotFoundError):
            continue
        installed.append(dotted)
    return installed


def test_materialize_makes_no_audio_model_onnx_cuda_calls(compact_catalog_factory, con, tmp_path, monkeypatch):
    """Materializing a search view is pure catalog+stream CPU work — never audio loaders, model
    sessions, ONNX inference, or CUDA.  A sentinel raised inside those seams must FAIL the test
    (catching the sentinel is not success)."""
    harness = _build_harness(compact_catalog_factory, con, tmp_path / "out", run_id="run-spec-7")
    try:
        installed = _install_sentinels(monkeypatch)
        assert installed, "no audio/model/ONNX/CUDA seam was available to sentinel — vacuous test"
        _materialize(harness, run_id="run-spec-7")  # must complete without touching any seam
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# 8. NO search_view_hash on the disposable view identity                       #
# --------------------------------------------------------------------------- #


def test_target_signature_and_record_have_no_search_view_hash(compact_catalog_factory, con, tmp_path):
    """The §D view identity must not introduce or depend on ``search_view_hash``: the target
    signature takes catalog/stream_store/song_ids/backbone/run_id/working_memory (no corpus, no
    query_keyset, no hash argument) and the returned record exposes no ``search_view_hash``."""
    harness = _build_harness(compact_catalog_factory, con, tmp_path / "out", run_id="run-spec-8")
    try:
        _config_id(harness)
        record = _materialize(harness, run_id="run-spec-8")
        assert not hasattr(record, "search_view_hash"), "SearchViewRecord must not carry a search_view_hash member"
        # The disposable payload persisted for the view must not mention the hash either.
        ref = getattr(record, "view_ref", None)
        if ref is not None:
            keys = harness.stream_store.output_root / ref / "keys.json"
            if keys.exists():
                payload = __import__("json").loads(keys.read_bytes())
                assert "search_view_hash" not in payload, (
                    "disposable view keyset payload must not contain search_view_hash"
                )
    finally:
        harness.close()


# --------------------------------------------------------------------------- #
# Shared accessor: gather the recorded vectors (in-memory or on-disk view)     #
# --------------------------------------------------------------------------- #


def _record_vectors(harness, record) -> np.ndarray:
    """Return the recorded gathered vectors for *record*.

    §D requires the record to expose its gathered observed-medoid vectors.  Prefer the in-memory
    ``record.vectors`` (P1-S2's intended home); fall back to the disposable on-disk view the
    record references, so the semantic assertions hold regardless of P1-S2's storage choice.
    """
    vectors = getattr(record, "vectors", None)
    if isinstance(vectors, np.ndarray):
        return vectors
    ref = getattr(record, "view_ref", None)
    if ref is None:
        raise AssertionError("SearchViewRecord must expose gathered vectors via .vectors or a .view_ref payload")
    path = harness.stream_store.output_root / ref / "vectors.npy"
    if not path.exists():
        raise AssertionError("SearchViewRecord must expose gathered vectors via .vectors or a .view_ref payload")
    return np.load(path, allow_pickle=False)
