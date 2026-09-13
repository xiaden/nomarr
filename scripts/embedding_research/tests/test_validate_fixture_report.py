"""Report validator tests (research-only, synthetic).

These tests exercise :mod:`scripts.embedding_research.validate_fixture_report` against the
deterministic seven-section synthetic geometry report and its fail-closed report checks.
The Git/source R1-R14 traceability replay machinery that previously lived in this module
was hard-deleted by the corrective repair pass; the negative absence and
scientific-hash-retention assertions live in
``test_traceability_absence.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.embedding_research.tools._evidence import _j
from scripts.embedding_research.validate_fixture_report import (
    validate_fixture_report,
    validate_report,
)

_PREVIEW = _j("cat", "alog", "_id")


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("report-workspace")
    report_dir = root / "report"
    from scripts.embedding_research.generate_fixture_report import main as generate_report

    viewer = root.parent / f"{root.name}_runtime" / "docs" / "embedding-research-report.html"
    report_path = generate_report(report_dir, html_out_path=viewer)
    return {"root": root, "report": Path(report_path), "viewer": viewer}


def test_valid_report_accepted(workspace: dict[str, Path]) -> None:
    assert validate_report(workspace["report"]) == []
    validate_fixture_report(workspace["report"])


def test_external_viewer_is_required_outside_json_root(workspace: dict[str, Path]) -> None:
    report = workspace["root"] / "without-viewer" / "report" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(workspace["report"].read_text(encoding="utf-8"), encoding="utf-8")
    (report.parent / "report.html").write_text("<html></html>", encoding="utf-8")

    problems = validate_report(report)
    assert any("external sibling embedding-research-report.html is missing or empty" in problem for problem in problems)


def test_runtime_report_accepts_runtime_sibling_viewer(workspace: dict[str, Path]) -> None:
    report = workspace["root"] / "outputs" / "embedding_research" / "report" / "report.json"
    report.parent.mkdir(parents=True)
    report.write_text(workspace["report"].read_text(encoding="utf-8"), encoding="utf-8")
    viewer = workspace["root"] / "outputs" / "embedding_research_runtime" / "docs" / "embedding-research-report.html"
    viewer.parent.mkdir(parents=True)
    viewer.write_text("<html></html>", encoding="utf-8")

    assert validate_report(report) == []


def test_in_root_docs_viewer_is_rejected(workspace: dict[str, Path]) -> None:
    viewer = workspace["report"].parent.parent / "docs" / "embedding-research-report.html"
    viewer.parent.mkdir(parents=True, exist_ok=True)
    viewer.write_text("<html></html>", encoding="utf-8")
    problems = validate_report(workspace["report"], html_path=viewer)
    assert any("outside the scientific JSON root" in problem for problem in problems)


def test_explicit_external_viewer_is_accepted(workspace: dict[str, Path]) -> None:
    viewer = workspace["root"].parent / "custom-docs" / "embedding-research-report.html"
    viewer.parent.mkdir(parents=True)
    viewer.write_text("<html></html>", encoding="utf-8")

    assert validate_report(workspace["report"], html_path=viewer) == []


def test_root_viewer_is_rejected_even_when_explicit(workspace: dict[str, Path]) -> None:
    viewer = workspace["report"].parent / "report.html"
    viewer.write_text("<html></html>", encoding="utf-8")

    problems = validate_report(workspace["report"], html_path=viewer)
    assert any("outside the scientific JSON root" in problem for problem in problems)


def test_missing_report_is_rejected(workspace: dict[str, Path]) -> None:
    problems = validate_report(workspace["root"] / "absent.json")
    assert any("fixture report not found" in problem for problem in problems)
    with pytest.raises(ValueError):
        validate_fixture_report(workspace["root"] / "absent.json")


def test_non_finite_value_is_rejected(workspace: dict[str, Path]) -> None:
    report = json.loads(workspace["report"].read_text(encoding="utf-8"))
    report["sections"][0]["panels"] = [{"id": "broken", "value": float("inf")}]
    mutated = workspace["root"] / "nonfinite.json"
    mutated.write_text(json.dumps(report), encoding="utf-8")
    problems = validate_report(mutated)
    assert any("is non-finite" in problem for problem in problems)


def test_report_has_no_retired_identity_columns(workspace: dict[str, Path]) -> None:
    report = json.loads(workspace["report"].read_text(encoding="utf-8"))
    blob = json.dumps(report)
    assert _PREVIEW not in blob
    assert _j("cat", "alog", "_fingerprint") not in blob
