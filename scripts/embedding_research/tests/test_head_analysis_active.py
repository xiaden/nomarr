"""Spec-first tests for the ACTIVE canonical head-analysis surface (Plan E, P1-S4).

Covers ``common.head_analysis`` — the canonical exact-membership pooling helper,
the per-(config, head) outcome record, and the CPU-only runner
``run_shared_ptc_head_pooling``:

* exact-membership means (never inclusive ``[start, end]`` ranges; the only rows
  averaged are the gathered ``seg_membership`` member rows);
* absorbed-outlier rows are members whose ``weight == member_count``;
* mutating ``seg_meta.start_idx/end_idx`` does NOT change the pooled values
  (the runner reads only ``seg_membership``);
* invalid index / flag / weight cases are rejected;
* class-1 is taken from ``act[1]`` (never ``act[0]``);
* CPU-boundary sentinels: the active helper and runner never reference
  ONNX/audio/CUDA/segmentation/CTP, and the LEGACY ``classify`` runner never
  invokes the canonical persistence surface.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

import scripts.embedding_research.classify as classify_mod
from scripts.embedding_research.common.head_analysis import (
    BOUNDARY_SOURCE_EFFNET_PTC,
    HEAD_POOL_VARIANT,
    HeadBoundaryPoolResult,
    pool_head_outputs_over_ptc_boundaries,
    run_shared_ptc_head_pooling,
)
from scripts.embedding_research.helpers.thresholds import PTC_STRATEGY_VERSION

_RESEARCH_DIR = Path(__file__).resolve().parents[1]

_CLASS1 = 1


def _gather_rows(acts: np.ndarray, indices):
    return np.asarray(acts, dtype=np.float32)[list(indices)]


# ---------------------------------------------------------------------------
# exact-membership value object
# ---------------------------------------------------------------------------


def test_exact_membership_mean_excludes_nonmembers() -> None:
    """Only the gathered exact member rows are pooled (never a [start:end] range).

    Patch 0 is present in the song but NOT a member of this segment; the pooled
    value must not include it — i.e. this is an exact-membership mean, not an
    inclusive range mean over ``seg_meta.start_idx..end_idx``.
    """
    full = np.array([[0.0, 1.0, 2.0], [3.0, 4.0, 5.0], [6.0, 7.0, 8.0], [9.0, 10.0, 11.0]], dtype=np.float32)
    member_patch_indices = (1, 3)  # patch 0 deliberately excluded
    acts = _gather_rows(full, member_patch_indices)
    result = pool_head_outputs_over_ptc_boundaries(
        acts, member_patch_indices, segment_id=2, weight=2, is_absorbed_outlier=(False, False)
    )
    assert isinstance(result, HeadBoundaryPoolResult)
    # mean of rows 1 and 3 only — row 0 (which a range [0:3] would include) is absent.
    np.testing.assert_allclose(result.acts, acts.mean(axis=0).astype(np.float32), rtol=1e-6)
    np.testing.assert_allclose(result.acts, np.array([6.0, 7.0, 8.0]), rtol=1e-6)
    assert result.weight == 2
    assert result.member_patch_indices == member_patch_indices
    assert result.segment_id == 2
    assert result.finite is True
    # Neither the helper nor the result ever exposes start_idx/end_idx.
    assert not hasattr(result, "start_idx") and not hasattr(result, "end_idx")


def test_absorbed_outlier_is_a_member_with_weight_equal_member_count() -> None:
    """Absorbed-outlier rows are members; weight equals member_count (incl. them)."""
    acts = np.array([[0.0, 1.0, 2.0], [3.0, 4.0, 5.0], [6.0, 7.0, 8.0]], dtype=np.float32)
    result = pool_head_outputs_over_ptc_boundaries(
        acts,
        (4, 9, 12),
        segment_id=1,
        weight=3,  # member_count == 3, absorbed outlier included
        is_absorbed_outlier=(False, True, False),
    )
    assert result.weight == 3
    assert result.is_absorbed_outlier == (False, True, False)
    np.testing.assert_allclose(result.acts, acts.mean(axis=0).astype(np.float32), rtol=1e-6)


def test_class1_is_act1_never_act0() -> None:
    acts = np.array([[0.9, 0.05], [0.8, 0.2], [0.7, 0.35]], dtype=np.float32)
    result = pool_head_outputs_over_ptc_boundaries(
        acts, (1, 2, 3), segment_id=0, weight=3, is_absorbed_outlier=(False, False, False)
    )
    # act[1] column mean = (0.05+0.2+0.35)/3 = 0.2 ; act[0] mean = 0.8 — never selected.
    assert result.class1 == pytest.approx(0.2)
    assert result.acts[_CLASS1] == pytest.approx(0.2)


def test_value_object_to_json_roundtrip_and_fixed_source() -> None:
    acts = np.array([[1.0, 2.0, 3.0], [2.0, 3.0, 4.0]], dtype=np.float32)
    result = pool_head_outputs_over_ptc_boundaries(
        acts, (0, 5), segment_id=3, weight=2, is_absorbed_outlier=(True, False)
    )
    assert result.boundary_source == BOUNDARY_SOURCE_EFFNET_PTC
    import json

    d = json.loads(result.to_json())
    assert d["boundary_source"] == BOUNDARY_SOURCE_EFFNET_PTC
    assert d["segment_id"] == 3 and d["weight"] == 2
    assert d["is_absorbed_outlier"] == [True, False]
    # class-1 survives the JSON round trip (act[1] mean = (2+3)/2).
    assert d["class1"] == pytest.approx((2.0 + 3.0) / 2)


def test_nonmembership_boundary_source_rejected() -> None:
    with pytest.raises(ValueError, match="CTP never used"):
        HeadBoundaryPoolResult(
            acts=np.array([0.5, 0.5, 0.5], dtype=np.float32),
            class1=0.5,
            weight=1,
            member_patch_indices=(0,),
            is_absorbed_outlier=(False,),
            segment_id=0,
            finite=True,
            boundary_source="ctp",
        )


# ---------------------------------------------------------------------------
# invalid index / flag / weight cases
# ---------------------------------------------------------------------------


def test_invalid_member_index_cases_rejected() -> None:
    acts = np.array([[1.0, 2.0, 3.0], [2.0, 3.0, 4.0]], dtype=np.float32)
    flags = (False, False)
    # negative source index.
    with pytest.raises(ValueError, match="non-negative"):
        pool_head_outputs_over_ptc_boundaries(acts, (-1, 2), segment_id=0, weight=2, is_absorbed_outlier=flags)
    # duplicate source index (a member listed twice).
    with pytest.raises(ValueError, match="unique"):
        pool_head_outputs_over_ptc_boundaries(acts, (2, 2), segment_id=0, weight=2, is_absorbed_outlier=flags)
    # indices not co-indexed with the gathered rows (count mismatch).
    with pytest.raises(ValueError, match="co-indexed"):
        pool_head_outputs_over_ptc_boundaries(acts, (0,), segment_id=0, weight=1, is_absorbed_outlier=flags)
    # empty membership.
    with pytest.raises(ValueError, match="at least one"):
        pool_head_outputs_over_ptc_boundaries(
            np.empty((0, 3), np.float32), (), segment_id=0, weight=0, is_absorbed_outlier=()
        )


def test_invalid_flag_cases_rejected() -> None:
    acts = np.array([[1.0, 2.0, 3.0], [2.0, 3.0, 4.0]], dtype=np.float32)
    # flag list length mismatch.
    with pytest.raises(ValueError, match="co-indexed"):
        pool_head_outputs_over_ptc_boundaries(acts, (0, 1), segment_id=0, weight=2, is_absorbed_outlier=(False,))
    # non-bool flag.
    with pytest.raises(ValueError, match="bool"):
        HeadBoundaryPoolResult(
            acts=np.array([0.1, 0.1, 0.1], dtype=np.float32),
            class1=0.1,
            weight=1,
            member_patch_indices=(0,),
            is_absorbed_outlier=(1,),
            segment_id=0,
            finite=True,
        )


def test_invalid_weight_cases_rejected() -> None:
    acts = np.array([[1.0, 2.0, 3.0], [2.0, 3.0, 4.0]], dtype=np.float32)
    flags = (False, False)
    # weight != member_count (absorbed outliers are members, so weight must equal N).
    with pytest.raises(ValueError, match="must equal the number of exact member rows"):
        pool_head_outputs_over_ptc_boundaries(acts, (0, 1), segment_id=0, weight=3, is_absorbed_outlier=flags)
    # zero weight.
    with pytest.raises(ValueError, match="must equal"):
        pool_head_outputs_over_ptc_boundaries(acts, (0, 1), segment_id=0, weight=0, is_absorbed_outlier=flags)
    # negative weight.
    with pytest.raises(ValueError, match="must equal"):
        pool_head_outputs_over_ptc_boundaries(acts, (0, 1), segment_id=0, weight=-1, is_absorbed_outlier=flags)
    # bool is not an integer weight.
    with pytest.raises(ValueError, match="must equal"):
        pool_head_outputs_over_ptc_boundaries(acts, (0, 1), segment_id=0, weight=True, is_absorbed_outlier=flags)


def test_nonfinite_or_wrong_rank_acts_rejected() -> None:
    with pytest.raises(ValueError, match="finite"):
        pool_head_outputs_over_ptc_boundaries(
            np.array([[np.nan, 1.0, 2.0]], np.float32), (0,), segment_id=0, weight=1, is_absorbed_outlier=(False,)
        )
    with pytest.raises(ValueError, match="2-D"):
        pool_head_outputs_over_ptc_boundaries(
            np.array([1.0, 2.0, 3.0], np.float32),
            (0, 1, 2),
            segment_id=0,
            weight=3,
            is_absorbed_outlier=(False, False, False),
        )


# ---------------------------------------------------------------------------
# canonical runner: start_idx/end_idx mutation does not change pooled values
# ---------------------------------------------------------------------------


class _FakeHeadStore:
    """Minimal stand-in: a ready single-head stream whose gathered rows are the
    source patch ids themselves (row value == its source patch index)."""

    def __init__(self, rows_by_patch):
        self._rows_by_patch = rows_by_patch

    def lookup(self, song_id, backbone):  # noqa: ARG002 - interface-parity fake
        import types

        return types.SimpleNamespace(head_ids="mood", dim_by_head="mood=3")

    def batch_gather(self, song_id, backbone, source_patch_indices):  # noqa: ARG002 - interface-parity fake
        return np.asarray(
            [[float(i), float(i) + 1.0, float(i) + 2.0] for i in source_patch_indices],
            dtype=np.float32,
        )


def _seed_catalog(con):
    con.execute(
        "INSERT INTO seg_config (config_id, backbone, bin_mode, threshold_configured, "
        "threshold_effective, semantics, calibration_record, outlier_window, strategy_version, "
        "alias_of_config_id, canonical_config_hash, created_at, run_id) VALUES "
        "(7, 'effnet', 'temporal_global', 1.0, 1.0, 'direct_l2', '{}', 0, ?, NULL, 'ch', 0, 'seed')",
        [PTC_STRATEGY_VERSION],
    )


def _seed_song(con, *, start_idx, end_idx):
    con.execute("DELETE FROM seg_membership WHERE config_id=7 AND song_id='s1'")
    con.execute("DELETE FROM seg_meta WHERE config_id=7 AND song_id='s1'")
    # seg 0: members (0, 2, 5) with patch 2 absorbed; seg 1: member (8).
    con.execute(
        "INSERT INTO seg_meta (config_id, song_id, seg_id, start_idx, end_idx, member_count, "
        "absorbed_outlier_count, weight, medoid_source_patch_idx, segment_signature, created_at) "
        "VALUES (7, 's1', 0, ?, ?, 3, 1, 3, 2, 'sig0', 0)",
        [start_idx[0], end_idx[0]],
    )
    con.execute(
        "INSERT INTO seg_meta (config_id, song_id, seg_id, start_idx, end_idx, member_count, "
        "absorbed_outlier_count, weight, medoid_source_patch_idx, segment_signature, created_at) "
        "VALUES (7, 's1', 1, ?, ?, 1, 0, 1, 8, 'sig1', 0)",
        [start_idx[1], end_idx[1]],
    )
    con.executemany(
        "INSERT INTO seg_membership (config_id, song_id, seg_id, member_patch_idx, "
        "is_absorbed_outlier, membership_version) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (7, "s1", 0, 0, False, 1),
            (7, "s1", 0, 2, True, 1),
            (7, "s1", 0, 5, False, 1),
            (7, "s1", 1, 8, False, 1),
        ],
    )


def test_runner_pooled_values_unchanged_when_start_end_mutated(con):
    """P1-S2: only ``seg_membership`` drives pooling; start_idx/end_idx are inert."""

    # seg_meta rows for the two (config, song) states differ only in structural ranges.
    _seed_catalog(con)
    _seed_song(con, start_idx=(0, 3), end_idx=(2, 3))
    store = _FakeHeadStore(None)
    first = run_shared_ptc_head_pooling(con, store, song_ids=["s1"], run_id="r1", reference_corpus_hash="h")
    assert first.done == 1 and first.skipped == 0 and first.errors == 0
    assert first.config_ids == (7,)
    assert first.heads == ("mood",)
    assert first.song_ids == ("s1",)
    r0 = first.results[0]
    assert r0.status == "done" and r0.n_songs == 1 and r0.n_pooled == 1
    assert r0.config_id == 7
    assert r0.head_pool_variant == HEAD_POOL_VARIANT

    # Mutate structural ranges to wildly different values (membership unchanged).
    _seed_song(con, start_idx=(99, 100), end_idx=(101, 1000))
    second = run_shared_ptc_head_pooling(con, store, song_ids=["s1"], run_id="r2", reference_corpus_hash="h")
    assert second.config_ids == first.config_ids
    assert second.heads == first.heads
    assert second.dimensions == first.dimensions
    # The pooled (config, head) outcome is byte-for-byte identical.
    assert second.results == first.results
    assert [r.n_pooled for r in second.results] == [r.n_pooled for r in first.results]
    assert second.done == 1 and second.finite is True


def test_runner_skips_ineligible_config_and_unknown_config(con):
    """Non-effnet/aliased/non-PTC configs are deterministic skips; unknown id too."""
    _seed_catalog(con)
    _seed_song(con, start_idx=(0, 3), end_idx=(2, 3))  # config 7 has a ready song
    # An alias-of + non-PTC semantics config must be skipped as ineligible.
    con.execute(
        "INSERT INTO seg_config (config_id, backbone, bin_mode, threshold_configured, "
        "threshold_effective, semantics, calibration_record, outlier_window, strategy_version, "
        "alias_of_config_id, canonical_config_hash, created_at, run_id) VALUES "
        "(8, 'effnet', 'temporal_half', 1.0, 1.0, 'direct_l2', '{}', 0, ?, NULL, 'ch', 0, 'seed')",
        [PTC_STRATEGY_VERSION],
    )
    store = _FakeHeadStore(None)
    manifest = run_shared_ptc_head_pooling(con, store, config_ids=[7, 8, 999], song_ids=["s1"], run_id="r")
    assert manifest.config_ids == (7,)
    reasons = dict(manifest.skip_reasons)
    assert any(k == "config:999" for k in reasons)
    assert any(k == "config:8" for k in reasons)
    assert all(r.config_id == 7 for r in manifest.results)


# ---------------------------------------------------------------------------
# CPU-boundary sentinels
# ---------------------------------------------------------------------------

_FORBIDDEN = (
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
)


def _function_body_code_names(path: Path, name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            names: set[str] = set()
            for child in ast.walk(node):
                if isinstance(child, ast.Name):
                    names.add(child.id)
                elif isinstance(child, ast.Attribute):
                    names.add(child.attr)
            return names
    raise AssertionError(f"function {name!r} not found in {path}")


def test_active_pooling_helper_is_cpu_boundary_pure() -> None:
    names = _function_body_code_names(
        _RESEARCH_DIR / "common" / "head_analysis.py", "pool_head_outputs_over_ptc_boundaries"
    )
    for token in _FORBIDDEN:
        assert token not in names, f"active helper must not reference {token!r}"


def test_active_runner_is_cpu_boundary_no_persistence_no_forbidden_calls() -> None:
    names = _function_body_code_names(_RESEARCH_DIR / "common" / "head_analysis.py", "run_shared_ptc_head_pooling")
    for token in _FORBIDDEN:
        assert token not in names, f"active runner must not reference {token!r}"


def test_legacy_classify_runner_never_invokes_canonical_persistence() -> None:
    """The LEGACY classify runner is cache/manifest-only (D1) — no persistence names."""
    source = Path(classify_mod.__file__).read_text(encoding="utf-8")
    assert "write_head_phase_provenance" not in source
    assert "append_head_phase_archival_rows" not in source
    # Never imports the head-phase persistence module (canonical or archival writer).
    assert "db.head_phase" not in source
    assert "head_phase_db" not in source
    # Never routes through the ACTIVE canonical runner module.
    assert "common.head_analysis" not in source
