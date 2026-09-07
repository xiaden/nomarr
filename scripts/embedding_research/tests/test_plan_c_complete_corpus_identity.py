"""COMPLETE corpus identity/evidence equality (Plan C Phase 1, P1-S1..S3).

Research-only, spec-first, CPU-only — no real corpus / model / audio / ONNX.  Pins the Plan C
contract (CONTRACTS L839): a baseline delta requires COMPLETE equality of the persisted corpus
identity/evidence (requested + eligible membership, missing evidence, observation binding,
semantics/version, completeness/integrity), NOT merely an equal-looking ``corpus_hash``/``count``
or a compatible subset.  A mismatch on ANY field excludes the cell from winner candidacy and is
surfaced as an explicit ``BaselineDeltaResult.incomplete`` diagnostic carrying the field-level
reason — never a silent partial match, never a winner/delta.

These tests exercise BOTH the ``build_baseline_delta_rows`` level (synthetic frames carrying the
full persisted corpus columns) AND the persisted-loader level (real analyze-scope writers + real
:class:`EvaluationCorpusIdentity` objects, seeded through the fixture harness ``con`` fixture),
mirroring ``test_baseline_delta_matching.py``.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.embedding_research.baseline import (
    CORPUS_IDENTITY_COLUMNS,
    build_baseline_delta_rows,
    medoid_strategy_key_for,
)
from scripts.embedding_research.catalog_identity import (
    EVALUATION_CORPUS_SEMANTICS_VERSION,
    EvaluationCorpusIdentity,
    evaluation_corpus_integrity,
    song_ids_digest,
)
from scripts.embedding_research.report._retrieval import query_winners_metrics
from scripts.embedding_research.report._winners import build_winner_delta_rows
from scripts.embedding_research.tests._report_seed import catalog_key, seed_catalog, seed_medoid_baseline

pytestmark = pytest.mark.unit

_EB = "effnet"
_ES = medoid_strategy_key_for(_EB)
_AB = catalog_key(_EB, "X")  # one segmented class strategy key
_BB = catalog_key(_EB, "Y")  # another segmented class strategy key


# --------------------------------------------------------------------------- #
# Full persisted-corpus row builders (13 corpus columns)                      #
# --------------------------------------------------------------------------- #
def _full_corpus(**kw) -> dict:
    """A row's COMPLETE persisted evaluation-corpus identity columns.

    Defaults to a comparable, eligible, complete 4-song corpus ({A,B,C,D}).  Pass keyword
    overrides (including ``None`` / ``""`` to make a field ABSENT / truncated) to build an
    altered / incomplete identity for the adversarial pins.
    """
    d = {
        "evaluation_corpus_hash": "h4",
        "evaluation_corpus_count": 4,
        "evaluation_corpus_comparable": True,
        "evaluation_corpus_missing_count": 0,
        "evaluation_corpus_missing_digest": None,
        "evaluation_corpus_semantics_version": EVALUATION_CORPUS_SEMANTICS_VERSION,
        "evaluation_corpus_eligible": True,
        "evaluation_corpus_eligible_digest": "elig:abcd",
        "evaluation_corpus_requested_count": 4,
        "evaluation_corpus_requested_digest": "req:abcd",
        "evaluation_corpus_observation_digest": "obs:v1",
        "evaluation_corpus_complete": True,
        "evaluation_corpus_integrity": "int:abcd",
    }
    d.update({k: v for k, v in kw.items() if k in CORPUS_IDENTITY_COLUMNS})
    return d


def _rec(strategy_key: str, value: float, corpus: dict | None) -> dict:
    """One long-form delta-builder row: cell provenance + its corpus columns."""
    row = {
        "backbone": _EB,
        "sim_metric": "cosine",
        "k": 5,
        "metric": "map_k",
        "strategy_key": strategy_key,
        "value": value,
        "canonical_config_id": None,
        "alias_ids": [],
    }
    row.update({k: corpus.get(k) for k in CORPUS_IDENTITY_COLUMNS} if corpus else {})
    return row


# --------------------------------------------------------------------------- #
# Identity-level fail-closed gate (P1-S1)                                     #
# --------------------------------------------------------------------------- #
def _complete_identity(
    *,
    backbone: str = _EB,
    songs=("A", "B", "C", "D"),
    corpus_hash: str = "h4",
    eligible: bool = True,
    comparable: bool = True,
    missing=(),
    eligible_digest=None,
    requested=None,
    observation_digest="obs:v1",
    completeness: bool = True,
) -> EvaluationCorpusIdentity:
    """A full COMPLETE :class:`EvaluationCorpusIdentity` with a computed integrity self-check."""
    songs = tuple(sorted(songs))
    missing = tuple(sorted(missing))
    req = tuple(sorted(requested)) if requested is not None else songs
    if not comparable:
        eligible = False
    ed = eligible_digest if eligible_digest is not None else song_ids_digest(songs)
    base = EvaluationCorpusIdentity(
        backbone=backbone,
        song_ids=songs,
        corpus_hash=corpus_hash,
        count=len(songs),
        eligible=eligible,
        comparable=comparable,
        missing_song_ids=missing,
        missing_count=len(missing),
        missing_digest=song_ids_digest(missing) if missing else None,
        semantics_version=EVALUATION_CORPUS_SEMANTICS_VERSION,
        requested_song_ids=req,
        requested_count=len(req),
        requested_digest=song_ids_digest(req),
        eligible_digest=ed,
        observation_digest=observation_digest,
        completeness=False,
        integrity=None,
    )
    return EvaluationCorpusIdentity(
        backbone=base.backbone,
        song_ids=base.song_ids,
        corpus_hash=base.corpus_hash,
        count=base.count,
        eligible=base.eligible,
        comparable=base.comparable,
        missing_song_ids=base.missing_song_ids,
        missing_count=base.missing_count,
        missing_digest=base.missing_digest,
        semantics_version=base.semantics_version,
        requested_song_ids=base.requested_song_ids,
        requested_count=base.requested_count,
        requested_digest=base.requested_digest,
        eligible_digest=base.eligible_digest,
        observation_digest=base.observation_digest,
        completeness=completeness,
        integrity=evaluation_corpus_integrity(base) if completeness else None,
    )


def test_complete_identity_flag_refuses_truncated_evidence() -> None:
    """A ``completeness=True`` corpus missing ANY proof field is refused before any write."""
    with pytest.raises(ValueError, match="observation-binding proof"):
        _complete_identity(observation_digest="")
    with pytest.raises(ValueError, match="eligible membership proof"):
        _complete_identity(eligible_digest="")
    with pytest.raises(ValueError, match="requested membership proof"):
        # completeness with an empty requested population is internally inconsistent
        _complete_identity(requested=())


# --------------------------------------------------------------------------- #
# Builder-level adversarial pins (P1-S2/P1-S3, a-f)                           #
# --------------------------------------------------------------------------- #
def test_f_complete_equal_identity_yields_delta() -> None:
    """(f) One valid full match (equal complete identity) DOES produce a delta."""
    baseline = {"strategy_key": _ES, "value": 0.4}
    candidate = {"strategy_key": _AB, "value": 0.6}
    res = build_baseline_delta_rows(
        pd.DataFrame(
            [
                _rec(baseline["strategy_key"], baseline["value"], _full_corpus()),
                _rec(candidate["strategy_key"], candidate["value"], _full_corpus()),
            ]
        )
    )
    assert res.incomplete == ()
    assert len(res.rows) == 1
    assert res.rows[0]["winner_strategy_key"] == _AB
    assert res.rows[0]["baseline_strategy_key"] == _ES
    assert res.rows[0]["delta"] == pytest.approx(0.6 - 0.4)


def test_a_abcd_baseline_vs_abc_candidate_no_delta_incomplete() -> None:
    """(a) {A,B,C,D} baseline vs {A,B,C} candidate -> NO delta + explicit incomplete reason."""
    base = _rec(_ES, 0.4, _full_corpus())
    seg = _rec(
        _AB,
        0.6,
        _full_corpus(
            evaluation_corpus_hash="h3",
            evaluation_corpus_count=3,
            evaluation_corpus_eligible_digest="elig:abc",
            evaluation_corpus_requested_count=3,
            evaluation_corpus_requested_digest="req:abc",
            evaluation_corpus_integrity="int:abc",
        ),
    )
    res = build_baseline_delta_rows(pd.DataFrame([base, seg]))
    assert res.rows == ()
    assert len(res.incomplete) == 1
    inc = res.incomplete[0]
    assert inc["strategy_key"] == _AB
    assert inc["baseline_strategy_key"] == _ES
    assert "differs" in inc["reason"]
    # the full mismatch field reason is carried (report-visible), naming the differing fields
    assert "eligible count differs" in inc["reason"]
    assert inc["representation_evaluation_corpus_hash"] == "h3"


def test_b_equal_looking_hash_count_altered_membership_is_unequal() -> None:
    """(b) Altered membership that KEEPS an equal hash/count/count is still detected unequal."""
    base = _rec(_ES, 0.4, _full_corpus())
    # same corpus_hash + count + comparability as the baseline, but a DIFFERENT eligible
    # membership digest (a re-sorted / different id set of the same size) => forged equal look.
    forged = _rec(
        _AB,
        0.6,
        _full_corpus(
            evaluation_corpus_eligible_digest="elig:dcba",  # altered membership, equal hash/count
            evaluation_corpus_requested_digest="req:dcba",
            evaluation_corpus_integrity="int:forged",
        ),
    )
    res = build_baseline_delta_rows(pd.DataFrame([base, forged]))
    assert res.rows == ()
    assert len(res.incomplete) == 1
    reason = res.incomplete[0]["reason"]
    assert "differs" in reason
    assert "eligible membership digest differs" in reason


def test_c_missing_observation_evidence_is_unequal() -> None:
    """(c) A candidate whose observation-binding evidence is absent is refused/unequal."""
    base = _rec(_ES, 0.4, _full_corpus())
    # candidate carries no observation-binding evidence (absent field) but identical hash/count
    lossy = _rec(_AB, 0.6, _full_corpus(evaluation_corpus_observation_digest=None))
    res = build_baseline_delta_rows(pd.DataFrame([base, lossy]))
    assert res.rows == ()
    assert len(res.incomplete) == 1
    assert "observation-binding digest present on only one side" in res.incomplete[0]["reason"]


def test_d_identity_less_rows_never_match_surfaced_incomplete() -> None:
    """(d) Identity-less rows are never matched; surfaced as incomplete diagnostics."""
    # candidate carries NO corpus identity at all while the baseline carries a full one.
    base = _rec(_ES, 0.4, _full_corpus())
    naked = _rec(_AB, 0.9, None)
    res = build_baseline_delta_rows(pd.DataFrame([base, naked]))
    assert res.rows == ()
    assert len(res.incomplete) == 1
    assert res.incomplete[0]["strategy_key"] == _AB
    assert "only one side" in res.incomplete[0]["reason"]
    # identity-less baseline row means the whole cell is refused, too.
    both_naked = _rec(_AB, 0.9, None), _rec(_ES, 0.4, None)
    res2 = build_baseline_delta_rows(pd.DataFrame([both_naked[1], both_naked[0]]))
    assert res2.rows == ()
    assert len(res2.incomplete) == 1


def test_e_non_comparable_class_is_incomplete_never_a_winner() -> None:
    """(e) A non-comparable class is surfaced incomplete, never a winner candidate."""
    base = _rec(_ES, 0.4, _full_corpus())
    nc = _rec(
        _AB,
        0.9,  # highest raw value, but non-comparable
        _full_corpus(
            evaluation_corpus_count=3,
            evaluation_corpus_comparable=False,
            evaluation_corpus_eligible=False,
            evaluation_corpus_missing_count=1,
            evaluation_corpus_missing_digest="md:s4",
            evaluation_corpus_eligible_digest="elig:abc",
            evaluation_corpus_requested_count=4,
            evaluation_corpus_requested_digest="req:abcd",
            evaluation_corpus_integrity="int:nc",
        ),
    )
    res = build_baseline_delta_rows(pd.DataFrame([base, nc]))
    assert res.rows == ()
    assert len(res.incomplete) == 1
    assert "non-comparable" in res.incomplete[0]["reason"]
    assert res.incomplete[0]["representation_evaluation_corpus_count"] == 3


def test_tampered_integrity_self_check_is_unequal() -> None:
    """The gate compares the integrity self-check field (an altered one is unequal)."""
    base = _rec(_ES, 0.4, _full_corpus())
    # identical membership/hash/count evidence but a DIFFERENT (stale/forged) integrity digest
    tampered = _rec(
        _AB,
        0.6,
        _full_corpus(
            evaluation_corpus_integrity="int:stale",
        ),
    )
    res = build_baseline_delta_rows(pd.DataFrame([base, tampered]))
    assert res.rows == ()
    assert len(res.incomplete) == 1
    assert "integrity self-check differs" in res.incomplete[0]["reason"]


# --------------------------------------------------------------------------- #
# Persisted-loader level (real writers + real complete identities)            #
# --------------------------------------------------------------------------- #
def test_persisted_equal_complete_identity_matches(con) -> None:
    ident = _complete_identity()
    seed_catalog(
        con, run_id="run-1", backbone=_EB, strategy_key=_AB, k=5, metrics={"map_k": 0.6}, evaluation_corpus=ident
    )
    seed_medoid_baseline(con, run_id="run-1", backbone=_EB, k=5, metrics={"map_k": 0.4}, evaluation_corpus=ident)
    rows = build_winner_delta_rows(query_winners_metrics(con))
    assert len(rows) == 1
    assert rows.iloc[0]["winner_strategy_key"] == _AB
    assert rows.iloc[0]["delta"] == pytest.approx(0.2)


def test_persisted_altered_membership_equal_hash_detected_unequal(con) -> None:
    # baseline over {A,B,C,D}; a retained class with the SAME corpus_hash/count/comparable but an
    # altered eligible-membership digest (equal-looking hash/count that must NOT match).
    base = _complete_identity()
    seg = _complete_identity(
        corpus_hash="h4",
        eligible_digest="elig:ABCE",  # same size, different membership => altered
        observation_digest="obs:v1",
    )
    seed_catalog(
        con, run_id="run-seg", backbone=_EB, strategy_key=_BB, k=5, metrics={"map_k": 0.8}, evaluation_corpus=seg
    )
    seed_medoid_baseline(con, run_id="run-base", backbone=_EB, k=5, metrics={"map_k": 0.4}, evaluation_corpus=base)
    res = build_baseline_delta_rows(query_winners_metrics(con))
    assert res.rows == ()
    assert len(res.incomplete) == 1
    assert "eligible membership digest differs" in res.incomplete[0]["reason"]


def test_persisted_missing_observation_evidence_is_unequal(con) -> None:
    # A retained class resolved WITHOUT observation-binding evidence vs a baseline WITH it is
    # unequal (present-vs-absent evidence), even sharing hash/count/comparable.
    base = _complete_identity()
    seg = _complete_identity(observation_digest="", completeness=False)  # absent obs evidence
    seed_catalog(
        con, run_id="run-seg2", backbone=_EB, strategy_key=_BB, k=5, metrics={"map_k": 0.7}, evaluation_corpus=seg
    )
    seed_medoid_baseline(con, run_id="run-base2", backbone=_EB, k=5, metrics={"map_k": 0.4}, evaluation_corpus=base)
    res = build_baseline_delta_rows(query_winners_metrics(con))
    assert res.rows == ()
    assert len(res.incomplete) == 1
    assert "observation-binding digest" in res.incomplete[0]["reason"]


def test_persisted_abcd_vs_abc_no_delta_through_real_loader(con) -> None:
    # The canonical P1-S3 (a) scenario through the real loader: {A,B,C,D} baseline vs a retained
    # {A,B,C} segmented class => no delta, explicit incomplete, and NO winner row from the caller.
    base = _complete_identity()
    seg = _complete_identity(
        songs=("A", "B", "C"),
        corpus_hash="h3",
        observation_digest="obs:v1",
    )
    seed_catalog(
        con, run_id="run-seg3", backbone=_EB, strategy_key=_BB, k=5, metrics={"map_k": 0.8}, evaluation_corpus=seg
    )
    seed_medoid_baseline(con, run_id="run-base3", backbone=_EB, k=5, metrics={"map_k": 0.4}, evaluation_corpus=base)
    winners = build_winner_delta_rows(query_winners_metrics(con))
    assert winners.empty
    assert list(winners.columns) == list(build_winner_delta_rows(pd.DataFrame()).columns)
    res = build_baseline_delta_rows(query_winners_metrics(con))
    assert res.rows == ()
    assert len(res.incomplete) == 1
    assert res.incomplete[0]["baseline_evaluation_corpus_hash"] == "h4"
    assert "eligible count differs" in res.incomplete[0]["reason"]
