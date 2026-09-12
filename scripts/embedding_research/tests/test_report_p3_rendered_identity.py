"""Rendered identity: every rendered evidence table carries complete exact identity axes."""

from __future__ import annotations

from scripts.embedding_research.report import run
from scripts.embedding_research.report._retrieval import IDENTITY_COLUMNS
from scripts.embedding_research.tests._report_seed import RUN_ID, build_seeded_con


def _all_tables(node: dict):
    yield from node.get("tables", [])
    for key in ("panels", "subsections"):
        for child in node.get(key, []) or []:
            yield from _all_tables(child)


def test_rendered_identity_tables_have_no_absent_axis(tmp_path):
    con = build_seeded_con()
    try:
        payload = run(con, tmp_path, run_id=RUN_ID)
    finally:
        con.close()

    checked = 0
    for section in payload["sections"]:
        for table in _all_tables(section):
            columns = table.get("columns", [])
            if not all(axis in columns for axis in IDENTITY_COLUMNS):
                continue
            checked += 1
            assert not table.get("empty")
            for axis in IDENTITY_COLUMNS:
                index = columns.index(axis)
                assert all(row[index] not in (None, "", "—") for row in table["rows"])
    assert checked >= 2
