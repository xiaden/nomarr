"""Command-level smoke: fixture generation renders and validates the seven-section report."""

from __future__ import annotations

import json

from scripts.embedding_research.generate_fixture_report import main
from scripts.embedding_research.tests._report_seed import PHASE_NAMES
from scripts.embedding_research.validate_fixture_report import validate_fixture_report

EXACT_SECTION_IDS = ("summary", "corpus", "analysis", "winners", "head-analysis", "provenance", "efficiency")


def test_generate_fixture_report_command_smoke(tmp_path):
    report_path = main(tmp_path)
    validate_fixture_report(report_path)

    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert [section["id"] for section in data["sections"]] == list(EXACT_SECTION_IDS)
    assert data["synthetic_only"] is True
    assert tuple(data["geometry_evidence"]["phases"]) == PHASE_NAMES
    assert (tmp_path / "report.html").stat().st_size > 0
