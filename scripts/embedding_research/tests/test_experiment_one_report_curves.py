"""Test L — normalized report curves: thresholds, single baseline, JOIN-derivable deltas.

Proves the Experiment One report payload renders the threshold -> class -> comparable
status -> class metrics -> delta-vs-baseline curve from the normalized surfaces, keeps
exactly ONE fixed threshold-independent baseline, surfaces non-comparable thresholds with
their canonical reasons, and scopes neighborhood uniqueness by class (never globally by
``(query, candidate)``).
"""

from __future__ import annotations

import pytest

from scripts.embedding_research.report._retrieval import collect_report_frames
from scripts.embedding_research.report._winners import class_neighborhood_rows
from scripts.embedding_research.tests import _report_seed
from scripts.embedding_research.tests._report_seed import RUN_ID

pytestmark = pytest.mark.unit

_TWO_THRESHOLDS = ("t-000", "t-001")


def _two_threshold_con(monkeypatch):
    """Seed a consistent single-backbone (effnet) result with exactly two thresholds."""
    monkeypatch.setattr(_report_seed, "THRESHOLD_IDS", _TWO_THRESHOLDS)
    return _report_seed.build_seeded_con()


def _section(payload: dict, section_id: str) -> dict:
    return next(section for section in payload["sections"] if section["id"] == section_id)


def _table(section: dict, table_id: str) -> dict:
    return next(table for table in section["tables"] if table["id"] == table_id)


def _rows(table: dict) -> list[dict[str, str]]:
    return [dict(zip(table["columns"], row, strict=True)) for row in table["rows"]]


def _warning_messages(section: dict) -> list[str]:
    return [warning["message"] for warning in section.get("warnings", [])]


def test_report_payload_has_two_threshold_points_and_one_fixed_baseline(monkeypatch, tmp_path):
    from scripts.embedding_research.report import run as report_run

    con = _two_threshold_con(monkeypatch)
    try:
        # One non-comparable threshold with its canonical reason must reach the payload.
        con.execute(
            "UPDATE geometry_threshold_class_map SET comparable=FALSE, reasons_json=? WHERE threshold_id=?",
            ['["zero_searchable"]', "t-001"],
        )
        frames = collect_report_frames(con, run_id=RUN_ID)
        payload = report_run(con, tmp_path, run_id=RUN_ID)
    finally:
        con.close()

    analysis = _section(payload, "analysis")
    curve = _rows(_table(analysis, "geometry_threshold_map"))
    assert {row["threshold_id"] for row in curve} == set(_TWO_THRESHOLDS)

    values_by_threshold: dict[str, set[float]] = {threshold_id: set() for threshold_id in _TWO_THRESHOLDS}
    for row in curve:
        values_by_threshold[row["threshold_id"]].add(float(row["class_value"]))
    # Two threshold points with different (collapse) metrics.
    assert values_by_threshold["t-000"] != values_by_threshold["t-001"]
    assert values_by_threshold["t-000"] and values_by_threshold["t-001"]

    # Exactly ONE fixed threshold-independent baseline.
    assert {row["backbone"] for row in frames.baseline_aggregate_metrics} == {_report_seed.ANALYSIS_BACKBONE}
    assert len(_rows(_table(_section(payload, "summary"), "observed_baseline_summary"))) == 1

    # Non-comparable threshold and its canonical reason are explicit in the payload.
    messages = _warning_messages(analysis)
    assert any("Non-comparable threshold t-001" in message for message in messages)
    assert any("zero_searchable" in message for message in messages)


def test_threshold_class_metric_curve_is_derivable_by_join(monkeypatch, tmp_path):
    from scripts.embedding_research.report import run as report_run

    con = _two_threshold_con(monkeypatch)
    try:
        frames = collect_report_frames(con, run_id=RUN_ID)
        payload = report_run(con, tmp_path, run_id=RUN_ID)
    finally:
        con.close()

    curve = _rows(_table(_section(payload, "analysis"), "geometry_threshold_map"))
    class_map = {row["threshold_id"]: row["corpus_search_class_id"] for row in frames.threshold_class_map}
    class_values = {
        (row["corpus_search_class_id"], row["ruler"], row["metric"], row["k"]): row["value"]
        for row in frames.class_aggregate_metrics
    }
    baseline_values = {
        (row["ruler"], row["metric"], row["k"]): row["value"] for row in frames.baseline_aggregate_metrics
    }

    assert curve
    for row in curve:
        assert row["corpus_search_class_id"] == class_map[row["threshold_id"]]
        expected_class = class_values[(row["corpus_search_class_id"], row["ruler"], row["metric"], int(row["k"]))]
        expected_baseline = baseline_values[(row["ruler"], row["metric"], int(row["k"]))]
        assert float(row["class_value"]) == pytest.approx(expected_class)
        assert float(row["baseline_value"]) == pytest.approx(expected_baseline)
        assert float(row["delta"]) == pytest.approx(expected_class - expected_baseline)


def test_neighborhood_uniqueness_is_class_scoped(monkeypatch, tmp_path):
    from scripts.embedding_research.report import run as report_run

    con = _two_threshold_con(monkeypatch)
    try:
        frames = collect_report_frames(con, run_id=RUN_ID)
        payload = report_run(con, tmp_path, run_id=RUN_ID)
    finally:
        con.close()

    rendered = _rows(_table(_section(payload, "winners"), "geometry_representations"))
    assert rendered
    keys = [(row["corpus_search_class_id"], row["query_song_id"], row["candidate_song_id"]) for row in rendered]
    assert len(keys) == len(set(keys)) == len(class_neighborhood_rows(frames))

    # The same (query, candidate) pair is retained under each owning class, never collapsed.
    pairs_by_class: dict[tuple[str, str], set[str]] = {}
    for class_id, query, candidate in keys:
        pairs_by_class.setdefault((query, candidate), set()).add(class_id)
    assert any(len(class_ids) >= 2 for class_ids in pairs_by_class.values())
