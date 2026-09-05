"""Report wiring + active catalog loader tests (catalog-only, seven-section contract).

Research-only.  Verifies report.run() emits EXACTLY seven section ids in order, that the
active loader is catalog-only (never filters through a legacy strategy allowlist), that
run_id scoping works, and that no forbidden legacy vocabulary is emitted.
"""

from __future__ import annotations

import json

import pytest

from scripts.embedding_research.db.analyze_scope import record_analyze_run_scope
from scripts.embedding_research.db.flat import write_analyze_metrics
from scripts.embedding_research.report import run as report_run
from scripts.embedding_research.report._base import decode_catalog_strategy_key
from scripts.embedding_research.report._retrieval import query_analyze_metrics
from scripts.embedding_research.tests._report_seed import (
    EXACT_SECTION_IDS,
    assert_no_forbidden_vocabulary,
    catalog_key,
    seed_catalog,
)


def _section_ids(payload: dict) -> list[str]:
    return [s["id"] for s in payload["sections"]]


def test_run_requires_out_path(con):
    with pytest.raises(ValueError):
        report_run(con)


def test_run_empty_payload_emits_exact_seven_sections(con, tmp_path):
    payload = report_run(con, tmp_path)
    assert _section_ids(payload) == list(EXACT_SECTION_IDS)
    assert payload["schema_version"] == 2
    # Empty catalog: the data-driven sections must say so explicitly.
    for sid in ("summary", "analysis", "winners"):
        section = next(s for s in payload["sections"] if s["id"] == sid)
        assert section.get("empty_message")
    assert (tmp_path / "report.json").exists()
    assert (tmp_path / "report.html").exists()


def test_run_seeded_catalog_seven_sections_catalog_only_and_no_forbidden_vocab(con, tmp_path):
    seed_catalog(
        con,
        run_id="run-1",
        backbone="effnet",
        strategy_key=catalog_key("effnet", keyset="a1b2"),
        k=5,
        metrics={"map_k": 0.6, "mrr": 0.5},
        config_ids=(3, 7),
    )
    # A legacy / non-catalog strategy_type row must NEVER be read or emitted.
    write_analyze_metrics(
        con,
        "global_pool:effnet:medoid",
        "global_pool",
        "cosine",
        5,
        {"map_k": 0.99},
        run_id="run-legacy",
    )

    payload = report_run(con, tmp_path)
    assert _section_ids(payload) == list(EXACT_SECTION_IDS)
    assert_no_forbidden_vocabulary(payload)

    analysis = next(s for s in payload["sections"] if s["id"] == "analysis")
    tables = analysis["subsections"][0]["tables"]
    rows = tables[0]["rows"]
    assert tables[0]["id"] == "catalog_analysis_effnet"
    # Only the catalog class; the global_pool legacy row is absent.
    assert all("global_pool" not in str(r) for r in rows)
    assert any("catalog:effnet:max_per_candidate_segment:v1:a1b2" in str(r) for r in rows)
    # canonical_config_id 3 (config_ids=(3,7)) with alias 7 carried, never duplicated.
    text = json.dumps(rows)
    assert '"3"' in text
    assert "7" in text


def test_run_id_scope_filters_catalog_rows(con, tmp_path):
    seed_catalog(
        con,
        run_id="run-1",
        backbone="effnet",
        strategy_key=catalog_key("effnet", "k1"),
        k=5,
        metrics={"map_k": 0.6},
    )
    seed_catalog(
        con,
        run_id="run-2",
        backbone="effnet",
        strategy_key=catalog_key("effnet", "k2"),
        k=5,
        metrics={"map_k": 0.7},
    )
    # Unscoped sees both classes.
    all_rows = query_analyze_metrics(con)
    assert len(all_rows) == 2
    # run_id-scoped sees exactly one run's rows.
    scoped = query_analyze_metrics(con, run_id="run-2")
    assert sorted(set(scoped["strategy_key"])) == [catalog_key("effnet", "k2")]

    payload = report_run(con, tmp_path, run_id="run-2")
    assert _section_ids(payload) == list(EXACT_SECTION_IDS)


def test_decode_catalog_strategy_key():
    got = decode_catalog_strategy_key("catalog:effnet:max_per_candidate_segment:v1:aabbcc")
    assert got is not None
    assert got["backbone"] == "effnet"
    assert got["score_variant"] == "max_per_candidate_segment"
    assert got["scoring_semantics_version"] == 1
    assert got["keyset_hash"] == "aabbcc"
    # Malformed / legacy keys are not decoded.
    assert decode_catalog_strategy_key("global_pool:effnet:medoid") is None
    assert decode_catalog_strategy_key("catalog:effnet:sv:notver:abcd") is None


def test_query_analyze_metrics_catalog_only_never_legacy_allowlist(con):
    write_analyze_metrics(
        con,
        "ptc:effnet:tempo:1.00:medoid:medoid:max_per_candidate_segment",
        "ptc",
        "cosine",
        5,
        {"map_k": 0.8},
        run_id="legacy",
    )
    seed_catalog(
        con,
        run_id="run-1",
        backbone="effnet",
        strategy_key=catalog_key("effnet", "zz"),
        k=5,
        metrics={"map_k": 0.6},
    )
    df = query_analyze_metrics(con)
    assert not df.empty
    assert (df["strategy_type"] == "catalog").all()
    assert sorted({str(s) for s in df["strategy_key"]}) == [catalog_key("effnet", "zz")]


def test_query_analyze_metrics_empty_when_table_absent(con):
    con.execute("DROP TABLE IF EXISTS analyze_metrics")
    df = query_analyze_metrics(con)
    assert df.empty
    from scripts.embedding_research.report._base import CATALOG_ANALYSIS_COLUMNS

    assert list(df.columns) == list(CATALOG_ANALYSIS_COLUMNS)


def test_scope_recorded_alias_ids_and_canonical(con):
    # Record the analyze scope (config_ids=(4, 9)) for a class.
    sk = catalog_key("musicnn", "ee")
    record_analyze_run_scope(
        con,
        run_id="run-1",
        strategy_key=sk,
        sim_metric="cosine",
        k=10,
        backbone="musicnn",
        config_ids=(4, 9),
        view_content_hash="vh1",
        score_variant="max_per_candidate_segment",
        scoring_semantics_version=1,
    )
    write_analyze_metrics(
        con,
        sk,
        "catalog",
        "cosine",
        10,
        {"map_k": 0.55},
        run_id="run-1",
    )
    df = query_analyze_metrics(con)
    row = df.iloc[0]
    assert int(row["canonical_config_id"]) == 4
    assert sorted(int(a) for a in row["alias_ids"]) == [9]
    assert row["backbone"] == "musicnn"
