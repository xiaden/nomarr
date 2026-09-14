"""Winners section renders class-scoped neighborhoods and the observed baseline separately."""

from __future__ import annotations

from scripts.embedding_research.report._retrieval import collect_report_frames
from scripts.embedding_research.report._winners_report import section_winners
from scripts.embedding_research.tests._report_seed import RUN_ID, build_seeded_con


def _table_ids(section: dict) -> set[str]:
    return {table["id"] for table in section.get("tables", [])}


def test_section_winners_renders_class_and_baseline_tables():
    con = build_seeded_con()
    try:
        frames = collect_report_frames(con, run_id=RUN_ID)
        section = section_winners(frames)
    finally:
        con.close()

    assert section["id"] == "winners"
    assert {"geometry_representations", "observed_global_medoid_baseline"} <= _table_ids(section)
    assert not section.get("empty_message")


def test_section_winners_refuses_when_evidence_absent():
    section = section_winners(None)
    assert section["empty_message"]
    assert section.get("warnings")
