"""Seven-section geometry report: order, identity evidence, and visible refusal."""

from __future__ import annotations

from scripts.embedding_research.report import run
from scripts.embedding_research.report._retrieval import IDENTITY_COLUMNS
from scripts.embedding_research.tests._report_seed import RUN_ID, build_seeded_con

EXPECTED_SECTIONS = ("summary", "corpus", "analysis", "winners", "head-analysis", "provenance", "efficiency")


def _section(payload: dict, section_id: str) -> dict:
    return next(section for section in payload["sections"] if section["id"] == section_id)


def _table(node: dict, table_id: str) -> dict | None:
    for table in node.get("tables", []):
        if table.get("id") == table_id:
            return table
    return None


def test_report_renders_exactly_seven_sections_in_order(tmp_path):
    con = build_seeded_con()
    try:
        payload = run(con, tmp_path, run_id=RUN_ID)
    finally:
        con.close()

    assert [section["id"] for section in payload["sections"]] == list(EXPECTED_SECTIONS)
    assert (tmp_path / "report.json").is_file()
    assert (tmp_path / "report.html").stat().st_size > 0

    analysis = _section(payload, "analysis")
    identity = _table(analysis, "geometry_identity")
    assert identity is not None and not identity.get("empty")
    for column in IDENTITY_COLUMNS:
        assert column in identity["columns"]

    head_identity = _table(_section(payload, "head-analysis"), "geometry_head_identity")
    assert head_identity is not None and not head_identity.get("empty")
    for column in IDENTITY_COLUMNS:
        assert column in head_identity["columns"]
        index = head_identity["columns"].index(column)
        assert all(row[index] not in (None, "", "—") for row in head_identity["rows"])


def test_report_refuses_every_evidence_section_without_completed_scope(con, tmp_path):
    payload = run(con, tmp_path, run_id=None)

    assert [section["id"] for section in payload["sections"]] == list(EXPECTED_SECTIONS)
    for section_id in ("summary", "analysis", "winners", "head-analysis"):
        assert _section(payload, section_id).get("empty_message")
    assert any(warning["level"] == "error" for warning in payload["warnings"])
