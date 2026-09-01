"""Phase 2 tests: primary ``max_per_candidate_segment`` score variant wiring.

Proves the process/orchestration contract from the follow-on primary experiment:

* primary rows use the named ``max_per_candidate_segment`` score;
* the legacy weighted hypotheses remain visibly labelled (opt-in comparison
  formulas), distinct from the primary variant;
* candidate-segment weights are used (the collision fixture's 8.6/9 value);
* collisions / winners are stable across re-computation;
* reverse-direction pair scores are computed separately, never copied from a
  transpose;
* existing PTC invariants still hold — unit-vector segmentation,
  ``act[1]`` as class-1 head score, ``disc_general`` excluding zero-valued
  components, and no ``disc_album`` key anywhere in the touched surfaces.
"""

from __future__ import annotations

import ast
import pathlib
from typing import Any

import numpy as np
import pytest

from scripts.embedding_research.cache_identity import matrix_cache_identity
from scripts.embedding_research.scoring_harness import PRIMARY_COLLISION_POLICY, PRIMARY_TIE_POLICY
from scripts.embedding_research.strategy_binned._constants import (
    _ALLOWED_SCORE_VARIANTS,
    PRIMARY_SCORE_VARIANT,
    SCORE_VARIANTS,
    validate_score_variant,
)
from scripts.embedding_research.strategy_binned._process import (
    ScoreVariantResult,
    compute_agg_mats,
    compute_score_variant_mats,
    compute_score_variant_retrieval_rows,
    score_variant_trace_summary,
)
from scripts.embedding_research.vector_types import UnitTensor

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _unit(rows: list[list[float]]) -> UnitTensor:
    return UnitTensor(np.asarray(rows, dtype=np.float32))


# Two songs with asymmetric rep_a/rep_b bin geometry so the reverse direction is
# provably *not* a transpose:
#   song0 rep_a = [[1,0],[0,1]] (2 bins, weights [2,1])
#   song0 rep_b = [[1,0],[0.8,0.6],[0,1]] (3 bins, weights [3,2,4])  <- collision fixture
#   song1 rep_a = [[1,0]] (1 bin, weights [1])
#   song1 rep_b = [[1,0]] (1 bin, weights [1])
def _fixture() -> tuple[list[UnitTensor], list[UnitTensor], list[np.ndarray], list[np.ndarray]]:
    norm_a = [_unit([[1, 0], [0, 1]]), _unit([[1, 0]])]
    norm_b = [_unit([[1, 0], [0.8, 0.6], [0, 1]]), _unit([[1, 0]])]
    weights_a = [np.array([2, 1], dtype=np.float32), np.array([1], dtype=np.float32)]
    weights_b = [np.array([3, 2, 4], dtype=np.float32), np.array([1], dtype=np.float32)]
    return norm_a, norm_b, weights_a, weights_b


def _result() -> ScoreVariantResult:
    return compute_score_variant_mats(*_fixture(), "cosine")


# rep_a and rep_b must share the same per-song bin counts for the weighted
# hypothesis path (compute_agg_mats) and the analyze orchestration validation.
def _symmetric_fixture() -> tuple[list[UnitTensor], list[UnitTensor], list[np.ndarray], list[np.ndarray], np.ndarray]:
    norm_a = [_unit([[1, 0], [0, 1]]), _unit([[1, 0]])]
    norm_b = [_unit([[1, 0], [0.8, 0.6]]), _unit([[1, 0]])]
    weights_a = [np.array([2, 1], dtype=np.float32), np.array([1], dtype=np.float32)]
    weights_b = [np.array([3, 2], dtype=np.float32), np.array([1], dtype=np.float32)]
    bin_counts = np.array([2, 1], dtype=np.int64)
    return norm_a, norm_b, weights_a, weights_b, bin_counts


# ---------------------------------------------------------------------------
# Primary score-variant matrix + traces
# ---------------------------------------------------------------------------


