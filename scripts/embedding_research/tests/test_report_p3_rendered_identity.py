"""Plan B P3 rendered-surface tests: semantic-vs-disposable identity, incomplete visibility.

Research-only.  Verifies that the seven-section schema-v2 report RENDERS the separated identity
surface directly from the durable ``analyze_scope_v2`` scope — the DURABLE SEMANTIC
``representation_hash`` distinctly from the DISPOSABLE ``view_keyset_hash``, the catalog anchor,
the per-member threshold/bin/exact evidence, and the persisted evaluation-corpus identity — and
that partial / non-comparable representations are VISIBLY surfaced in the rendered winners and
summary sections (never a silently-matched complete metric).  Also pins finite/escapable JSON+HTML
output and a stable report shape across deterministic seed regeneration.
"""

from __future__ import annotations

import json

import duckdb

from scripts.embedding_research.catalog_identity import (
    EVALUATION_CORPUS_SEMANTICS_VERSION,
    EvaluationCorpusIdentity,
)
from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.report import run as report_run
from scripts.embedding_research.tests._report_seed import (
    EXACT_SECTION_IDS,
    catalog_key,
    seed_catalog,
    seed_medoid_baseline,
)

_SEMANTIC = "9" * 64
_FPRINT = "cf" * 16


def _corpus(song_ids, corpus_hash: str, *, comparable: bool = True, missing=()) -> EvaluationCorpusIdentity:
    ids = tuple(sorted(song_ids))
    missing_ids = tuple(sorted(missing))
    return EvaluationCorpusIdentity(
        backbone="effnet",
        song_ids=ids,
        corpus_hash=corpus_hash,
        count=len(ids),
        eligible=True,
        comparable=comparable,
        missing_song_ids=missing_ids,
        missing_count=len(missing_ids),
        missing_digest="d" * 8 if missing_ids else None,
        semantics_version=EVALUATION_CORPUS_SEMANTICS_VERSION,
    )


def _section(payload, sid: str) -> dict:
    return next(s for s in payload["sections"] if s["id"] == sid)


def _all_tables(section: dict) -> list[dict]:
    tabs = list(section.get("tables") or [])
    for sub in section.get("subsections") or []:
        tabs.extend(sub.get("tables") or [])
    return tabs


def _table(section: dict, tid: str) -> dict:
    return next(t for t in _all_tables(section) if t["id"] == tid)


def _row_map(table: dict, idx: int = 0) -> dict:
    return dict(zip(table["columns"], table["rows"][idx], strict=False))


def _seed_equal_scope(con, *, run_id: str, corpus: EvaluationCorpusIdentity, value: float = 0.8) -> None:
    seed_catalog(
        con,
        run_id=run_id,
        backbone="effnet",
        strategy_key=catalog_key("effnet", "k1"),
        k=5,
        metrics={"map_k": value},
        config_ids=(1, 5),
        evaluation_corpus=corpus,
        search_representation_hash=_SEMANTIC,
        catalog_fingerprint=_FPRINT,
    )
    seed_medoid_baseline(
        con,
        run_id=run_id,
        backbone="effnet",
        k=5,
        metrics={"map_k": 0.5},
        evaluation_corpus=corpus,
        catalog_fingerprint=_FPRINT,
    )


# --------------------------------------------------------------------------- #
# P3-S3: real semantic hash propagation + distinct disposable keyset, end-to-end#
# --------------------------------------------------------------------------- #
def test_rendered_analysis_renders_semantic_distinct_from_disposable_keyset(con, tmp_path):
    _seed_equal_scope(con, run_id="run-r", corpus=_corpus(["a", "b", "c"], "abc"))
    payload = report_run(con, tmp_path)
    assert [s["id"] for s in payload["sections"]] == list(EXACT_SECTION_IDS)

    analysis = _section(payload, "analysis")
    main = _table(analysis, "catalog_analysis_effnet")
    cols = main["columns"]
    # The analysis table renders the separated surface directly: semantic hash, disposable keyset,
    # catalog anchor and evaluation-corpus fields as DISTINCT columns.
    for required in (
        "representation_hash",
        "view_keyset_hash",
        "view_content_hash",
        "catalog_id",
        "catalog_fingerprint",
        "canonical_config_id",
        "alias_ids",
        "config_ids",
        "evaluation_corpus_hash",
        "evaluation_corpus_count",
        "evaluation_corpus_comparable",
    ):
        assert required in cols, f"missing rendered column {required}"
    row = _row_map(main)
    # Semantic is the durable hash, kept distinct from the disposable keyset (k1).
    assert row["representation_hash"] == _SEMANTIC
    assert row["view_keyset_hash"] == "k1"
    assert row["representation_hash"] != row["view_keyset_hash"]
    assert row["catalog_id"]
    assert row["evaluation_corpus_hash"] == "abc"

    # The winners factor roster also carries semantic vs disposable distinctly.
    winners = _section(payload, "winners")
    factor = _table(winners, "factor_classes_effnet")
    frow = _row_map(factor)
    assert frow["representation_hash"] == _SEMANTIC
    assert frow["view_keyset_hash"] == "k1"
    assert frow["representation_hash"] != frow["view_keyset_hash"]


