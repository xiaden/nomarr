"""Spec-first tests for the shared-boundary head phase (LEGACY INTERIM surface).

NOTE (Plan E, Phase 1): this file now covers the LEGACY interim inclusive-range
``head_pooling`` helper and the LEGACY ``classify.run_shared_ptc_head_pooling``
runner, retained callable through Phase 4 (D1).  The ACTIVE canonical exact-membership
helper, per-config outcome records, and CPU runner are covered in
``test_head_analysis_active.py``.  This legacy coverage stays green unchanged.

Covers the pure ``pool_head_outputs_over_ptc_boundaries`` helper, the
extended ``cache.binned_ptc_heads`` provenance metadata, and the non-blocking
``classify.run_shared_ptc_head_pooling`` orchestration:

* inclusive boundary means and one-patch bins;
* invalid-range / weight-alignment rejection;
* ``act[1]`` (never ``act[0]``) class-1 selection;
* no head-specific segmentation calls (AST guard over the new surfaces);
* EffNet-only defaulting and non-blocking primary-success behavior;
* provenance fields, finite outputs, cache round trips, stale-source rejection.
"""

from __future__ import annotations

import ast
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest

import scripts.embedding_research.classify as classify_mod
from scripts.embedding_research.cache import binned_ptc_heads as binned_ptc_heads_cache
from scripts.embedding_research.cache_identity import SCORING_SEMANTICS_VERSION
from scripts.embedding_research.head_pooling import (
    BOUNDARY_SOURCE_EFFNET_PTC,
    HeadBoundaryPoolResult,
    pool_head_outputs_over_ptc_boundaries,
)

_RESEARCH_DIR = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# pool_head_outputs_over_ptc_boundaries — inclusive boundary means
# ---------------------------------------------------------------------------


def test_inclusive_boundary_means() -> None:
    """Each bin averages over the INCLUSIVE [start, end] patch range."""
    rng = np.random.default_rng(0)
    acts = rng.random((10, 3)).astype(np.float32)
    start = np.array([0, 5], dtype=np.int32)
    end = np.array([3, 9], dtype=np.int32)
    weights = np.array([4, 5], dtype=np.int32)

    result = pool_head_outputs_over_ptc_boundaries(acts, start, end, weights)

    assert isinstance(result, HeadBoundaryPoolResult)
    assert result.acts.shape == (2, 3)
    np.testing.assert_allclose(result.acts[0], acts[0:4].mean(axis=0), rtol=1e-5)
    np.testing.assert_allclose(result.acts[1], acts[5:10].mean(axis=0), rtol=1e-5)


def test_one_patch_bins_return_patch_unchanged() -> None:
    """A bin with exactly one patch returns that patch's acts unchanged."""
    acts = np.array([[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]], dtype=np.float32)
    start = np.array([0, 1, 2], dtype=np.int32)
    end = np.array([0, 1, 2], dtype=np.int32)
    weights = np.array([1, 1, 1], dtype=np.int32)

    result = pool_head_outputs_over_ptc_boundaries(acts, start, end, weights)

    np.testing.assert_array_equal(result.acts, acts)
    np.testing.assert_array_equal(result.class1, acts[:, 1].astype(np.float32))


# ---------------------------------------------------------------------------
# invalid ranges / weight alignment
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "start,end,weights",
    [
        # negative start
        (np.array([-1, 0], dtype=np.int32), np.array([0, 2], dtype=np.int32), np.array([1, 3], dtype=np.int32)),
        # negative end
        (np.array([0, 0], dtype=np.int32), np.array([-1, 2], dtype=np.int32), np.array([1, 3], dtype=np.int32)),
        # start > end
        (np.array([4, 0], dtype=np.int32), np.array([2, 4], dtype=np.int32), np.array([3, 5], dtype=np.int32)),
        # end out of range
        (np.array([0], dtype=np.int32), np.array([9], dtype=np.int32), np.array([10], dtype=np.int32)),
        # non-positive weight
        (np.array([0], dtype=np.int32), np.array([2], dtype=np.int32), np.array([0], dtype=np.int32)),
    ],
)
def test_invalid_ranges_rejected(start, end, weights) -> None:
    """Malformed boundary/weight arrays raise ValueError (strict, no silent zeros)."""
    acts = np.ones((6, 2), dtype=np.float32)
    with pytest.raises(ValueError):
        pool_head_outputs_over_ptc_boundaries(acts, start, end, weights)


def test_boundary_coindex_mismatch_rejected() -> None:
    """bin_start_idx and bin_end_idx must have the same length."""
    acts = np.ones((5, 2), dtype=np.float32)
    with pytest.raises(ValueError, match="co-indexed"):
        pool_head_outputs_over_ptc_boundaries(
            acts,
            np.array([0, 2], dtype=np.int32),
            np.array([1], dtype=np.int32),
            np.array([1], dtype=np.int32),
        )