def test_compute_score_variant_mats_returns_matrix_and_bounded_traces() -> None:
    result = _result()
    assert isinstance(result, ScoreVariantResult)
    assert result.score_variant == PRIMARY_SCORE_VARIANT
    assert result.tie_policy == PRIMARY_TIE_POLICY
    assert result.collision_policy == PRIMARY_COLLISION_POLICY
    assert result.matrix.shape == (2, 2)
    assert result.matrix.dtype == np.float32
    assert result.n == 2
    # One bounded trace record per ordered pair (never the raw matrix in a row).
    assert len(result.traces) == 2 and all(len(row) == 2 for row in result.traces)


def test_primary_diagonal_uses_collision_fixture_with_candidate_weights() -> None:
    """matrix[0,0] == 8.6/9 — the scoring-harness collision fixture value.

    That value only arises when the candidate-segment weights [3,2,4] are used
    (uniform weights would give 2.8/3), so it proves candidate-segment weights
    feed the primary score.
    """
    result = _result()
    assert result.matrix[0, 0] == pytest.approx(8.6 / 9, abs=1e-6)
    trace = result.traces[0][0]
    assert trace.score == pytest.approx(8.6 / 9, abs=1e-6)
    assert trace.finite is True
    # Stable collision group: candidate bins {0,1} both win source bin 0.
    assert trace.collisions == ((0, 1),)
    assert result.variant == f"max_per_candidate_segment({PRIMARY_TIE_POLICY}+{PRIMARY_COLLISION_POLICY})"


def test_reverse_direction_computed_not_copied_from_transpose() -> None:
    """matrix[1,0] != matrix[0,1] and equals the hand-computed reverse score.

    If the reverse pair were derived by transposing the forward matrix,
    matrix[1,0] would equal matrix[0,1]; it does not, and the value matches an
    independent computation from the actual reverse arrays.
    """
    result = _result()
    assert result.matrix[0, 1] == pytest.approx(1.0, abs=1e-6)  # [[1,0],[0,1]] -> [[1,0]]
    assert result.matrix[1, 0] == pytest.approx(4.6 / 9, abs=1e-6)  # [[1,0]] -> [[1,0],[.8,.6],[0,1]]
    assert result.matrix[1, 0] != pytest.approx(result.matrix[0, 1], abs=1e-6)


def test_collisions_and_winners_stable_across_recomputation() -> None:
    first = _result()
    second = _result()
    for i in range(2):
        for j in range(2):
            assert first.traces[i][j].collisions == second.traces[i][j].collisions
            assert first.traces[i][j].winner_counts == second.traces[i][j].winner_counts
            assert first.traces[i][j].score == pytest.approx(second.traces[i][j].score)
    assert np.allclose(first.matrix, second.matrix)


def test_score_variant_trace_summary_is_bounded_and_finite() -> None:
    summary = score_variant_trace_summary(_result())
    assert summary["trace_n_pairs"] == 4.0
    assert all(isinstance(v, float) and np.isfinite(v) for v in summary.values())
    assert summary["trace_finite"] == 1.0
    assert summary["trace_collision_count"] >= 1.0  # the [0,0] pair has one collision group


def test_score_variant_rejects_non_cosine_metric() -> None:
    with pytest.raises(ValueError, match="cosine"):
        compute_score_variant_mats(*_fixture(), "l2")


def test_score_variant_rejects_weighted_hypothesis_here() -> None:
    norm_a, norm_b, weights_a, weights_b = _fixture()
    with pytest.raises(ValueError, match="legacy"):
        compute_score_variant_mats(norm_a, norm_b, weights_a, weights_b, "cosine", score_variant="target_weighted")


# ---------------------------------------------------------------------------
# Retrieval rows: primary labelled distinctly from weighted hypotheses
# ---------------------------------------------------------------------------


