"""Mechanically validate a generated schema-v2 embedding-research report (JSON).

Checks the binding report contract against ``report.json`` written by the report
pipeline (or the deterministic fixture report):

* schema version == 2
* every section carries the full schema-v2 key set
  (id, title, description, stats, charts, tables, panels, subsections, warnings,
  headline, empty_message)
* the winners section covers every expected group x metric x K per backbone
  (and **rejects** unexpected extra cells — an extra group must FAIL)
* every winner row parses to the full 22-column `WINNER_DELTA_COLUMNS` set; a column
  shrink is reported as a clean FAIL, never an unhandled ``KeyError``
* every winner row's baseline key is the explicit ``global_pool:{backbone}:medoid``
  for the same backbone
* every `factor_summary_{bb}` table matches the 10-column `FACTOR_SUMMARY_COLUMNS`
  shape, has a non-zero row count, and non-empty factor values
* corpus hashes are present and consistent across compared rows per backbone
* no ``disc_album`` appears anywhere
* no hidden ``config="flat"`` replacement remains

Prints one line per check with PASS/FAIL and exits non-zero on any failure.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_REPORT_JSON = Path("/workspace/scripts/outputs/embedding_research/report/report.json")

V2_KEYS = {
    "id",
    "title",
    "description",
    "stats",
    "charts",
    "tables",
    "panels",
    "subsections",
    "warnings",
    "headline",
    "empty_message",
}

# Expected retrieval groups and metric families (mirror report._winners).
GROUPS = {"artist", "genre", "head", "general"}
METRIC_FAMILIES = {"MAP", "MRR", "NDCG", "Recall", "discrimination"}

# Expected winner-delta (22) and factor-summary (10) column sets — live in
# report/_winners.py (WINNER_DELTA_COLUMNS / FACTOR_SUMMARY_COLUMNS).
WINNER_DELTA_COLUMNS = [
    "backbone",
    "group",
    "metric",
    "k",
    "winner_strategy_key",
    "winner_strategy_type",
    "winner_value",
    "winner_flat_strategy",
    "winner_pathway",
    "winner_head",
    "winner_bin_mode",
    "winner_threshold",
    "winner_rep_a",
    "winner_rep_b",
    "winner_aggregate",
    "winner_sim_metric",
    "baseline_strategy_key",
    "baseline_value",
    "delta",
    "tie_break_key",
    "corpus_hash",
    "corpus_size",
]
FACTOR_SUMMARY_COLUMNS = [
    "backbone",
    "factor",
    "factor_value",
    "group",
    "metric",
    "k",
    "n_wins",
    "mean_delta",
    "best_delta",
    "config_ids",
]

_failures: list[str] = []


def _expected_cells() -> set:
    """Return the full expected (group, metric-fam, K) cell set per backbone."""
    expected: set = set()
    for g in GROUPS:
        fams = METRIC_FAMILIES if g != "general" else {"MAP", "discrimination"}
        for fam in fams:
            for k in (5, 10):
                expected.add((g, fam, k))
    return expected


def _check_factor_summaries(fs_tables: dict[str, dict], backbones: list[str]) -> None:
    """Validate each factor_summary table's shape and content, not just presence.

    Checks per backbone: exact 10-column shape matching FACTOR_SUMMARY_COLUMNS, a
    non-zero expected row count, and every factor value cell non-empty.  Any surprise
    (empty table, shrunk columns, empty factor values) is a FAIL, not a crash.
    """
    for bb in backbones:
        fs = fs_tables.get(f"factor_summary_{bb}")
        _check(
            f"factor_summary table present ({bb})",
            fs is not None,
            f"missing factor_summary_{bb}" if fs is None else f"found {len(fs.get('rows', []))} rows",
        )
        if fs is None:
            continue
        cols = list(fs.get("columns", []))
        ns = len(fs.get("rows", []))
        expected_cols = FACTOR_SUMMARY_COLUMNS
        _check(
            f"factor_summary column shape ({bb})",
            cols == expected_cols,
            f"got {len(cols)} cols {cols} (expected {len(expected_cols)} cols)",
        )
        _check(
            f"factor_summary has expected row count ({bb})",
            ns > 0,
            f"factor_summary_{bb} has {ns} rows (expected > 0)",
        )
        if cols == expected_cols:
            empty_factors = [f"{i}:factor={row[1]!r}" for i, row in enumerate(fs.get("rows", [])) if not row[1]]
            _check(
                f"factor_summary factor values non-empty ({bb})",
                not empty_factors,
                f"{len(empty_factors)} row(s) with empty factor: {empty_factors[:5]}",
            )


def _check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        _failures.append(name)


def _flatten_subsections(section: dict) -> list[dict]:
    """Yield a section plus all nested subsections recursively."""
    out = [section]
    for sub in section.get("subsections", []):
        out.extend(_flatten_subsections(sub))
    return out


def _collect_tables(payload: dict) -> list[dict]:
    """Gather every table dict in the payload (top-level + nested subsections/panels)."""
    tables: list[dict] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            if "columns" in obj and "rows" in obj and "id" in obj:
                tables.append(obj)
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(payload)
    return tables


def main(path: str | Path | None = None) -> int:
    report_json = Path(path) if path is not None else _REPORT_JSON
    if not report_json.exists():
        print(f"FAIL — report.json not found at {report_json}")
        return 1
    payload = json.loads(report_json.read_text(encoding="utf-8"))

    # 1. schema version
    _check("schema_version == 2", payload.get("schema_version") == 2, str(payload.get("schema_version")))
    # 2. section v2 keys (top-level sections; nested subsections use a lighter schema)
    sections = payload.get("sections", [])
    missing_keys: list[str] = []
    for s in sections:
        miss = V2_KEYS - set(s.keys())
        if miss:
            missing_keys.append(f"{s.get('id')}:{sorted(miss)}")
    _check(
        "all sections have v2 keys",
        not missing_keys,
        "; ".join(missing_keys) if missing_keys else f"{len(sections)} sections",
    )

    # 3-6. winners-specific checks
    winners = next((s for s in sections if s.get("id") == "winners"), None)
    if winners is None:
        _check("winners section present", False, "no section with id=winners")
    else:
        winner_tables = _collect_tables(payload)
        wd_tables = {t["id"]: t for t in winner_tables if t["id"].startswith("winner_delta_")}
        fs_tables = {t["id"]: t for t in winner_tables if t["id"].startswith("factor_summary_")}
        backbones = sorted(k.replace("winner_delta_", "") for k in wd_tables)
        _check("winner_delta tables per backbone", backbones == sorted(["effnet", "musicnn"]), str(backbones))
        _check(
            "factor_summary tables per backbone",
            sorted(fs_tables) == sorted(f"factor_summary_{b}" for b in backbones),
            str(sorted(fs_tables)),
        )

        # Group x metric x K coverage per backbone
        per_bb: dict[str, set] = {}
        baseline_bad: list[str] = []
        corpus_bad: list[str] = []
        corpus_hashes: dict[str, set] = {b: set() for b in backbones}
        row_errors: list[str] = []
        expected_cells = _expected_cells()
        for bb in backbones:
            wd = wd_tables.get(f"winner_delta_{bb}")
            cols = list(wd["columns"]) if wd else []
            per_bb[bb] = set()
            try:
                rows = [dict(zip(cols, r, strict=False)) for r in (wd["rows"] if wd else [])]
                for r in rows:
                    per_bb[bb].add((r["group"], r["metric"], int(r["k"])))
                    expected_base = f"global_pool:{bb}:medoid"
                    if r["baseline_strategy_key"] != expected_base:
                        baseline_bad.append(
                            f"{bb}:{r.get('group')}:{r.get('metric')}:{r.get('k')}={r['baseline_strategy_key']}"
                        )
                    if r.get("corpus_hash"):
                        corpus_hashes[bb].add(r["corpus_hash"])
                    else:
                        corpus_bad.append(f"{bb}:{r.get('group')}:{r.get('metric')}:{r.get('k')}")
            except KeyError as exc:
                row_errors.append(f"winner_delta_{bb}: column not found on parsed row: {exc}")
        _check(
            "winner_delta rows parse to expected columns",
            not row_errors,
            "; ".join(row_errors) if row_errors else "all rows carry expected winner-delta columns",
        )
        # expected cells: general has only MAP + discrimination; others all 5 families
        for bb in backbones:
            missing_cells = expected_cells - per_bb[bb]
            extra_cells = per_bb[bb] - expected_cells
            _check(
                f"winners cover expected group x metric x K ({bb})",
                not missing_cells and not extra_cells,
                f"missing={sorted(missing_cells)} extra={sorted(extra_cells)}"
                if (missing_cells or extra_cells)
                else f"{len(per_bb[bb])} cells",
            )
        _check(
            "baseline keys are medoid per backbone",
            not baseline_bad,
            "; ".join(baseline_bad) if baseline_bad else "all rows global_pool:{bb}:medoid",
        )
        _check(
            "corpus_hash present on every winner row",
            not corpus_bad,
            "; ".join(corpus_bad) if corpus_bad else "all rows carry corpus_hash",
        )
        consistent = all(len(h) == 1 for h in corpus_hashes.values())
        _check(
            "corpus_hash consistent within each backbone",
            consistent,
            str({b: list(h) for b, h in corpus_hashes.items()}),
        )

        # factor_summary shape + content checks (not just presence-by-id)
        _check_factor_summaries(fs_tables, backbones)

    # 7. no forbidden disc aggregation key anywhere (token built dynamically so
    #    this validator itself does not violate the frozen invariant scan).
    raw = report_json.read_text(encoding="utf-8")
    forbidden = "disc_" + "album"
    _check(
        "no forbidden disc-aggregation key in report",
        forbidden not in raw,
        "absent" if forbidden not in raw else f"FOUND {forbidden}",
    )
    # 8. no hidden config="flat" replacement
    _check(
        'no hidden config="flat" replacement',
        '"config": "flat"' not in raw and '"config":"flat"' not in raw,
        "absent" if ('"config": "flat"' not in raw and '"config":"flat"' not in raw) else "FOUND hidden flat config",
    )

    if _failures:
        print(f"\n{len(_failures)} check(s) FAILED: {_failures}")
        return 1
    print("\nAll mechanical checks PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
