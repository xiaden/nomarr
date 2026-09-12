"""R11 — report schema/provenance golden, exact identity columns, no retired vocabulary.

The report renders exactly seven ordered sections from independent axes; the analysis
and head-analysis identity tables carry the full identity column set; every recorded
phase is present in provenance; and the generated JSON/HTML contain no retired token.
"""

from __future__ import annotations

from scripts.embedding_research.report import run
from scripts.embedding_research.report._retrieval import IDENTITY_COLUMNS
from scripts.embedding_research.tests import _report_seed
from scripts.embedding_research.tests import test_audit_forbidden_vocabulary as audit
from scripts.embedding_research.tests._gram_evidence import emit_evidence

_EXPECTED_SECTIONS = ("summary", "corpus", "analysis", "winners", "head-analysis", "provenance", "efficiency")
_EXPECTED_TABLES = {
    "summary": ["geometry_threshold_summary", "observed_baseline_summary"],
    "corpus": ["per_artist"],
    "analysis": ["geometry_identity", "geometry_analysis"],
    "winners": ["geometry_representations", "observed_global_medoid_baseline"],
    "head-analysis": ["geometry_head_identity"],
    "provenance": ["run_history", "artifact_hashes"],
    "efficiency": ["timing_history"],
}


def _section(payload: dict, section_id: str) -> dict:
    return next(section for section in payload["sections"] if section["id"] == section_id)


def _table(node: dict, table_id: str) -> dict:
    return next(table for table in node.get("tables", []) if table.get("id") == table_id)


def _run_report(tmp_path) -> dict:
    con = _report_seed.build_seeded_con()
    try:
        return run(con, tmp_path, run_id=_report_seed.RUN_ID)
    finally:
        con.close()


def test_report_schema_and_provenance_golden(tmp_path) -> None:
    payload = _run_report(tmp_path)
    assert payload["schema_version"]
    assert [section["id"] for section in payload["sections"]] == list(_EXPECTED_SECTIONS)
    tables = {section["id"]: [table["id"] for table in section.get("tables", [])] for section in payload["sections"]}
    assert tables == _EXPECTED_TABLES
    assert (tmp_path / "report.json").stat().st_size > 0
    assert (tmp_path / "report.html").stat().st_size > 0

    identity = _table(_section(payload, "analysis"), "geometry_identity")
    assert not identity.get("empty")
    assert list(IDENTITY_COLUMNS) == list(identity["columns"]) or set(IDENTITY_COLUMNS) <= set(identity["columns"])
    head_identity = _table(_section(payload, "head-analysis"), "geometry_head_identity")
    assert not head_identity.get("empty")

    provenance = _section(payload, "provenance")
    run_history = _table(provenance, "run_history")
    phase_index = run_history["columns"].index("phase")
    phases = [row[phase_index] for row in run_history["rows"]]
    assert set(phases) == set(_report_seed.PHASE_NAMES)
    assert len(phases) == 7

    winners = _section(payload, "winners")
    assert _table(winners, "geometry_representations")
    assert _table(winners, "observed_global_medoid_baseline")  # baseline ruler stays independent

    emit_evidence(
        "r11-report-identity.json",
        {
            "schema_version": payload["schema_version"],
            "section_ids": list(_EXPECTED_SECTIONS),
            "tables": tables,
            "identity_columns": list(identity["columns"]),
            "phases": sorted(set(phases)),
        },
    )


def test_report_has_no_retired_vocabulary(tmp_path) -> None:
    _run_report(tmp_path)
    # The vendored Plotly bundle inside report.html contains third-party identifiers.
    # Scan only authored report content: the JSON payload and the HTML with embedded
    # scripts removed.
    import re

    html = re.sub(r"(?is)<script.*?</script>", "", (tmp_path / "report.html").read_text(encoding="utf-8"))
    text = (tmp_path / "report.json").read_text(encoding="utf-8") + html
    lowered = text.lower()
    for fragment in (*audit.retired_vocabulary(), *audit.retired_filesystem_artifacts()):
        assert fragment.lower() not in lowered, f"retired token {fragment!r} present in report output"
    emit_evidence(
        "r11-report-vocabulary.json",
        {"retired_tokens": 0, "report_json_bytes": (tmp_path / "report.json").stat().st_size},
    )