def test_weight_alignment_rejected_and_preserved() -> None:
    """Weights must be co-indexed with the boundaries and are preserved exactly."""
    acts = np.ones((5, 2), dtype=np.float32)
    # length mismatch -> rejected
    with pytest.raises(ValueError, match="co-indexed"):
        pool_head_outputs_over_ptc_boundaries(
            acts,
            np.array([0, 2], dtype=np.int32),
            np.array([1, 3], dtype=np.int32),
            np.array([2, 3, 4], dtype=np.int32),
        )
    # valid weights are preserved unchanged in the result
    result = pool_head_outputs_over_ptc_boundaries(
        acts,
        np.array([0, 2], dtype=np.int32),
        np.array([1, 3], dtype=np.int32),
        np.array([2, 5], dtype=np.int32),
    )
    np.testing.assert_array_equal(result.weights, [2, 5])


def test_nonfinite_acts_rejected() -> None:
    """NaN/Inf activations are rejected at the pure boundary."""
    acts = np.array([[1.0, np.nan], [0.0, 1.0]], dtype=np.float32)
    with pytest.raises(ValueError, match="finite"):
        pool_head_outputs_over_ptc_boundaries(
            acts, np.array([0], dtype=np.int32), np.array([1], dtype=np.int32), np.array([2], dtype=np.int32)
        )


def test_1d_acts_rejected() -> None:
    with pytest.raises(ValueError, match="2-D"):
        pool_head_outputs_over_ptc_boundaries(
            np.ones(4, dtype=np.float32),
            np.array([0], dtype=np.int32),
            np.array([3], dtype=np.int32),
            np.array([4], dtype=np.int32),
        )


# ---------------------------------------------------------------------------
# act[1] selection (never act[0])
# ---------------------------------------------------------------------------


def test_class1_values_come_from_act1_never_act0() -> None:
    """class1 is the pooled column-1 value; act[0] never influences it."""
    # Column 0 varies wildly; column 1 is what class1 must reflect.
    acts = np.array(
        [[0.0, 0.1], [1.0, 0.3], [0.0, 0.5], [1.0, 0.7], [0.0, 0.9]],
        dtype=np.float32,
    )
    start = np.array([0, 2], dtype=np.int32)
    end = np.array([1, 4], dtype=np.int32)
    weights = np.array([2, 3], dtype=np.int32)

    result = pool_head_outputs_over_ptc_boundaries(acts, start, end, weights)

    # class1 is the mean of act[1] over each bin, i.e. pooled[:, 1].
    expected = np.array([(0.1 + 0.3) / 2, (0.5 + 0.7 + 0.9) / 3], dtype=np.float32)
    np.testing.assert_allclose(result.class1, expected, rtol=1e-5)
    np.testing.assert_allclose(result.class1, result.acts[:, 1], rtol=1e-6)
    # Explicitly not act[0]: flipping column 0 leaves class1 unchanged.
    flipped = acts.copy()
    flipped[:, 0] = 1.0 - flipped[:, 0]
    flipped_result = pool_head_outputs_over_ptc_boundaries(flipped, start, end, weights)
    np.testing.assert_array_equal(flipped_result.class1, result.class1)


# ---------------------------------------------------------------------------
# provenance / finite / JSON-safety of the pure helper
# ---------------------------------------------------------------------------


def test_result_provenance_and_finite() -> None:
    acts = np.random.default_rng(1).random((8, 2)).astype(np.float32)
    result = pool_head_outputs_over_ptc_boundaries(
        acts,
        np.array([0, 4], dtype=np.int32),
        np.array([3, 7], dtype=np.int32),
        np.array([4, 4], dtype=np.int32),
    )
    assert result.boundary_source == BOUNDARY_SOURCE_EFFNET_PTC
    assert result.finite is True
    assert np.all(np.isfinite(result.acts))
    assert np.all(np.isfinite(result.class1))


def test_result_json_safe() -> None:
    acts = np.random.default_rng(2).random((6, 2)).astype(np.float32)
    result = pool_head_outputs_over_ptc_boundaries(
        acts,
        np.array([0, 3], dtype=np.int32),
        np.array([2, 5], dtype=np.int32),
        np.array([3, 3], dtype=np.int32),
    )
    payload = json.loads(result.to_json())
    assert payload["boundary_source"] == BOUNDARY_SOURCE_EFFNET_PTC
    assert payload["finite"] is True
    assert len(payload["class1"]) == 2


