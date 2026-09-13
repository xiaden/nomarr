"""Deterministic fixture durability: re-read, re-validate, and stable re-render."""

from __future__ import annotations

import json

from scripts.embedding_research.generate_fixture_report import main
from scripts.embedding_research.validate_fixture_report import validate_fixture_report


def test_fixture_report_survives_reload_and_rerun(tmp_path):
    html_path = tmp_path.parent / "docs" / "embedding-research-report.html"
    report_path = main(tmp_path, html_out_path=html_path)
    validate_fixture_report(report_path)
    first = json.loads(report_path.read_text(encoding="utf-8"))

    # Re-validate the persisted artifact without regenerating it.
    validate_fixture_report(report_path)

    # A second render into the same directory replaces the artifacts durably.
    report_path = main(tmp_path, html_out_path=html_path)
    validate_fixture_report(report_path)
    second = json.loads(report_path.read_text(encoding="utf-8"))

    assert first["synthetic_only"] is True
    assert second["synthetic_only"] is True
    first.pop("run_ts", None)
    second.pop("run_ts", None)
    assert first == second
    html_path = tmp_path.parent / "docs" / "embedding-research-report.html"
    assert html_path.stat().st_size > 0
    assert not list(tmp_path.rglob("*.html"))
    assert all(path.suffix == ".json" for path in tmp_path.rglob("*") if path.is_file())
