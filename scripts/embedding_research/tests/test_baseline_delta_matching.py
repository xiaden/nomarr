"""Matching-only baseline/winner/delta gate (execution-reporting Plan A P3-S1..S4).

Research-only, spec-first.  Pins the delta builder's matching-only contract: a segmented
representation may win a ``(backbone, sim_metric, k, metric)`` cell ONLY when it shares the
observed-medoid baseline's evaluation-corpus identity (equal ``corpus_hash``), is comparable,
and is finite.  A mismatched/non-comparable representation NEVER produces a matched delta and
never partially matches on a shared song subset (no silent intersection) — it is surfaced as a
``BaselineDeltaResult.incomplete`` diagnostic retaining its count/hash/missing evidence.

Branch pins here cover BOTH the ``build_baseline_delta_rows`` level (synthetic identity-bearing
frames) AND the winners-caller / persisted-loader level (``build_winner_delta_rows`` over the
real ``query_winners_metrics`` frame seeded through the analyze-scope writers with real
:class:`EvaluationCorpusIdentity` objects), per P3-S3/S4.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.embedding_research.baseline import (
    BASELINE_DELTA_COLUMNS,
    BaselineDeltaResult,
    build_baseline_delta_rows,
    medoid_strategy_key_for,
)
from scripts.embedding_research.catalog_identity import (
    EVALUATION_CORPUS_SEMANTICS_VERSION,
    EvaluationCorpusIdentity,
)
from scripts.embedding_research.report._retrieval import query_winners_metrics
from scripts.embedding_research.report._winners import (
    CATALOG_WINNER_DELTA_COLUMNS,
    build_winner_delta_rows,
)
from scripts.embedding_research.tests._report_seed import catalog_key, seed_catalog, seed_medoid_baseline

pytestmark = pytest.mark.unit

_EB = "effnet"
_ES = medoid_strategy_key_for(_EB)


# --------------------------------------------------------------------------- #
# Synthetic identity-bearing frame builders (builder-level pins)               #
# --------------------------------------------------------------------------- #
def _corp(hash_, count, *, comparable=True, missing_count=0, digest=""):
    """One row's persisted evaluation-corpus identity columns (mirrors analyze_scope_v2 keys)."""
    return {
        "evaluation_corpus_hash": hash_,
        "evaluation_corpus_count": count,
        "evaluation_corpus_comparable": comparable,
        "evaluation_corpus_missing_count": missing_count,
        "evaluation_corpus_missing_digest": digest or None,
    }


def _base():
    return {
        "backbone": _EB,
        "sim_metric": "cosine",
        "k": 5,
        "metric": "map_k",
        "canonical_config_id": None,
        "alias_ids": [],
    }


def _class_row(keyset: str, value: float, corpus: dict) -> dict:
    return {**_base(), "strategy_key": catalog_key(_EB, keyset), "value": value, **corpus}


def _medoid(value: float, corpus: dict) -> dict:
    return {**_base(), "strategy_key": _ES, "value": value, **corpus}


def _result(rows: list[dict]) -> BaselineDeltaResult:
    return build_baseline_delta_rows(pd.DataFrame(rows))


H4 = _corp("hash-4", 4)
H3 = _corp("hash-3", 3)


def test_equal_corpus_yields_matched_delta_and_no_incomplete():
    # Baseline {A,B,C,D} vs segmented X {A,B,C,D} (equal identity + comparable + finite) -> matched.
    res = _result([_class_row("X", 0.6, H4), _medoid(0.4, H4)])
    assert isinstance(res, BaselineDeltaResult)
    assert res.incomplete == ()
    assert len(res.rows) == 1
    r = res.rows[0]
    assert set(r) == set(BASELINE_DELTA_COLUMNS)
    assert r["winner_strategy_key"] == catalog_key(_EB, "X")
    assert r["winner_value"] == pytest.approx(0.6)
    assert r["delta"] == pytest.approx(0.6 - 0.4)


def test_mismatched_population_no_matched_row_surfaces_incomplete():
    # Baseline {A,B,C,D} vs segmented Y {A,B,C} (different identity) -> NO matched delta and a
    # surfaced incomplete diagnostic retaining the representation's count/hash/provenance.
    res = _result([_class_row("Y", 0.8, H3), _medoid(0.4, H4)])
    assert res.rows == ()
    assert len(res.incomplete) == 1
    inc = res.incomplete[0]
    assert inc["strategy_key"] == catalog_key(_EB, "Y")
    assert inc["backbone"] == _EB
    assert "differs" in inc["reason"]
    assert inc["baseline_strategy_key"] == _ES
    assert inc["baseline_evaluation_corpus_hash"] == "hash-4"
    assert inc["baseline_evaluation_corpus_count"] == 4
    assert inc["representation_evaluation_corpus_hash"] == "hash-3"
    assert inc["representation_evaluation_corpus_count"] == 3
    assert inc["representation_missing_count"] == 0