# ---------------------------------------------------------------------------
# cache provenance metadata
# ---------------------------------------------------------------------------


@pytest.fixture()
def ptc_heads_cache(tmp_path: Path, monkeypatch):
    """Patch CACHE_BASE on the binned_ptc_heads module to a temp directory."""
    monkeypatch.setattr(binned_ptc_heads_cache, "CACHE_BASE", tmp_path / "binned_ptc_heads")
    return binned_ptc_heads_cache


def test_cache_save_carries_provenance_fields(ptc_heads_cache) -> None:
    acts = np.array([[0.2, 0.8], [0.65, 0.35]], dtype=np.float32)
    weights = np.array([2, 2], dtype=np.int32)
    start = np.array([0, 2], dtype=np.int32)
    end = np.array([1, 3], dtype=np.int32)

    ptc_heads_cache.save(
        "effnet",
        "mood",
        "temporal_global",
        1.0,
        "s1",
        acts,
        weights,
        bin_start_idx=start,
        bin_end_idx=end,
        boundary_source=BOUNDARY_SOURCE_EFFNET_PTC,
        scoring_semantics_version=SCORING_SEMANTICS_VERSION,
        finite=True,
    )

    meta = ptc_heads_cache.load_metadata("effnet", "mood", "temporal_global", 1.0, "s1")
    assert meta is not None
    assert meta["boundary_source"] == BOUNDARY_SOURCE_EFFNET_PTC
    assert meta["backbone"] == "effnet"
    assert meta["head"] == "mood"
    assert meta["bin_mode"] == "temporal_global"
    assert meta["threshold"] == pytest.approx(1.0)
    assert meta["song_id"] == "s1"
    assert meta["scoring_semantics_version"] == SCORING_SEMANTICS_VERSION
    assert meta["finite"] is True
    np.testing.assert_array_equal(meta["bin_start_idx"], start)
    np.testing.assert_array_equal(meta["bin_end_idx"], end)
    np.testing.assert_array_equal(meta["weights"], weights)


def test_cache_round_trip_acts_weights_and_valid(ptc_heads_cache) -> None:
    acts = np.array([[0.1, 0.9], [0.6, 0.4]], dtype=np.float32)
    weights = np.array([5, 3], dtype=np.int32)
    ptc_heads_cache.save("effnet", "mood", "temporal_global", 1.35, "s1", acts, weights)

    loaded = ptc_heads_cache.load("effnet", "mood", "temporal_global", 1.35, "s1")
    assert loaded is not None
    got_acts, got_weights = loaded
    np.testing.assert_array_equal(got_acts, acts)
    np.testing.assert_array_equal(got_weights, weights)
    assert ptc_heads_cache.check_cache_valid("effnet", "mood", "temporal_global", 1.35, "s1") is True


def test_stale_boundary_source_rejected(ptc_heads_cache) -> None:
    acts = np.ones((2, 2), dtype=np.float32)
    weights = np.array([2, 2], dtype=np.int32)
    ptc_heads_cache.save(
        "effnet",
        "mood",
        "temporal_global",
        1.0,
        "s1",
        acts,
        weights,
        boundary_source="ctp",  # a repurposed CTP path must be rejected as stale
    )
    meta = ptc_heads_cache.load_metadata("effnet", "mood", "temporal_global", 1.0, "s1")
    assert meta is not None
    with pytest.raises(ValueError, match="boundary_source"):
        ptc_heads_cache.validate_boundary_source(meta)
    assert ptc_heads_cache.check_cache_valid("effnet", "mood", "temporal_global", 1.0, "s1") is False


def test_stale_scoring_semantics_rejected(ptc_heads_cache) -> None:
    acts = np.ones((2, 2), dtype=np.float32)
    weights = np.array([2, 2], dtype=np.int32)
    ptc_heads_cache.save(
        "effnet",
        "mood",
        "temporal_global",
        1.0,
        "s1",
        acts,
        weights,
        scoring_semantics_version=SCORING_SEMANTICS_VERSION - 1,
    )
    meta = ptc_heads_cache.load_metadata("effnet", "mood", "temporal_global", 1.0, "s1")
    assert meta is not None
    with pytest.raises(ValueError, match="scoring_semantics_version"):
        ptc_heads_cache.validate_boundary_source(meta)
    assert ptc_heads_cache.check_cache_valid("effnet", "mood", "temporal_global", 1.0, "s1") is False


def test_validate_missing_cache_rejected(ptc_heads_cache) -> None:
    with pytest.raises(ValueError, match="absent or corrupt"):
        ptc_heads_cache.validate_boundary_source(None)


# ---------------------------------------------------------------------------
# no head-specific segmentation calls (AST guard)
# ---------------------------------------------------------------------------