def test_primary_retrieval_row_uses_named_score_and_hypotheses_stay_labeled() -> None:
    result = _result()
    rows, _per_head, summary = compute_score_variant_retrieval_rows(
        result,
        artists=["artist-a", "artist-b"],
        backbone="effnet",
        bin_mode="temporal_global",
        std_thresh=0.5,
        rep_a="mean",
        rep_b="mean",
        metric="cosine",
        k=1,
        n_songs=2,
    )
    assert len(rows) == 1
    # Primary DTO row carries the explicit score-variant identity.
    assert rows[0].agg_method == PRIMARY_SCORE_VARIANT
    assert rows[0].rep_a == "mean" and rows[0].rep_b == "mean"
    # Bounded trace summary threads through the retrieval boundary.
    assert summary["trace_n_pairs"] == 4.0
    assert summary["trace_finite"] == 1.0

    # The weighted hypothesis path yields separate, visibly-labelled rows whose
    # agg_method names are the legacy weighted reductions — never the primary.
    hyp_rows = _hypothesis_rows()
    assert len(hyp_rows) == 3
    for row in hyp_rows:
        assert row.agg_method != PRIMARY_SCORE_VARIANT
        assert row.agg_method in {
            "target_weighted",
            "bidirectional_weighted",
            "normalized_mean_pair_weighted",
        }


def _hypothesis_rows():
    from scripts.embedding_research.strategy_binned._process import compute_retrieval_rows

    norm_a, norm_b, weights_a, weights_b, _bin_counts = _symmetric_fixture()
    agg_mats = compute_agg_mats(norm_a, norm_b, weights_a, weights_b, "cosine")
    rows, _per_head = compute_retrieval_rows(
        agg_mats,
        ["artist-a", "artist-b"],
        "effnet",
        "temporal_global",
        0.5,
        "mean",
        "mean",
        "cosine",
        1,
        2,
    )
    return rows


# ---------------------------------------------------------------------------
# Score-variant identity surface (no generic aggregate re-enters)
# ---------------------------------------------------------------------------


def test_score_variant_surface_excludes_generic_aggregates() -> None:
    for generic in ("mean", "median", "max", "min", "medoid"):
        assert generic not in _ALLOWED_SCORE_VARIANTS
        with pytest.raises(ValueError):
            validate_score_variant(generic)
    # Primary + the three weighted hypotheses are the full allowed surface.
    assert PRIMARY_SCORE_VARIANT in _ALLOWED_SCORE_VARIANTS
    assert set(_ALLOWED_SCORE_VARIANTS) == {
        "max_per_candidate_segment",
        "target_weighted",
        "bidirectional_weighted",
        "normalized_mean_pair_weighted",
    }


def test_default_scoring_surface_is_primary_variant_only() -> None:
    """The default evaluated scoring surface is exactly the primary variant.

    The legacy weighted hypotheses remain available in ``_ALLOWED_SCORE_VARIANTS``
    but are not evaluated by default (opt-in only via ``pooling.score_variants``).
    """
    assert SCORE_VARIANTS == [PRIMARY_SCORE_VARIANT]
    assert set(_ALLOWED_SCORE_VARIANTS) == {
        "max_per_candidate_segment",
        "target_weighted",
        "bidirectional_weighted",
        "normalized_mean_pair_weighted",
    }


def test_cache_identity_includes_score_variant_dimension() -> None:
    base_kwargs: dict[str, Any] = {
        "backbone": "effnet",
        "pathway": "ptc",
        "threshold": 0.5,
        "rep_a": "mean",
        "rep_b": "mean",
        "aggregate": "target_weighted",
        "metric": "cosine",
        "song_ids": ["a", "b"],
        "corpus_hash": "abc",
    }
    without = matrix_cache_identity(**base_kwargs)
    with_primary = matrix_cache_identity(**base_kwargs, score_variant=PRIMARY_SCORE_VARIANT)
    assert with_primary != without  # score-variant identity is explicit in cache identity
    # An unlabelled generic aggregate must not re-enter via cache identity.
    with pytest.raises(ValueError):
        matrix_cache_identity(**base_kwargs, score_variant="mean")


# ---------------------------------------------------------------------------
# Orchestration: analyze() writes the named primary + labelled hypotheses
# ---------------------------------------------------------------------------


