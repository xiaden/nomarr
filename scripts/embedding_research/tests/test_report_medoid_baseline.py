"""Observed global-medoid baseline is rendered separately and never a class winner."""

from __future__ import annotations

from scripts.embedding_research.report import run
from scripts.embedding_research.tests._report_seed import RUN_ID, build_seeded_con


def _table(section: dict, table_id: str) -> dict:
    return next(table for table in section["tables"] if table["id"] == table_id)


def test_baseline_window_is_never_a_class_winner(tmp_path):
    con = build_seeded_con()
    try:
        payload = run(con, tmp_path, run_id=RUN_ID)
    finally:
        con.close()

    winner_section = next(section for section in payload["sections"] if section["id"] == "winners")
    class_table = _table(winner_section, "geometry_representations")
    baseline_table = _table(winner_section, "observed_global_medoid_baseline")

    # Class-scoped neighborhoods are keyed by corpus class; the baseline is keyed by backbone.
    assert "corpus_search_class_id" in class_table["columns"]
    assert "backbone" not in class_table["columns"]
    assert "backbone" in baseline_table["columns"]
    assert class_table["rows"]
    assert baseline_table["rows"]