def _function_body_code_names(path: Path, name: str) -> set[str]:
    """Collect identifier/attribute names referenced by a function's CODE (not docstring)."""
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            doc_lines: set[int] = set()
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                doc = body[0]
                doc_lines = set(range(getattr(doc, "lineno", 0), (getattr(doc, "end_lineno", None) or doc.lineno) + 1))
            names: set[str] = set()
            for child in ast.walk(node):
                if getattr(child, "lineno", None) in doc_lines:
                    continue  # documentation mentions are not code references
                if isinstance(child, ast.Name):
                    names.add(child.id)
                elif isinstance(child, ast.Attribute):
                    names.add(child.attr)
            return names
    raise AssertionError(f"function {name!r} not found in {path}")


_FORBIDDEN = ("temporal_segment", "segment_fn", "binned_ctp", "strategy_ctp")


def test_pooling_helper_has_no_segmentation() -> None:
    """The pure pooling helper never runs segmentation and never creates head-specific bins."""
    names = _function_body_code_names(_RESEARCH_DIR / "head_pooling.py", "pool_head_outputs_over_ptc_boundaries")
    for token in _FORBIDDEN:
        assert token not in names, f"pool helper must not reference {token!r}"


def test_shared_phase_has_no_segmentation_and_no_ctp() -> None:
    """run_shared_ptc_head_pooling consumes only EffNet PTC cache boundaries."""
    names = _function_body_code_names(_RESEARCH_DIR / "classify.py", "run_shared_ptc_head_pooling")
    for token in _FORBIDDEN:
        assert token not in names, f"run_shared_ptc_head_pooling must not reference {token!r}"


# ---------------------------------------------------------------------------
# orchestration: EffNet-only defaulting + non-blocking primary-success
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_ml_session_comp(monkeypatch):
    """Inject a fake nomarr ml_session_comp so orchestration avoids ONNX/nomarr deps."""
    for name in (
        "nomarr.components.ml",
        "nomarr.components.ml.onnx",
        "nomarr.components.ml.onnx.ml_session_comp",
    ):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
    fake = sys.modules["nomarr.components.ml.onnx.ml_session_comp"]
    fake._BACKBONE_BATCH_SIZE = 64
    fake._run_in_batches = lambda fn, arr, _bs: fn(arr)
    fake.create_session = lambda *_a, **_k: None
    monkeypatch.setitem(sys.modules, "nomarr.components.ml", sys.modules["nomarr.components.ml"])
    monkeypatch.setitem(sys.modules, "nomarr.components.ml.onnx", sys.modules["nomarr.components.ml.onnx"])
    monkeypatch.setitem(
        sys.modules,
        "nomarr.components.ml.onnx.ml_session_comp",
        sys.modules["nomarr.components.ml.onnx.ml_session_comp"],
    )
    return fake


@pytest.mark.usefixtures("fake_ml_session_comp")
def test_effnet_only_defaulting(monkeypatch) -> None:
    """backbones=None defaults to ['effnet'] and the phase is non-blocking."""
    monkeypatch.setattr(classify_mod, "HEADS", {"effnet": {"mood": "fake"}, "musicnn": {"mood": "fake"}})
    monkeypatch.setattr(classify_mod._binned_ptc_cache, "list_done_keys", lambda: set())

    manifest = classify_mod.run_shared_ptc_head_pooling(None)

    assert manifest.backbones == ("effnet",)
    assert manifest.primary_analysis_succeeded is True
    assert manifest.boundary_source == BOUNDARY_SOURCE_EFFNET_PTC
    assert any(scope.startswith("backbone:effnet") for scope, _ in manifest.skip_reasons)


@pytest.mark.usefixtures("fake_ml_session_comp")
def test_head_phase_missing_is_nonblocking(monkeypatch) -> None:
    """Absent head models/caches never raise and never block primary analysis."""
    # No heads configured for the backbone.
    monkeypatch.setattr(classify_mod, "HEADS", {"effnet": {}})
    monkeypatch.setattr(
        classify_mod._binned_ptc_cache,
        "list_done_keys",
        lambda: {("s1", "effnet", "temporal_global", 1.0)},
    )
    monkeypatch.setattr(classify_mod, "patches_path", lambda _sid, _bb: Path("/nonexistent/sidecar"))

    manifest = classify_mod.run_shared_ptc_head_pooling(None)

    assert manifest.primary_analysis_succeeded is True
    assert any("no configured heads" in reason for _, reason in manifest.skip_reasons)
    assert manifest.results == ()


