"""Seven-section geometry report: order, identity evidence, and visible refusal."""

from __future__ import annotations

import pytest

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
        payload = run(
            con,
            tmp_path,
            run_id=RUN_ID,
            html_out_path=tmp_path.parent / "docs" / "embedding-research-report.html",
        )
    finally:
        con.close()

    assert [section["id"] for section in payload["sections"]] == list(EXPECTED_SECTIONS)
    assert (tmp_path / "report.json").is_file()
    html_path = tmp_path.parent / "docs" / "embedding-research-report.html"
    assert html_path.is_file() and html_path.stat().st_size > 0
    assert not list(tmp_path.rglob("*.html"))
    assert all(path.suffix == ".json" for path in tmp_path.rglob("*") if path.is_file())

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


def test_report_rejects_in_root_viewer_before_writing(tmp_path):
    con = build_seeded_con()
    report_dir = tmp_path / "report"
    from scripts.embedding_research.config import OUTPUT_ROOT

    viewer = OUTPUT_ROOT / "docs" / "embedding-research-report.html"
    try:
        with pytest.raises(ValueError, match="outside the scientific JSON root"):
            run(con, report_dir, run_id=RUN_ID, html_out_path=viewer)
    finally:
        con.close()

    assert not report_dir.exists()
    assert not viewer.exists()