def test_different_membership_same_count_is_still_a_mismatch():
    # Y {A,B,C,E} has the SAME population size as baseline {A,B,C,D} but a different membership ->
    # a different corpus identity, so it must NOT silently match on the shared {A,B,C} subset.
    other4 = _corp("hash-4-alt", 4)
    res = _result([_class_row("Y", 0.7, other4), _medoid(0.4, H4)])
    assert res.rows == ()
    assert len(res.incomplete) == 1
    assert "differs" in res.incomplete[0]["reason"]


def test_non_comparable_representation_never_matches_even_with_equal_hash():
    # A segmented representation that lost a baseline-eligible song (comparable=False, missing
    # evidence) never matches the equal-hash baseline: no matched row + incomplete retaining the
    # excluded-song count/digest evidence.
    lossy = _corp("hash-4", 3, comparable=False, missing_count=1, digest="md:s4")
    res = _result([_class_row("Z", 0.9, lossy), _medoid(0.4, H4)])
    assert res.rows == ()
    assert len(res.incomplete) == 1
    inc = res.incomplete[0]
    assert "non-comparable" in inc["reason"]
    assert inc["representation_evaluation_corpus_count"] == 3
    assert inc["representation_missing_count"] == 1
    assert inc["representation_missing_digest"] == "md:s4"


def test_no_silent_intersection_never_merges_mismatch_into_winner():
    # Same cell carries BOTH a matching representation X {A,B,C,D} (0.6) and a mismatched Y
    # {A,B,C} (0.8).  The 0.8 Y must NOT win on the shared subset: the matched winner is X (0.6)
    # and Y is surfaced as an incomplete diagnostic (no silent partial comparison).
    res = _result([_class_row("X", 0.6, H4), _class_row("Y", 0.8, H3), _medoid(0.4, H4)])
    assert len(res.rows) == 1
    r = res.rows[0]
    assert r["winner_strategy_key"] == catalog_key(_EB, "X")
    assert r["winner_value"] == pytest.approx(0.6)  # never the mismatched 0.8
    assert r["delta"] == pytest.approx(0.6 - 0.4)
    assert len(res.incomplete) == 1
    assert res.incomplete[0]["strategy_key"] == catalog_key(_EB, "Y")


def test_observed_baseline_never_a_winner_candidate_with_identity():
    # The medoid baseline (0.99) beats every segmented class yet is never the winner (delta is
    # class-minus-baseline and negative) — the equality gate never promotes the baseline.
    res = _result([_class_row("only", 0.4, H4), _medoid(0.99, H4)])
    assert len(res.rows) == 1
    r = res.rows[0]
    assert r["winner_strategy_key"] == catalog_key(_EB, "only")
    assert r["baseline_value"] == pytest.approx(0.99)
    assert r["winner_value"] == pytest.approx(0.4)
    assert r["delta"] == pytest.approx(0.4 - 0.99)
    assert res.incomplete == ()


def _crow(backbone: str, keyset: str, value: float, corpus: dict) -> dict:
    return {
        **_base(),
        "backbone": backbone,
        "strategy_key": catalog_key(backbone, keyset),
        "value": value,
        **corpus,
    }


def _mrow(backbone: str, value: float, corpus: dict) -> dict:
    return {
        **_base(),
        "backbone": backbone,
        "strategy_key": medoid_strategy_key_for(backbone),
        "value": value,
        **corpus,
    }


def test_no_cross_backbone_comparison_with_identity():
    # effnet and musicnn are independent per-backbone populations: an effnet medoid row never
    # serves as a musicnn baseline even under the matching-only gate (cells are backbone-keyed).
    mb = "musicnn"
    hm = _corp("hash-m", 4)
    res = _result(
        [
            _crow(_EB, "e", 0.4, H4),
            _mrow(_EB, 0.99, H4),
            _crow(mb, "m", 0.7, hm),
            _mrow(mb, 0.1, hm),
        ]
    )
    by = {r["backbone"]: r for r in res.rows}
    assert set(by) == {_EB, mb}
    assert by[_EB]["winner_value"] == pytest.approx(0.4)
    assert by[mb]["winner_value"] == pytest.approx(0.7)
    assert by[mb]["baseline_value"] == pytest.approx(0.1)


