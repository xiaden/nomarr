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
from pathlib import Path
from typing import Any

import pytest

from scripts.embedding_research import validate_fixture_report as validator

pytestmark = pytest.mark.unit

_REPORT = Path("/workspace/scripts/outputs/embedding_research/report/report.json")


def _run_validator(payload: dict[str, Any], tmp_path: Path) -> tuple[int, str]:
    """Write *payload* to a temp json and run the validator; return (exit_code, output)."""
    report = tmp_path / "report.json"
    report.write_text(json.dumps(payload), encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = validator.main(report)
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