@pytest.mark.usefixtures("fake_ml_session_comp")
def test_shared_phase_pools_and_writes_provenance_cache(monkeypatch, tmp_path) -> None:
    """A real pooling run writes a provenance-backed cache entry and reports done."""
    acts_out = np.array(
        [[0.1, 0.9], [0.3, 0.7], [0.5, 0.5], [0.8, 0.2]],
        dtype=np.float32,
    )  # [4 patches, 2 classes]

    class _FakeSession:
        def run(self, names, _feeds):
            assert names == ["activations"]
            return [acts_out]

    monkeypatch.setattr(classify_mod, "HEADS", {"effnet": {"mood": "fake"}})
    monkeypatch.setattr(
        classify_mod._binned_ptc_cache,
        "list_done_keys",
        lambda: {("s1", "effnet", "temporal_global", 1.0)},
    )

    # Write a real PTC cache npz with boundaries/weights for the pooling path.
    ptc_dir = tmp_path / "ptc"
    ptc_dir.mkdir(parents=True, exist_ok=True)
    ptc_npz = ptc_dir / "s1.npz"
    np.savez(
        ptc_npz,
        bin_start_idx=np.array([0, 2], dtype=np.int32),
        bin_end_idx=np.array([1, 3], dtype=np.int32),
        weights=np.array([2, 2], dtype=np.int32),
    )
    monkeypatch.setattr(classify_mod._binned_ptc_cache, "cache_path", lambda *_args: ptc_npz)

    # Redirect the patches sidecar to a real temp file.
    sidecar = tmp_path / "s1.effnet.npy"
    np.save(sidecar, acts_out)
    monkeypatch.setattr(classify_mod, "patches_path", lambda _sid, _bb: sidecar)

    # Redirect the head cache root and provide the fake session via head_sessions.
    monkeypatch.setattr(binned_ptc_heads_cache, "CACHE_BASE", tmp_path / "binned_ptc_heads")
    head_sessions = {"effnet": {"mood": _FakeSession()}}

    manifest = classify_mod.run_shared_ptc_head_pooling(None, head_sessions=head_sessions)

    assert manifest.primary_analysis_succeeded is True
    assert manifest.backbones == ("effnet",)
    assert len(manifest.results) == 1
    rec = manifest.results[0]
    assert rec.status == "done"
    assert rec.head == "mood"
    assert rec.bin_mode == "temporal_global"
    assert rec.threshold == pytest.approx(1.0)
    assert rec.n_songs == 1 and rec.n_pooled == 1
    assert rec.finite is True

    # Cache entry written with provenance metadata.
    assert binned_ptc_heads_cache.check_cache_valid("effnet", "mood", "temporal_global", 1.0, "s1") is True
    loaded = binned_ptc_heads_cache.load("effnet", "mood", "temporal_global", 1.0, "s1")
    assert loaded is not None
    got_acts, got_weights = loaded
    np.testing.assert_allclose(got_acts, [[0.2, 0.8], [0.65, 0.35]], rtol=1e-5)
    np.testing.assert_array_equal(got_weights, [2, 2])


@pytest.mark.usefixtures("fake_ml_session_comp")
def test_shared_phase_is_deterministic(monkeypatch, tmp_path) -> None:
    """Repeated runs produce identical JSON-safe manifests (deterministic ordering)."""
    acts_out = np.random.default_rng(3).random((4, 2)).astype(np.float32)

    class _FakeSession:
        def run(self, _names, _feeds):
            return [acts_out]

    monkeypatch.setattr(classify_mod, "HEADS", {"effnet": {"mood": "fake", "timbre": "fake"}})
    monkeypatch.setattr(
        classify_mod._binned_ptc_cache,
        "list_done_keys",
        lambda: {("s2", "effnet", "temporal_global", 1.0), ("s2", "effnet", "temporal_perdim", 1.0)},
    )
    ptc_dir = tmp_path / "ptc"
    ptc_dir.mkdir(parents=True, exist_ok=True)
    ptc_npz = ptc_dir / "s2.npz"
    np.savez(
        ptc_npz,
        bin_start_idx=np.array([0, 2], dtype=np.int32),
        bin_end_idx=np.array([1, 3], dtype=np.int32),
        weights=np.array([2, 2], dtype=np.int32),
    )
    monkeypatch.setattr(classify_mod._binned_ptc_cache, "cache_path", lambda *_args: ptc_npz)
    sidecar = tmp_path / "s2.effnet.npy"
    np.save(sidecar, acts_out)
    monkeypatch.setattr(classify_mod, "patches_path", lambda _sid, _bb: sidecar)
    monkeypatch.setattr(binned_ptc_heads_cache, "CACHE_BASE", tmp_path / "binned_ptc_heads")

    head_sessions = {"effnet": {"mood": _FakeSession(), "timbre": _FakeSession()}}
    first = classify_mod.run_shared_ptc_head_pooling(None, head_sessions=head_sessions, force=True)
    second = classify_mod.run_shared_ptc_head_pooling(None, head_sessions=head_sessions, force=True)

    assert first.to_json() == second.to_json()
    payload = json.loads(first.to_json())
    assert payload["finite"] is True
    assert payload["primary_analysis_succeeded"] is True
    assert payload["boundary_source"] == BOUNDARY_SOURCE_EFFNET_PTC