def test_non_finite_value_fails_closed_with_identity():
    df = pd.DataFrame([_class_row("a", float("inf"), H4), _medoid(0.5, H4)])
    with pytest.raises(ValueError):
        build_baseline_delta_rows(df)


# --------------------------------------------------------------------------- #
# Winners-caller level (build_winner_delta_rows over identity-bearing frames)  #
# --------------------------------------------------------------------------- #
def test_winners_caller_equal_corpus_matches():
    df = pd.DataFrame([_class_row("X", 0.6, H4), _medoid(0.4, H4)])
    rows = build_winner_delta_rows(df)
    assert len(rows) == 1
    assert list(rows.columns) == list(CATALOG_WINNER_DELTA_COLUMNS)
    assert rows.iloc[0]["winner_strategy_key"] == catalog_key(_EB, "X")
    assert rows.iloc[0]["delta"] == pytest.approx(0.6 - 0.4)


def test_winners_caller_mismatched_population_emits_no_winner_delta():
    # At the winners-caller level the report frame simply yields NO winner/delta rows (an empty
    # CATALOG_WINNER_DELTA_COLUMNS frame) for a mismatched representation — no silent phantom delta.
    df = pd.DataFrame([_class_row("Y", 0.8, H3), _medoid(0.4, H4)])
    rows = build_winner_delta_rows(df)
    assert rows.empty
    assert list(rows.columns) == list(CATALOG_WINNER_DELTA_COLUMNS)


# --------------------------------------------------------------------------- #
# Persisted-loader level (real analyze-scope writers + real EvaluationCorpusIdentity) #
# --------------------------------------------------------------------------- #
def _identity(songs, *, corpus_hash):
    return EvaluationCorpusIdentity(
        backbone=_EB,
        song_ids=tuple(sorted(songs)),
        corpus_hash=corpus_hash,
        count=len(songs),
        eligible=True,
        comparable=True,
        missing_song_ids=(),
        missing_count=0,
        missing_digest=None,
        semantics_version=EVALUATION_CORPUS_SEMANTICS_VERSION,
    )


def test_persisted_equal_corpus_matches_through_real_loader(con):
    ident = _identity(("A", "B", "C", "D"), corpus_hash="h4")
    seed_catalog(
        con,
        run_id="run-1",
        backbone=_EB,
        strategy_key=catalog_key(_EB, "X"),
        k=5,
        metrics={"map_k": 0.6},
        evaluation_corpus=ident,
    )
    seed_medoid_baseline(con, run_id="run-1", backbone=_EB, k=5, metrics={"map_k": 0.4}, evaluation_corpus=ident)
    rows = build_winner_delta_rows(query_winners_metrics(con))
    assert len(rows) == 1
    assert rows.iloc[0]["winner_strategy_key"] == catalog_key(_EB, "X")
    assert rows.iloc[0]["delta"] == pytest.approx(0.6 - 0.4)


def test_persisted_mismatched_population_surfaces_incomplete_through_real_loader(con):
    # Two DIFFERENT runs over two different requested populations (baseline {A,B,C,D} vs a
    # retained segmented class {A,B,C}) are read whole-table by the loader.  The matching-only
    # gate must NOT produce a cross-population delta, and the mismatched class must be surfaced.
    base = _identity(("A", "B", "C", "D"), corpus_hash="h4")
    seg = _identity(("A", "B", "C"), corpus_hash="h3")
    seed_catalog(
        con,
        run_id="run-seg",
        backbone=_EB,
        strategy_key=catalog_key(_EB, "Y"),
        k=5,
        metrics={"map_k": 0.8},
        evaluation_corpus=seg,
    )
    seed_medoid_baseline(con, run_id="run-base", backbone=_EB, k=5, metrics={"map_k": 0.4}, evaluation_corpus=base)
    winners = build_winner_delta_rows(query_winners_metrics(con))
    assert winners.empty  # no silent cross-population delta
    assert list(winners.columns) == list(CATALOG_WINNER_DELTA_COLUMNS)
    res = build_baseline_delta_rows(query_winners_metrics(con))
    assert res.rows == ()
    assert len(res.incomplete) == 1
    inc = res.incomplete[0]
    assert inc["strategy_key"] == catalog_key(_EB, "Y")
    assert inc["representation_evaluation_corpus_hash"] == "h3"
    assert inc["representation_evaluation_corpus_count"] == 3
    assert inc["baseline_evaluation_corpus_hash"] == "h4"
