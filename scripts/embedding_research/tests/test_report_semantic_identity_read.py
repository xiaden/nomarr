"""Phase-2 read-surface tests: the report loaders re-source semantic identity.

Research-only.  Verifies the execution-reporting-repair Plan B P2 contract that the report
read surface (``query_analyze_metrics`` / ``query_medoid_baselines``) exposes the DURABLE
semantic catalog identity recorded on the ``analyze_scope_v2`` provenance line — the real
``catalog_identity.search_representation_hash``, never a disposable view/keyset hash as
semantic identity — plus the compact-catalog anchor, ordered member evidence and the kept-
separate disposable view keyset/content identity.  Also verifies that a medoid baseline's
provenance (catalog anchor + score/scoring-semantics) is surfaced rather than left blank, and
that ``BaselineDeltaResult.incomplete`` diagnostics survive ``build_winner_delta_rows``
instead of being silently dropped (so partial representations are never rendered as matched).
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.embedding_research.baseline import medoid_strategy_key_for
from scripts.embedding_research.db import write_analyze_metrics
from scripts.embedding_research.db.analyze_scope import (
    SCOPE_KIND_OBSERVED_BASELINE,
    AnalyzeScopeIdentity,
    ScopeMemberIdentity,
    record_analyze_run_scope,
)
from scripts.embedding_research.report._base import CATALOG_STRATEGY_TYPE
from scripts.embedding_research.report._retrieval import (
    query_analyze_metrics,
    query_medoid_baselines,
)
from scripts.embedding_research.report._winners import build_winner_delta_rows
from scripts.embedding_research.tests._report_seed import catalog_key, seed_catalog

_SEMANTIC = "a" * 64
_FPRINT = "cf" * 32
_FINGER = "exact-" + "e" * 32


def _seed_real_class(con, *, run_id: str, keyset: str = "aa") -> str:
    """Persist a real catalog class whose analyze-scope carries a full durable semantic identity."""
    sk = catalog_key("effnet", keyset)
    write_analyze_metrics(
        con,
        sk,
        CATALOG_STRATEGY_TYPE,
        "cosine",
        5,
        {"map_k": 0.6},
        run_id=run_id,
    )
    record_analyze_run_scope(
        con,
        run_id=run_id,
        identity=AnalyzeScopeIdentity(
            strategy_key=sk,
            sim_metric="cosine",
            k=5,
            backbone="effnet",
            catalog_id="catalog-9",
            catalog_fingerprint=_FPRINT,
            search_representation_hash=_SEMANTIC,
            config_ids=(1, 5),
            members=(
                ScopeMemberIdentity(
                    config_id=1,
                    threshold_configured=0.7,
                    threshold_effective=0.7,
                    bin_mode="temporal_global",
                    exact_segmentation_hash="m1" + _FINGER[3:],
                ),
                ScopeMemberIdentity(
                    config_id=5,
                    threshold_configured=0.9,
                    threshold_effective=0.9,
                    bin_mode="temporal_global",
                    exact_segmentation_hash="m5" + _FINGER[3:],
                ),
            ),
            score_variant="max_per_candidate_segment",
            scoring_semantics_version=1,
            view_keyset_hash=keyset,
            view_content_hash="vh-aa",
            evaluation_corpus_hash="corpus-1",
            evaluation_corpus_count=5,
            evaluation_corpus_comparable=True,
            evaluation_corpus_missing_count=0,
            evaluation_corpus_missing_digest="",
        ),
    )
    return sk


# --------------------------------------------------------------------------- #
# P2-S1/S2: durable semantic identity on the catalog read surface              #
# --------------------------------------------------------------------------- #
def test_real_class_representation_hash_is_semantic_not_keyset(con):
    _seed_real_class(con, run_id="run-real")
    df = query_analyze_metrics(con, run_id="run-real")
    assert not df.empty
    row = df.iloc[0]
    # The report representation hash is the DURABLE semantic hash, NOT the disposable keyset.
    assert row["representation_hash"] == _SEMANTIC
    assert row["representation_hash"] != row["view_keyset_hash"]
    assert row["view_keyset_hash"] == "aa"


def test_real_class_surfaces_catalog_anchor_and_separate_disposable_view(con):
    _seed_real_class(con, run_id="run-real")
    row = query_analyze_metrics(con, run_id="run-real").iloc[0]
    assert row["catalog_id"] == "catalog-9"
    assert row["catalog_fingerprint"] == _FPRINT
    # Config identity: canonical lowest member, sorted alias, full ordered member list.
    assert row["canonical_config_id"] == 1
    assert sorted(int(a) for a in row["alias_ids"]) == [5]
    assert [int(c) for c in row["config_ids"]] == [1, 5]
    assert row["view_content_hash"] == "vh-aa"
    assert row["view_keyset_hash"] != row["view_content_hash"]
    assert row["score_variant"] == "max_per_candidate_segment"
    assert row["scoring_semantics_version"] == 1
    assert row["evaluation_corpus_hash"] == "corpus-1"


def test_real_class_member_evidence_carried_per_member(con):
    _seed_real_class(con, run_id="run-real")
    row = query_analyze_metrics(con, run_id="run-real").iloc[0]
    members = list(row["class_members"])
    assert [m["config_id"] for m in members] == [1, 5]
    m1 = members[0]
    assert m1["threshold_configured"] == pytest.approx(0.7)
    assert m1["threshold_effective"] == pytest.approx(0.7)
    assert m1["bin_mode"] == "temporal_global"
    assert m1["exact_segmentation_hash"].startswith("m1")
    assert members[1]["config_id"] == 5


def test_identity_less_structural_row_stays_visibly_incomplete(con):
    # Structural fixture seed (catalog_id="" => no durable semantic / member evidence / catalog
    # anchor).  Plan B P3 removed the transitional keyset fallback: such a row renders VISIBLY
    # incomplete (representation_hash None) and its disposable keyset rides only in
    # view_keyset_hash — a keyset is never promoted into the semantic representation column.
    seed_catalog(
        con,
        run_id="run-leg",
        backbone="effnet",
        strategy_key=catalog_key("effnet", "bb"),
        k=5,
        metrics={"map_k": 0.7},
        catalog_id="",
    )
    row = query_analyze_metrics(con, run_id="run-leg").iloc[0]
    assert row["representation_hash"] is None  # visibly incomplete, not the keyset
    assert row["view_keyset_hash"] == "bb"  # disposable keyset kept separate
    assert row["catalog_id"] is None
    assert row["catalog_fingerprint"] is None
    # Identity-less but carries the ordered member config ids (default (1,)); no per-member
    # evidence and no durable semantic were recorded (no catalog anchor).
    assert [int(c) for c in row["config_ids"]] == [1]
    assert row["class_members"] == []


# --------------------------------------------------------------------------- #
# P2-S2: medoid baseline provenance is surfaced, not left blank                 #
# --------------------------------------------------------------------------- #
def test_medoid_baseline_carries_catalog_anchor_and_scoring_provenance(con):
    key = medoid_strategy_key_for("effnet")
    write_analyze_metrics(
        con,
        key,
        "global_pool",
        "cosine",
        5,
        {"map_k": 0.5},
        run_id="run-m",
    )
    record_analyze_run_scope(
        con,
        run_id="run-m",
        identity=AnalyzeScopeIdentity(
            strategy_key=key,
            sim_metric="cosine",
            k=5,
            backbone="effnet",
            # A medoid baseline is a NON-class observed scope: explicitly TAGGED observed_baseline
            # (never an identity-less / empty catalog_class exemption under the corrective gate).
            scope_kind=SCOPE_KIND_OBSERVED_BASELINE,
            catalog_id="catalog-9",
            catalog_fingerprint=_FPRINT,
            score_variant="max_per_candidate_segment",
            scoring_semantics_version=1,
            evaluation_corpus_hash="corpus-1",
            evaluation_corpus_count=5,
            evaluation_corpus_comparable=True,
            evaluation_corpus_missing_count=0,
            evaluation_corpus_missing_digest="",
        ),
    )
    df = query_medoid_baselines(con, run_id="run-m")
    assert not df.empty
    row = df.iloc[0]
    assert row["strategy_type"] == "global_pool"
    assert row["catalog_id"] == "catalog-9"
    assert row["catalog_fingerprint"] == _FPRINT
    assert row["score_variant"] == "max_per_candidate_segment"
    assert row["scoring_semantics_version"] == 1
    assert row["evaluation_corpus_hash"] == "corpus-1"
    # A baseline is not a class: no representation / config / member identity of its own.
    assert row["representation_hash"] is None
    assert row["canonical_config_id"] is None
    assert row["config_ids"] == []
    assert row["class_members"] == []


# --------------------------------------------------------------------------- #
# P2-S3/S4: incomplete diagnostics survive the winners DataFrame boundary       #
# --------------------------------------------------------------------------- #
def _cell(backbone: str, sk: str, value: float, *, corpus_hash: str) -> dict:
    return {
        "sim_metric": "cosine",
        "k": 5,
        "metric": "map_k",
        "canonical_config_id": None,
        "alias_ids": [],
        "backbone": backbone,
        "strategy_key": sk,
        "value": value,
        "evaluation_corpus_hash": corpus_hash,
        "evaluation_corpus_count": 3,
        "evaluation_corpus_comparable": True,
        "evaluation_corpus_missing_count": 0,
        "evaluation_corpus_missing_digest": "",
    }


def test_mismatched_corpus_incomplete_carried_not_matched():
    # Adversarial baseline {A,B,C,D} vs representation X={A,B,C}: unequal corpus identity =>
    # the cell can never match, is excluded from matched winner rows, and the incomplete
    # diagnostic is carried through on the returned winner frame (never dropped).
    class_sk = catalog_key("effnet", "x")
    df = pd.DataFrame(
        [
            _cell("effnet", class_sk, 0.8, corpus_hash="hash-abcd"),
            _cell("effnet", medoid_strategy_key_for("effnet"), 0.5, corpus_hash="hash-abc"),
        ]
    )
    winner = build_winner_delta_rows(df)
    # Matched rows exclude the unequal cell entirely (never a matched complete metric).
    assert winner.empty or (winner["strategy_key"] != class_sk).all()
    incomplete = list(winner.attrs.get("baseline_incomplete", ()))
    assert len(incomplete) >= 1
    assert incomplete[0]["strategy_key"] == class_sk
    assert "differs" in incomplete[0]["reason"]


def test_equal_corpus_matches_with_no_incomplete_carried():
    df = pd.DataFrame(
        [
            _cell("effnet", catalog_key("effnet", "x"), 0.8, corpus_hash="hash-abc"),
            _cell("effnet", medoid_strategy_key_for("effnet"), 0.5, corpus_hash="hash-abc"),
        ]
    )
    winner = build_winner_delta_rows(df)
    assert not winner.empty
    assert list(winner.attrs.get("baseline_incomplete", ())) == []


def test_empty_analysis_carries_empty_incomplete():
    empty = pd.DataFrame(columns=["backbone", "strategy_key", "value"])
    winner = build_winner_delta_rows(empty)
    assert winner.empty
    assert list(winner.attrs.get("baseline_incomplete", ())) == []