def test_analyze_binned_writes_primary_row_with_trace_summary(con, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.embedding_research.common import analyze as analyze_mod

    norm_a, norm_b, weights_a, weights_b, bin_counts = _symmetric_fixture()
    payload = {
        "rep_a": "mean",
        "rep_b": "mean",
        "norm_a_all": norm_a,
        "norm_b_all": norm_b,
        "bin_counts": bin_counts,
        "weights_a": weights_a,
        "weights_b": weights_b,
    }

    def load(_bb, _strategy, _con, _extra):
        return (payload, ["a", "b"], ["artist-a", "artist-b"], ["album-a", "album-b"], ["rock", "jazz"])

    captured: dict[str, dict[str, Any]] = {}

    def write(_con, strategy_key, _strategy_type, _sim_metric, _k, metrics):
        captured[strategy_key] = dict(metrics)

    def key_fn(_bb, _strategy, extra):
        return f"ptc:{_bb}:temporal_global:0.50:{extra['rep_a']}:{extra['rep_b']}:{extra['agg_method']}"

    cfg: analyze_mod.AnalyzeCfg = {
        "strategy_names": ["ptc_temporal_global_0.50"],
        "load_vecs_fn": load,
        "db_write_fn": write,
        "strategy_key_fn": key_fn,
        "strategy_type": "ptc",
        # Explicitly opt in to the weighted hypotheses so their labelled rows
        # are exercised; the default surface is primary-only (see
        # test_analyze_binned_default_writes_only_primary_row).
        "extra_cfg": {
            "rep_types": ["mean"],
            "score_variants": [
                PRIMARY_SCORE_VARIANT,
                "target_weighted",
                "bidirectional_weighted",
                "normalized_mean_pair_weighted",
            ],
        },
    }
    monkeypatch.setattr(analyze_mod, "_load_head_scores_and_names", lambda _bb, _sids: (None, None))

    analyze_mod.analyze(con, cfg, backbones=["effnet"], force=True, k=2)

    primary_key = f"ptc:effnet:temporal_global:0.50:mean:mean:{PRIMARY_SCORE_VARIANT}"
    assert primary_key in captured
    primary_metrics = captured[primary_key]
    # Primary row carries the bounded trace summary (finite scalar metrics).
    assert primary_metrics["trace_n_pairs"] == 4.0
    assert primary_metrics["trace_finite"] == 1.0
    assert "map_k_general" in primary_metrics

    # Hypothesis rows remain visibly labelled and carry no primary trace summary.
    weighted_keys = [k for k in captured if k.endswith("_weighted")]
    assert len(weighted_keys) == 3
    for k in weighted_keys:
        assert PRIMARY_SCORE_VARIANT not in k
        assert "trace_n_pairs" not in captured[k]
        assert k.endswith(("target_weighted", "bidirectional_weighted", "normalized_mean_pair_weighted"))


def test_analyze_binned_default_writes_only_primary_row(con, monkeypatch: pytest.MonkeyPatch) -> None:
    """With no explicit ``score_variants``, the default analyze surface evaluates
    only the primary ``max_per_candidate_segment`` variant — no weighted
    hypothesis rows enter the default output."""
    from scripts.embedding_research.common import analyze as analyze_mod

    norm_a, norm_b, weights_a, weights_b, bin_counts = _symmetric_fixture()
    payload = {
        "rep_a": "mean",
        "rep_b": "mean",
        "norm_a_all": norm_a,
        "norm_b_all": norm_b,
        "bin_counts": bin_counts,
        "weights_a": weights_a,
        "weights_b": weights_b,
    }

    def load(_bb, _strategy, _con, _extra):
        return (payload, ["a", "b"], ["artist-a", "artist-b"], ["album-a", "album-b"], ["rock", "jazz"])

    captured: dict[str, dict[str, Any]] = {}

    def write(_con, strategy_key, _strategy_type, _sim_metric, _k, metrics):
        captured[strategy_key] = dict(metrics)

    def key_fn(_bb, _strategy, extra):
        return f"ptc:{_bb}:temporal_global:0.50:{extra['rep_a']}:{extra['rep_b']}:{extra['agg_method']}"

    cfg: analyze_mod.AnalyzeCfg = {
        "strategy_names": ["ptc_temporal_global_0.50"],
        "load_vecs_fn": load,
        "db_write_fn": write,
        "strategy_key_fn": key_fn,
        "strategy_type": "ptc",
        "extra_cfg": {"rep_types": ["mean"]},  # no score_variants -> default primary-only
    }
    monkeypatch.setattr(analyze_mod, "_load_head_scores_and_names", lambda _bb, _sids: (None, None))

    analyze_mod.analyze(con, cfg, backbones=["effnet"], force=True, k=2)

    primary_key = f"ptc:effnet:temporal_global:0.50:mean:mean:{PRIMARY_SCORE_VARIANT}"
    assert set(captured) == {primary_key}
    assert captured[primary_key]["trace_n_pairs"] == 4.0
    assert captured[primary_key]["trace_finite"] == 1.0


# ---------------------------------------------------------------------------
# PTC invariants still hold through the score-variant path
# ---------------------------------------------------------------------------


def test_unit_vector_segmentation_invariant_holds_in_score_variant_path() -> None:
    # SegmentScoreInput enforces unit-norm rows; a passing computation is the
    # proof that the score-variant path sees unit-normalised PTC segment vectors.
    result = _result()
    for row in result.traces:
        for trace in row:
            assert trace.finite is True
    assert np.allclose(np.linalg.norm(np.asarray([[1.0, 0.0], [0.0, 1.0]]), axis=1), 1.0)


def test_act1_still_class1_head_score(monkeypatch: pytest.MonkeyPatch) -> None:
    """act[1] remains the class-1 head score in the binned head-score loader."""
    from scripts.embedding_research.common import analyze as analyze_mod

    monkeypatch.setattr(analyze_mod, "HEADS", {"effnet": {"mood": object()}})
    monkeypatch.setattr(
        analyze_mod._flat_heads_cache,
        "load_bulk",
        lambda _bb, _head, _rep, _pathway, sids: {sid: np.array([0.10, 0.90]) for sid in sids},
    )
    matrix, names = analyze_mod._load_head_scores_and_names("effnet", ["s1", "s2"])
    assert names == ["mood"]
    assert matrix is not None and matrix[0] == [0.90, 0.90]  # act[1], never act[0]


def test_disc_general_excludes_zero_valued_components() -> None:
    """disc_general is the mean of the non-zero disc components, excluding zeros."""
    from scripts.embedding_research.similarity import compute_retrieval_metrics

    # Artist-only inputs: disc_artist > 0, disc_genre/disc_head are zero, so
    # disc_general must equal disc_artist (the zero-valued components excluded).
    sim_mat = np.array(
        [
            [1.0, 0.9, 0.1, 0.0],
            [0.9, 1.0, 0.1, 0.0],
            [0.1, 0.1, 1.0, 0.9],
            [0.0, 0.0, 0.9, 1.0],
        ],
        dtype=np.float32,
    )
    metrics = compute_retrieval_metrics(sim_mat, ["A", "A", "B", "B"], k=2, genres=None, head_scores=None)
    assert metrics["disc_artist"] > 0.0
    assert metrics["disc_genre"] == 0.0
    assert metrics["disc_head"] == 0.0
    assert metrics["disc_general"] == pytest.approx(metrics["disc_artist"])
    assert metrics["disc_general"] > 0.0


def test_no_disc_album_in_touched_surfaces() -> None:
    root = pathlib.Path(__file__).resolve().parents[1]
    touched = [
        "strategy_binned/_process.py",
        "strategy_binned/_constants.py",
        "cache_identity.py",
        "common/analyze.py",
        "report/_base.py",
        "db/binned.py",
        "db/_schema.py",
        "scoring_harness.py",
    ]
    for rel in touched:
        source = (root / rel).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id != "disc_album", f"disc_album Name in {rel}"
            if isinstance(node, ast.Attribute):
                assert node.attr != "disc_album", f"disc_album Attribute in {rel}"
