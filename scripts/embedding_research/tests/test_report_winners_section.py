"""Catalog winners-report section tests.

Research-only.  Verifies the ``winners`` section renders per-backbone winner/delta and factor
tables, honours the active-key-only / no-forbidden-vocabulary contract, and yields an
explicit empty message when there are no active catalog results.
"""

from __future__ import annotations

from scripts.embedding_research.report._summary import section_summary
from scripts.embedding_research.report._winners_report import section_winners
from scripts.embedding_research.tests._report_seed import (
    assert_no_forbidden_vocabulary,
    catalog_key,
    seed_catalog,
)

# Active keys allowed in emitted section/table columns.
_ACTIVE_KEYS = {
    "backbone",
    "strategy_key",
    "strategy_type",
    "score_variant",
    "config_id",
    "canonical_config_id",
    "alias_ids",
    "representation_hash",
    "run_id",
    "metric",
    "value",
    "delta",
    "status",
    "coverage",
    "command",
    "hash",
    "limitation",
    "sim_metric",
    "k",
    "n_classes",
    "baseline_strategy_key",
    "baseline_canonical_config_id",
    "baseline_value",
    "winner_strategy_key",
    "winner_canonical_config_id",
    "winner_alias_ids",
    "winner_value",
    "scoring_semantics_version",
    "view_content_hash",
    "head",
    "semantics",
    "threshold_effective",
    "finite",
    "n_songs",
    "n_pooled",
    "boundary_source",
    "head_pool_variant",
    "reference_corpus_hash",
    "input_artifact_hashes",
    "output_artifact_hashes",
    "started_at",
    "finished_at",
    "config_hash",
    "song_count",
    "warning_count",
    "phase",
}


def test_section_winners_empty_message():
    import pandas as pd

    section = section_winners(pd.DataFrame())
    assert section["id"] == "winners"
    assert section.get("empty_message")


def test_section_winners_renders_per_backbone_tables(con):
    seed_catalog(
        con,
        run_id="run-1",
        backbone="effnet",
        strategy_key=catalog_key("effnet", "a"),
        k=5,
        metrics={"map_k": 0.6},
        config_ids=(1, 2),
    )
    seed_catalog(
        con,
        run_id="run-1",
        backbone="musicnn",
        strategy_key=catalog_key("musicnn", "b"),
        k=5,
        metrics={"map_k": 0.5},
    )
    section = section_winners(_load(con))
    assert section["id"] == "winners"
    backbones = [sub["title"] for sub in section["subsections"]]
    assert backbones == ["effnet", "musicnn"]
    effnet_tables = {t["id"] for t in section["subsections"][0]["tables"]}
    assert {"winner_delta_effnet", "factor_classes_effnet"} <= effnet_tables

    # Active-key-only column check on every emitted table.
    for sub in section["subsections"]:
        for tbl in sub["tables"]:
            for col in tbl["columns"]:
                assert col in _ACTIVE_KEYS, f"non-active emitted column {col!r}"
    assert_no_forbidden_vocabulary(section)


def test_section_summary_per_backbone_and_empty(con):
    section_empty = section_summary(_load_empty())
    assert section_empty["id"] == "summary"
    assert section_empty.get("empty_message")

    seed_catalog(
        con,
        run_id="run-1",
        backbone="effnet",
        strategy_key=catalog_key("effnet", "a"),
        k=5,
        metrics={"map_k": 0.7},
        config_ids=(1,),
    )
    section = section_summary(_load(con))
    table = section["tables"][0]
    assert table["id"] == "catalog_result_status"
    cell = dict(zip(table["columns"], table["rows"][0], strict=False))
    assert cell["backbone"] == "effnet"
    assert int(cell["active_catalog_classes"]) == 1
    assert int(cell["evaluation_cells"]) == 1


def _load(con):
    from scripts.embedding_research.report._retrieval import query_analyze_metrics

    return query_analyze_metrics(con)


def _load_empty():
    import pandas as pd

    from scripts.embedding_research.report._base import CATALOG_ANALYSIS_COLUMNS

    return pd.DataFrame(columns=list(CATALOG_ANALYSIS_COLUMNS))
