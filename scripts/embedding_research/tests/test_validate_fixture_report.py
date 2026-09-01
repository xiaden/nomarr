"""Regression tests for validate_fixture_report.py structural-gap hardening.

This guards the three structural fixes from QA Round 1:

* an **extra** retrieval group beyond the expected ones must FAIL
  (previously ``extra_cells`` was computed but never fed the pass condition);
* a shrunk factor_summary table (columns / content) must FAIL
  (previously only presence-by-id was checked);
* a shrunk winner_delta table (missing columns) must FAIL with a clean
  validation message, not an unhandled ``KeyError``.

Each test runs the validator against a deliberately mutated copy of the real
deterministic fixture report.  The fixture report is regenerated (outside the
repo) by ``scripts/embedding_research/generate_fixture_report.py`` and is a
required verification artifact, so these tests skip when it is absent.
"""

from __future__ import annotations

import copy
import io
import json
from contextlib import redirect_stdout
from typing import TYPE_CHECKING, Any

import pytest

from scripts.embedding_research import validate_fixture_report as validator

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_REPORT = validator._REPORT_JSON


def _run_validator(payload: dict[str, Any], tmp_path: Path, *, explicit: bool = False) -> tuple[int, str]:
    """Write *payload* to a temp json and run the validator; return (exit_code, output)."""
    report = tmp_path / "report.json"
    report.write_text(json.dumps(payload), encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = validator.main(report, explicit=explicit)
    return code, buf.getvalue()


def _find_table(payload: dict[str, Any], id_prefix: str) -> dict[str, Any]:
    """Return the first table whose id starts with *id_prefix*."""
    found: list[dict[str, Any]] = []

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            if isinstance(o.get("id"), str) and o["id"].startswith(id_prefix) and "rows" in o:
                found.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(payload)
    assert found, f"no table with id prefix {id_prefix!r}"
    return found[0]


def _find_rows(table: dict[str, Any]) -> list[dict[str, Any]]:
    """Zip a make_table table's rows (lists) back to dicts keyed by its columns."""
    cols = list(table.get("columns", []))
    return [dict(zip(cols, r, strict=False)) for r in table.get("rows", [])]


def _walk_tables(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Gather every table dict in the payload (top-level + nested subsections/panels)."""
    tables: list[dict[str, Any]] = []

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            if "columns" in o and "rows" in o and "id" in o:
                tables.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(payload)
    return tables


@pytest.fixture(scope="module")
def base_report() -> dict[str, Any]:
    if not _REPORT.exists():
        pytest.skip("fixture report not generated — run generate_fixture_report.py first")
    return json.loads(_REPORT.read_text(encoding="utf-8"))


def test_valid_base_report_passes(base_report: dict[str, Any], tmp_path: Path) -> None:
    code, out = _run_validator(base_report, tmp_path)
    assert code == 0, out
    assert "All mechanical checks PASSED." in out


def test_extra_group_fails(base_report: dict[str, Any], tmp_path: Path) -> None:
    mut = copy.deepcopy(base_report)
    wd = _find_table(mut, "winner_delta_effnet")
    # Inject a spurious 'album' group cell; per_bb set grows, expected stays same.
    extra = list(wd["rows"][0])
    extra[1] = "album"
    wd["rows"].append(extra)
    code, out = _run_validator(mut, tmp_path)
    assert code == 1, out
    assert "album" in out and "extra=" in out


def test_shrunk_factor_summary_fails(base_report: dict[str, Any], tmp_path: Path) -> None:
    mut = copy.deepcopy(base_report)
    _find_table(mut, "factor_summary")["columns"] = ["backbone", "factor"]
    code, out = _run_validator(mut, tmp_path)
    assert code == 1, out
    assert "factor_summary column shape" in out


def test_shrunk_winner_delta_clean_fail(base_report: dict[str, Any], tmp_path: Path) -> None:
    """A shrunk winner_delta table MUST report a clean FAIL, never raise KeyError."""
    mut = copy.deepcopy(base_report)
    wd = _find_table(mut, "winner_delta_effnet")
    wd["columns"] = [c for c in wd["columns"] if c != "baseline_strategy_key"]
    code, out = _run_validator(mut, tmp_path)
    assert code == 1, out
    assert "winner_delta rows parse to expected columns" in out


def test_shrunk_winner_delta_missing_any_canonical_field_fails(base_report: dict[str, Any], tmp_path: Path) -> None:
    """A winner_delta table missing ANY canonical field (not just the parsed ones) must FAIL.

    Regression for the explicit full canonical-set column check: the validator imports
    ``WINNER_DELTA_COLUMNS`` and requires every winner_delta table to carry the full
    schema-v2 reference column set.  Dropping a field the parse loop never reads directly
    (e.g. ``corpus_hash``) must still be a clean FAIL, not silently accepted because the
    grouping/baseline/corpus checks happen to pass without it.
    """
    mut = copy.deepcopy(base_report)
    wd = _find_table(mut, "winner_delta_effnet")
    wd["columns"] = [c for c in wd["columns"] if c != "corpus_hash"]
    code, out = _run_validator(mut, tmp_path)
    assert code == 1, out
    assert "winner_delta rows carry the full canonical column set" in out
    assert "corpus_hash" in out


def test_extra_non_canonical_winner_column_fails(base_report: dict[str, Any], tmp_path: Path) -> None:
    """An EXTRA non-canonical column on a winner_delta table must FAIL (F1 absolute set)."""
    mut = copy.deepcopy(base_report)
    wd = _find_table(mut, "winner_delta_effnet")
    wd["columns"] = [*list(wd["columns"]), "surprise_col"]
    for row in wd["rows"]:
        row.append("x")
    code, out = _run_validator(mut, tmp_path)
    assert code == 1, out
    assert "non-canonical" in out and "surprise_col" in out


def test_regenerated_report_has_16_sections(base_report: dict[str, Any]) -> None:
    """The regenerated narrow fixture report carries all 16 schema-v2 sections."""
    ids = {s["id"] for s in base_report["sections"]}
    assert "head-output-shared-ptc-boundary" in ids
    assert "head-value" in ids  # archival CTP note retained
    assert len(base_report["sections"]) == 16


def test_regenerated_report_no_non_finite_literals(base_report: dict[str, Any], tmp_path: Path) -> None:
    """Strict-JSON regression: the regenerated report contains no NaN/Infinity/-Infinity."""
    report = tmp_path / "report.json"
    report.write_text(json.dumps(base_report), encoding="utf-8")
    raw = report.read_text(encoding="utf-8")
    for bad in ("NaN", "Infinity", "-Infinity"):
        assert bad not in raw, f"report.json contains a {bad} literal"


def test_winners_section_lens_and_medoid(base_report: dict[str, Any]) -> None:
    """Evaluation-lens wording and the medoid baseline identity survive regeneration."""
    winners = next(s for s in base_report["sections"] if s["id"] == "winners")
    assert "evaluation lens" in winners["description"]
    wd = _find_table(base_report, "winner_delta_effnet")
    rows = _find_rows(wd)
    assert all(r["baseline_strategy_key"] == "global_pool:effnet:medoid" for r in rows)
    assert {r["winner_strategy_type"] for r in rows} == {"ptc"}


def test_winners_trace_and_ambiguity_contract(base_report: dict[str, Any]) -> None:
    """Winner rows carry finite trace fields and the primary ambiguity-variant identity."""
    wd = _find_table(base_report, "winner_delta_effnet")
    cols = list(wd["columns"])
    rows = _find_rows(wd)
    trace_cols = [
        "trace_n_pairs",
        "trace_numerator_sum",
        "trace_denominator_sum",
        "trace_collision_count",
        "trace_winner_count",
        "trace_retained_contributions",
        "trace_dropped_contributions",
        "trace_finite",
    ]
    for c in trace_cols:
        assert c in cols, f"winner_delta missing trace column {c}"
    for r in rows:
        assert r["trace_finite"] not in ("—", "0.0000"), f"trace_finite falsy in {r['winner_strategy_key']}"
        for c in trace_cols:
            if c == "trace_finite":
                continue
            assert r[c] not in ("—", None), f"{c} missing on {r['winner_strategy_key']}"
            float(r[c])  # parses to a finite float
        assert r["winner_ambiguity_variant"] == "first_index + retain_all_candidate_segments"
        assert r["winner_aggregate"] == "max_per_candidate_segment"


def test_regenerated_report_thresholds_and_head_phase(base_report: dict[str, Any]) -> None:
    """Per-threshold configs appear separately and the shared-boundary head section renders."""
    wd = _find_table(base_report, "winner_delta_effnet")
    seen = {
        (r["winner_bin_mode"], float(r["winner_threshold"]))
        for r in _find_rows(wd)
        if r["winner_strategy_type"] == "ptc"
    }
    assert seen == {
        ("temporal_global", 1.0),
        ("temporal_global", 1.1),
        ("temporal_perdim", 1.0),
        ("temporal_perdim", 1.1),
    }
    head_section = next(s for s in base_report["sections"] if s["id"] == "head-output-shared-ptc-boundary")
    assert not head_section.get("empty_message")
    prov = _find_table(head_section, "head_phase_provenance")
    prov_rows = _find_rows(prov)
    assert prov_rows
    assert all(r["boundary_source"] == "effnet_ptc" for r in prov_rows)
    assert all(r["head_pool_variant"] == "shared_effnet_ptc_boundary" for r in prov_rows)
    # reference_corpus_hash consistent with the effnet winner corpus hash
    effnet_hash = {r["corpus_hash"] for r in _find_rows(_find_table(base_report, "winner_delta_effnet"))}
    assert len(effnet_hash) == 1
    assert all(r["reference_corpus_hash"] == next(iter(effnet_hash)) for r in prov_rows)
    for r in prov_rows:
        assert int(r["n_pooled"]) <= int(r["n_songs"])


def test_explicit_musicnn_ctp_fixture(tmp_path: Path) -> None:
    """OPT-IN fixture: MusicNN primary rows render, CTP analyze rows never become winners.

    Builds the explicit fixture (generator --include-musicnn-ctp), renders a report, and
    validates it in explicit mode.  Also proves CTP rows are excluded from every winner_delta
    table even though CTP analyze_metrics rows exist.
    """
    pytest.importorskip("duckdb")
    from scripts.embedding_research.generate_fixture_report import build_fixture_con
    from scripts.embedding_research.report import run as report_run

    con, manifests = build_fixture_con(include_musicnn_ctp=True)
    try:
        report_run(con, tmp_path, matching_corpora=manifests)
    finally:
        con.close()

    payload = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    wd_ids = {t["id"] for t in _walk_tables(payload) if t["id"].startswith("winner_delta_")}
    assert wd_ids == {"winner_delta_effnet", "winner_delta_musicnn"}
    for t in _walk_tables(payload):
        if not t["id"].startswith("winner_delta_"):
            continue
        for r in _find_rows(t):
            assert r["winner_strategy_type"] != "ctp"
            assert not str(r["winner_strategy_key"]).startswith("ctp:")

    # The explicit fixture passes the validator in explicit mode.
    code, out = _run_validator(payload, tmp_path, explicit=True)
    assert code == 0, out