@pytest.mark.usefixtures("fake_ml_session_comp")
def test_shared_phase_cached_rerun_counts_pooled(monkeypatch, tmp_path) -> None:
    """A fully-cached re-run reports n_pooled==n_songs and done==0 (coverage from cache).

    Coverage accounting on the incremental path: songs whose head arrays are already
    cached and valid (provenance passes ``check_cache_valid``) must be counted as POOLED
    (n_pooled) even though nothing was freshly produced this run, so done==0 and the
    per-threshold coverage is accurate.
    """
    acts_out = np.array(
        [[0.1, 0.9], [0.3, 0.7], [0.5, 0.5], [0.8, 0.2]],
        dtype=np.float32,
    )  # [4 patches, 2 classes]

    class _FakeSession:
        def run(self, names, _feeds):
            assert names == ["activations"]
            return [acts_out]

    monkeypatch.setattr(classify_mod, "HEADS", {"effnet": {"mood": "fake"}})
    monkeypatch.setattr(
        classify_mod._binned_ptc_cache,
        "list_done_keys",
        lambda: {("s1", "effnet", "temporal_global", 1.0)},
    )
    ptc_dir = tmp_path / "ptc"
    ptc_dir.mkdir(parents=True, exist_ok=True)
    ptc_npz = ptc_dir / "s1.npz"
    np.savez(
        ptc_npz,
        bin_start_idx=np.array([0, 2], dtype=np.int32),
        bin_end_idx=np.array([1, 3], dtype=np.int32),
        weights=np.array([2, 2], dtype=np.int32),
    )
    monkeypatch.setattr(classify_mod._binned_ptc_cache, "cache_path", lambda *_args: ptc_npz)
    sidecar = tmp_path / "s1.effnet.npy"
    np.save(sidecar, acts_out)
    monkeypatch.setattr(classify_mod, "patches_path", lambda _sid, _bb: sidecar)
    monkeypatch.setattr(binned_ptc_heads_cache, "CACHE_BASE", tmp_path / "binned_ptc_heads")
    head_sessions = {"effnet": {"mood": _FakeSession()}}

    # First run populates the cache with provenance-valid entries.
    classify_mod.run_shared_ptc_head_pooling(None, head_sessions=head_sessions)

    # Re-run without force: everything is already cached and valid. Coverage must be
    # reported as fully pooled (n_pooled == n_songs) and done==0 since no config was
    # freshly produced this run.
    manifest = classify_mod.run_shared_ptc_head_pooling(None, head_sessions=head_sessions)

    assert manifest.done == 0
    assert len(manifest.results) == 1
    rec = manifest.results[0]
    assert rec.status == "skipped"
    assert rec.n_songs == 1 and rec.n_pooled == 1