def test_rendered_analysis_member_evidence_per_member(con, tmp_path):
    _seed_equal_scope(con, run_id="run-m", corpus=_corpus(["a", "b", "c"], "abc"))
    payload = report_run(con, tmp_path)
    analysis = _section(payload, "analysis")
    members = _table(analysis, "catalog_members_effnet")
    assert {"config_id", "threshold_configured", "threshold_effective", "bin_mode", "exact_segmentation_hash"} <= set(
        members["columns"]
    )
    # config_ids=(1,5) => exactly two ordered member rows with finite configured==effective
    # threshold, a bin mode and a non-empty exact segmentation hash.
    configs = [r[members["columns"].index("config_id")] for r in members["rows"]]
    assert configs == ["1", "5"]
    for r in members["rows"]:
        m = dict(zip(members["columns"], r, strict=False))
        assert m["threshold_configured"] == m["threshold_effective"]
        assert m["threshold_configured"] != "—"
        assert m["bin_mode"] != "—"
        assert m["exact_segmentation_hash"] not in ("", "—")


# --------------------------------------------------------------------------- #
# P3-S3: baseline provenance is populated (catalog anchor + corpus identity)    #
# --------------------------------------------------------------------------- #
def test_medoid_baseline_seed_populates_catalog_anchor_and_corpus(con):
    from scripts.embedding_research.report._retrieval import query_medoid_baselines

    seed_medoid_baseline(
        con,
        run_id="run-b",
        backbone="effnet",
        k=5,
        metrics={"map_k": 0.5},
        evaluation_corpus=_corpus(["a", "b", "c"], "abc"),
        catalog_fingerprint=_FPRINT,
    )
    row = query_medoid_baselines(con, run_id="run-b").iloc[0]
    # Mirrors the analyze producer: a non-class observed baseline still records its catalog anchor
    # + evaluation-corpus identity + score/scoring provenance on the scope line.
    assert row["catalog_id"]
    assert row["catalog_fingerprint"] == _FPRINT
    assert row["evaluation_corpus_hash"] == "abc"
    assert row["evaluation_corpus_count"] == 3
    assert row["score_variant"] == "max_per_candidate_segment"
    assert row["scoring_semantics_version"] == 1
    # Baseline is not a class: no representation/config/member identity of its own.
    assert row["representation_hash"] is None
    assert row["config_ids"] == []
    assert row["class_members"] == []


# --------------------------------------------------------------------------- #
# P3-S1: incomplete / non-comparable representations are VISIBLE when rendered  #
# --------------------------------------------------------------------------- #
def test_incomplete_representations_visible_in_rendered_winners_and_summary(con, tmp_path):
    # Segmented class population {A,B,C} vs observed-medoid baseline {A,B,C,D}: unequal corpus
    # identity => the cell can never be a matched delta.  The class must be surfaced explicitly
    # (never silently rendered as matched) in the winners incomplete table AND the summary count.
    seed_catalog(
        con,
        run_id="run-inc",
        backbone="effnet",
        strategy_key=catalog_key("effnet", "x"),
        k=5,
        metrics={"map_k": 0.8},
        evaluation_corpus=_corpus(["a", "b", "c"], "abc"),
        search_representation_hash=_SEMANTIC,
    )
    seed_medoid_baseline(
        con,
        run_id="run-inc",
        backbone="effnet",
        k=5,
        metrics={"map_k": 0.5},
        evaluation_corpus=_corpus(["a", "b", "c", "d"], "abcd"),
    )
    payload = report_run(con, tmp_path)

    winners = _section(payload, "winners")
    incomplete = _table(winners, "incomplete_representations_effnet")
    cols = incomplete["columns"]
    row = _row_map(incomplete)
    # The representation is excluded from matched deltas and its per-cell reason is rendered.
    assert "reason" in cols
    assert "differs" in row["reason"]
    assert row["representation_evaluation_corpus_hash"] == "abc"
    assert row["baseline_evaluation_corpus_hash"] == "abcd"
    # The unequal cell produced NO matched winner/delta cell.
    assert not any(t["id"].startswith("winner_delta_effnet") for t in _all_tables(winners))

    summary = _section(payload, "summary")
    status = _table(summary, "catalog_result_status")
    srow = _row_map(status)
    assert srow["incomplete_representations"] == "1"


