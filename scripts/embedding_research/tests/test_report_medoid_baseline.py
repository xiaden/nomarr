"""Observed global-medoid baseline is rendered separately and never a winner."""

from __future__ import annotations

from scripts.embedding_research.report import run
from scripts.embedding_research.report._retrieval import query_geometry_winners, query_observed_baselines
from scripts.embedding_research.tests._report_seed import RUN_ID, build_seeded_con


def _table(section: dict, table_id: str) -> dict:
    return next(table for table in section["tables"] if table["id"] == table_id)


def test_baseline_never_appears_in_winners_table(tmp_path):
    con = build_seeded_con()
    try:
        winners = query_geometry_winners(con, run_id=RUN_ID)
        baselines = query_observed_baselines(con, run_id=RUN_ID)
        payload = run(con, tmp_path, run_id=RUN_ID)
    finally:
        con.close()

    winner_section = next(section for section in payload["sections"] if section["id"] == "winners")
    winner_table = _table(winner_section, "geometry_representations")
    baseline_table = _table(winner_section, "observed_global_medoid_baseline")

    threshold_index = winner_table["columns"].index("threshold_id")
    assert all(not str(row[threshold_index]).startswith("observed-baseline:") for row in winner_table["rows"])
    baseline_index = baseline_table["columns"].index("threshold_id")
    assert all(str(row[baseline_index]).startswith("observed-baseline:") for row in baseline_table["rows"])
    assert set(baselines["threshold_id"]).issubset(set(winners["threshold_id"]) | set(baselines["threshold_id"]))