@pytest.mark.usefixtures("fake_ml_session_comp")
def test_shared_phase_partial_cache_counts_cached_valid_heads_pooled(monkeypatch, tmp_path) -> None:
    """Mixed cache population: cached-valid heads count pooled, missing heads recompute.

    Regression for the partial-cache partition fix. Run 1 pools only ``mood`` (heads
    restricted to ``["mood"]``); run 2 adds ``timbre``. On run 2 ``mood`` is cached AND
    valid, so it MUST be counted as pooled (n_songs=1, n_pooled=1) and carry the
    ``"head arrays cached and valid"`` reason — it must NOT be silently skipped
    (status='skipped' reason='' n_songs=0 n_pooled=0) — while missing ``timbre`` goes
    to pending and is freshly pooled (done).
    """
    acts_out = np.array(
        [[0.1, 0.9], [0.3, 0.7], [0.5, 0.5], [0.8, 0.2]],
        dtype=np.float32,
    )  # [4 patches, 2 classes]

    class _FakeSession:
        def run(self, names, _feeds):
            assert names == ["activations"]
            return [acts_out]

    monkeypatch.setattr(classify_mod, "HEADS", {"effnet": {"mood": "fake", "timbre": "fake"}})
    monkeypatch.setattr(
        classify_mod._binned_ptc_cache,
        "list_done_keys",
        lambda: {("s1", "effnet", "temporal_global", 1.0)},
    )
    ptc_dir = tmp_path / "ptc"
    ptc_dir.mkdir(parents=True, exist_ok=True)
    ptc_npz = ptc_dir / "s1.npz"
    np.savez(
        ptc_npz,
        bin_start_idx=np.array([0, 2], dtype=np.int32),
        bin_end_idx=np.array([1, 3], dtype=np.int32),
        weights=np.array([2, 2], dtype=np.int32),
    )
    monkeypatch.setattr(classify_mod._binned_ptc_cache, "cache_path", lambda *_args: ptc_npz)
    sidecar = tmp_path / "s1.effnet.npy"
    np.save(sidecar, acts_out)
    monkeypatch.setattr(classify_mod, "patches_path", lambda _sid, _bb: sidecar)
    monkeypatch.setattr(binned_ptc_heads_cache, "CACHE_BASE", tmp_path / "binned_ptc_heads")

    # Run 1: only 'mood' participates, populating the mood head cache for s1.
    run_1_sessions = {"effnet": {"mood": _FakeSession()}}
    classify_mod.run_shared_ptc_head_pooling(None, head_sessions=run_1_sessions, heads=["mood"])

    # Run 2: both heads in scope. 'mood' cached+valid -> pooled; 'timbre' missing -> done.
    run_2_sessions = {"effnet": {"mood": _FakeSession(), "timbre": _FakeSession()}}
    manifest = classify_mod.run_shared_ptc_head_pooling(None, head_sessions=run_2_sessions)

    by_head = {r.head: r for r in manifest.results}
    assert set(by_head) == {"mood", "timbre"}

    mood = by_head["mood"]
    assert mood.status == "skipped"
    assert mood.reason == "head arrays cached and valid"
    assert mood.n_songs == 1 and mood.n_pooled == 1

    timbre = by_head["timbre"]
    assert timbre.status == "done"
    assert timbre.n_songs == 1 and timbre.n_pooled == 1


@pytest.mark.usefixtures("fake_ml_session_comp")
def test_shared_phase_legacy_ptc_cache_records_boundary_key_skip(monkeypatch, tmp_path) -> None:
    """Legacy PTC npz missing bin_start_idx/bin_end_idx records a distinct skip reason.

    Regression: a legacy-format PTC cache (no boundary keys) for a combo must record
    status='skipped' reason='PTC cache lacks boundary keys (legacy format)' and bump
    n_songs for that combo, instead of silently dropping it (status='skipped' reason=''
    n_songs=0 n_pooled=0). A sibling valid combo still pools normally.
    """
    acts_out = np.array(
        [[0.1, 0.9], [0.3, 0.7], [0.5, 0.5], [0.8, 0.2]],
        dtype=np.float32,
    )  # [4 patches, 2 classes]

    class _FakeSession:
        def run(self, names, _feeds):
            assert names == ["activations"]
            return [acts_out]

    monkeypatch.setattr(classify_mod, "HEADS", {"effnet": {"mood": "fake"}})
    monkeypatch.setattr(
        classify_mod._binned_ptc_cache,
        "list_done_keys",
        lambda: {
            ("s1", "effnet", "temporal_global", 1.0),
            ("s1", "effnet", "temporal_perdim", 1.0),
        },
    )
    ptc_dir = tmp_path / "ptc"
    ptc_dir.mkdir(parents=True, exist_ok=True)
    legacy_npz = ptc_dir / "legacy.npz"
    # Legacy format: only 'weights', no boundary keys.
    np.savez(legacy_npz, weights=np.array([2, 2], dtype=np.int32))
    valid_npz = ptc_dir / "valid.npz"
    np.savez(
        valid_npz,
        bin_start_idx=np.array([0, 2], dtype=np.int32),
        bin_end_idx=np.array([1, 3], dtype=np.int32),
        weights=np.array([2, 2], dtype=np.int32),
    )

    def _cache_path(_bb, bin_mode, _st, _sid):
        return legacy_npz if bin_mode == "temporal_global" else valid_npz

    monkeypatch.setattr(classify_mod._binned_ptc_cache, "cache_path", _cache_path)
    sidecar = tmp_path / "s1.effnet.npy"
    np.save(sidecar, acts_out)
    monkeypatch.setattr(classify_mod, "patches_path", lambda _sid, _bb: sidecar)
    monkeypatch.setattr(binned_ptc_heads_cache, "CACHE_BASE", tmp_path / "binned_ptc_heads")

    manifest = classify_mod.run_shared_ptc_head_pooling(None, head_sessions={"effnet": {"mood": _FakeSession()}})

    legacy = next(r for r in manifest.results if r.bin_mode == "temporal_global")
    assert legacy.status == "skipped"
    assert legacy.reason == "PTC cache lacks boundary keys (legacy format)"
    assert legacy.n_songs == 1 and legacy.n_pooled == 0
    # The sibling valid combo still pools normally.
    valid = next(r for r in manifest.results if r.bin_mode == "temporal_perdim")
    assert valid.status == "done"
    assert valid.n_songs == 1 and valid.n_pooled == 1