def test_incomplete_visible_reason_for_non_comparable_representation(con, tmp_path):
    # A representation whose corpus is non-comparable (lost an eligible song => missing evidence)
    # can never match even an equal hash; its reason + missing evidence must be surfaced per cell.
    seg = _corpus(["a", "b"], "ab", comparable=False, missing=["z"])
    baseline = _corpus(["a", "b"], "ab", comparable=True)
    seed_catalog(
        con,
        run_id="run-nc",
        backbone="effnet",
        strategy_key=catalog_key("effnet", "y"),
        k=5,
        metrics={"map_k": 0.8},
        evaluation_corpus=seg,
        search_representation_hash=_SEMANTIC,
    )
    seed_medoid_baseline(
        con,
        run_id="run-nc",
        backbone="effnet",
        k=5,
        metrics={"map_k": 0.5},
        evaluation_corpus=baseline,
    )
    payload = report_run(con, tmp_path)
    winners = _section(payload, "winners")
    incomplete = _table(winners, "incomplete_representations_effnet")
    row = _row_map(incomplete)
    assert row["reason"]
    assert "non-comparable" in row["reason"]
    assert "representation_evaluation_corpus_comparable" in incomplete["columns"]
    assert "representation_missing_count" in incomplete["columns"]
    assert row["representation_missing_count"] != "—"


# --------------------------------------------------------------------------- #
# P3-S3: finite / escaping-safe JSON + HTML + stable shape across regeneration #
# --------------------------------------------------------------------------- #
def test_report_output_finite_and_escaping_safe(con, tmp_path):
    _seed_equal_scope(con, run_id="run-f", corpus=_corpus(["a", "b", "c"], "abc"))
    payload = report_run(con, tmp_path)
    # Finite JSON: json.dumps with allow_nan=False must not raise, and no NaN/Infinity literal may
    # leak into the written report.json.
    json.dumps(payload, default=str, allow_nan=False)
    report_text = (tmp_path / "report.json").read_text()
    for banned in ("NaN", "Infinity", "-Infinity"):
        assert banned not in report_text
    parsed = json.loads(report_text)
    assert parsed["schema_version"] == 2
    assert [s["id"] for s in parsed["sections"]] == list(EXACT_SECTION_IDS)
    # The HTML viewer shell is escaping/rendering safe and stays schematically intact (it loads
    # report.json at runtime, so section data lives in the finite JSON above, not the shell).
    html = (tmp_path / "report.html").read_text()
    assert "renderSection" in html
    assert "report.json" in html


def test_stable_report_shape_across_seed_regeneration(tmp_path):
    def _build():
        con = duckdb.connect(":memory:")
        ensure_schema(con)
        try:
            _seed_equal_scope(con, run_id="run-s", corpus=_corpus(["a", "b", "c"], "abc"))
            return report_run(con, tmp_path / "r")
        finally:
            con.close()

    a = _build()
    b = _build()
    assert [s["id"] for s in a["sections"]] == [s["id"] for s in b["sections"]] == list(EXACT_SECTION_IDS)
    for sa, sb in zip(a["sections"], b["sections"], strict=False):
        ta, tb = _all_tables(sa), _all_tables(sb)
        assert [t["id"] for t in ta] == [t["id"] for t in tb]
        for x, y in zip(ta, tb, strict=False):
            assert x["columns"] == y["columns"]
            assert len(x["rows"]) == len(y["rows"])