@pytest.mark.usefixtures("fake_ml_session_comp")
def test_cached_valid_plus_missing_plus_legacy_ptc_no_double_count(monkeypatch, tmp_path) -> None:
    """Cached-valid + missing head + legacy-format PTC npz in the same combo: no double-count.

    Regression: a single combo whose ``mood`` head is already cached-and-valid, whose
    ``timbre`` head is missing, and whose PTC npz is legacy-format (no ``bin_start_idx`` /
    ``bin_end_idx`` boundary keys) must account both heads EXACTLY once:

    * ``mood`` in cached-valid -> counted as pooled once (n_songs=1, n_pooled=1,
      reason "head arrays cached and valid"); it must NOT be double-counted later when
      the legacy-format skip bump fires (which is scoped to ONLY the missing heads).
    * ``timbre`` in missing -> cannot pool against legacy boundaries, so it is counted
      as NOT pooled (n_songs=1, n_pooled=0, reason "PTC cache lacks boundary keys
      (legacy format)") — it must NOT be falsely pooled.

    Both statuses are 'skipped' and done==0 (nothing freshly produced this run).
    """
    acts_out = np.array(
        [[0.1, 0.9], [0.3, 0.7], [0.5, 0.5], [0.8, 0.2]],
        dtype=np.float32,
    )  # [4 patches, 2 classes]

    class _FakeSession:
        def run(self, names, _feeds):
            assert names == ["activations"]
            return [acts_out]

    monkeypatch.setattr(classify_mod, "HEADS", {"effnet": {"mood": "fake", "timbre": "fake"}})
    monkeypatch.setattr(
        classify_mod._binned_ptc_cache,
        "list_done_keys",
        lambda: {("s1", "effnet", "temporal_global", 1.0)},
    )
    ptc_dir = tmp_path / "ptc"
    ptc_dir.mkdir(parents=True, exist_ok=True)
    # Same combo is legacy-format: no boundary keys, only 'weights'.
    legacy_npz = ptc_dir / "s1.npz"
    np.savez(legacy_npz, weights=np.array([2, 2], dtype=np.int32))
    monkeypatch.setattr(classify_mod._binned_ptc_cache, "cache_path", lambda *_args: legacy_npz)
    sidecar = tmp_path / "s1.effnet.npy"
    np.save(sidecar, acts_out)
    monkeypatch.setattr(classify_mod, "patches_path", lambda _sid, _bb: sidecar)
    monkeypatch.setattr(binned_ptc_heads_cache, "CACHE_BASE", tmp_path / "binned_ptc_heads")

    # Pre-seed a valid, provenance-clean cached entry for 'mood' (as a prior valid run
    # would have produced), while 'timbre' has no cache entry at all.
    binned_ptc_heads_cache.save(
        "effnet",
        "mood",
        "temporal_global",
        1.0,
        "s1",
        np.array([[0.2, 0.8], [0.65, 0.35]], dtype=np.float32),
        np.array([2, 2], dtype=np.int32),
        bin_start_idx=np.array([0, 2], dtype=np.int32),
        bin_end_idx=np.array([1, 3], dtype=np.int32),
        boundary_source=BOUNDARY_SOURCE_EFFNET_PTC,
        scoring_semantics_version=SCORING_SEMANTICS_VERSION,
        finite=True,
    )

    manifest = classify_mod.run_shared_ptc_head_pooling(
        None, head_sessions={"effnet": {"mood": _FakeSession(), "timbre": _FakeSession()}}
    )

    by_head = {r.head: r for r in manifest.results}
    assert set(by_head) == {"mood", "timbre"}

    # cached-valid head counted pooled EXACTLY once (not double-counted by the legacy bump).
    mood = by_head["mood"]
    assert mood.status == "skipped"
    assert mood.reason == "head arrays cached and valid"
    assert mood.n_songs == 1 and mood.n_pooled == 1

    # missing head against legacy boundaries is NOT falsely pooled; counted once, n_pooled=0.
    timbre = by_head["timbre"]
    assert timbre.status == "skipped"
    assert timbre.reason == "PTC cache lacks boundary keys (legacy format)"
    assert timbre.n_songs == 1 and timbre.n_pooled == 0

    # Nothing was freshly pooled; the run reports no 'done' configs.
    assert manifest.done == 0
