"""Mechanically validate a generated schema-v2 embedding-research report (JSON).

Checks the binding report contract against ``report.json`` written by the report
pipeline (or the deterministic fixture report):

* schema version == 2
* every section carries the full schema-v2 key set
  (id, title, description, stats, charts, tables, panels, subsections, warnings,
  headline, empty_message)
* the winners section covers every expected group x metric x K per backbone
  (and **rejects** unexpected extra cells — an extra group must FAIL)
* the primary backbone/dimension contract holds: the DEFAULT fixture's winner_delta
  backbones are exactly ``["effnet"]``; MusicNN is allowed only under the explicit
  ``--explicit-musicnn-ctp`` mode (imported here from ``report/_winners.py``)
* every winner row parses to the FULL ``WINNER_DELTA_COLUMNS`` set (the absolute,
  canonical set imported from ``report/_winners.py``); any table missing ANY canonical
  column — or carrying an extra non-canonical column — is a clean FAIL, never an
  unhandled ``KeyError``
* every winner row's baseline key is the explicit ``global_pool:{backbone}:medoid``
  for the same backbone
* every configured PTC (bin_mode, threshold) appears across the winner rows (per-threshold
  non-collapse; no hidden averaging across threshold/configuration dimensions)
* trace-summary fields are present and finite on winner rows (``trace_finite`` truthy,
  every numeric trace field finite)
* the winners section uses evaluation-lens wording (MAP/MRR/NDCG/Recall/discrimination
  are lenses, not optimization objectives)
* every `factor_summary_{bb}` table matches the `FACTOR_SUMMARY_COLUMNS` shape
  (also imported from `report/_winners.py`), has a non-zero row count, and non-empty factor values
* corpus hashes are present and consistent across compared rows per backbone
* the shared-boundary head-phase section is present with ``boundary_source="effnet_ptc"``
  provenance and a ``reference_corpus_hash`` consistent with the effnet corpus hash
* no CTP primary row (no winner row with ``winner_strategy_type == "ctp"`` and no
  ``ctp:`` winner strategy key) and no ``disc_album`` anywhere
* no hidden ``config="flat"`` replacement remains

Prints one line per check with PASS/FAIL and exits non-zero on any failure.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

# Make the repository-root ``scripts`` package importable when run as a standalone script
# (mirrors generate_fixture_report.py / run.py).  Harmless under pytest, where the rootdir
# already provides the ``scripts`` package.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.embedding_research.config import REPORT_DIR
from scripts.embedding_research.report._winners import (
    FACTOR_SUMMARY_COLUMNS,
    TRACE_SUMMARY_COLUMNS,
    WINNER_DELTA_COLUMNS,
)

_REPORT_JSON = REPORT_DIR / "report.json"

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

# The DEFAULT primary backbone set (follow-on contract).  MusicNN is allowed only under
# the explicit ``--explicit-musicnn-ctp`` mode.
DEFAULT_BACKBONES = ["effnet"]
EXPLICIT_BACKBONES = ["effnet", "musicnn"]

# Configured PTC (bin_mode, threshold) boundary configurations.  Every one of these must
# appear across the winner rows (each threshold its own config; no hidden averaging).
CONFIGURED_PTC: set[tuple[str, float]] = {
    ("temporal_global", 1.0),
    ("temporal_global", 1.1),
    ("temporal_perdim", 1.0),
    ("temporal_perdim", 1.1),
}

# Shared-boundary head-phase provenance constants (see db/head_phase.py).
EXPECTED_BOUNDARY_SOURCE = "effnet_ptc"
EXPECTED_HEAD_POOL_VARIANT = "shared_effnet_ptc_boundary"

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


def _parse_rows(table: dict) -> list[dict]:
    """Zip a make_table table's rows (lists) back to dicts keyed by its columns."""
    cols = list(table.get("columns", []))
    return [dict(zip(cols, r, strict=False)) for r in table.get("rows", [])]


def _check_trace_finiteness(wd_tables: dict[str, dict]) -> None:
    """Every winner_delta row must carry finite trace-summary fields.

    ``trace_finite`` must be truthy (not '—' and not '0.0000'); every other trace field
    must parse to a finite float.  A missing/None/finite trace field is a clean FAIL.
    """
    for t_id, table in wd_tables.items():
        cols = list(table.get("columns", []))
        present_trace = [c for c in TRACE_SUMMARY_COLUMNS if c in cols]
        bad_finite: list[str] = []
        bad_missing: list[str] = []
        for row in _parse_rows(table):
            for col in present_trace:
                val = row.get(col)
                if val in (None, "—"):
                    if col == "trace_finite":
                        bad_missing.append(f"{col}=None")
                    else:
                        bad_missing.append(f"{col}=—")
                    continue
                try:
                    fv = float(val)
                except (TypeError, ValueError):
                    bad_finite.append(f"{col}={val!r}")
                    continue
                if not math.isfinite(fv):
                    bad_finite.append(f"{col}={val!r}")
                if col == "trace_finite" and fv == 0.0:
                    bad_finite.append("trace_finite=0 (falsy)")
        _check(
            f"winner_delta trace fields present + finite ({t_id})",
            not bad_finite and not bad_missing,
            "; ".join((bad_missing + bad_finite)[:6])
            if (bad_finite or bad_missing)
            else f"all {len(present_trace)} trace field(s) finite + trace_finite truthy",
        )


def _check_per_threshold_configs(wd_tables: dict[str, dict]) -> None:
    """Every configured (bin_mode, threshold) must appear across the winner rows.

    Collects the (bin_mode, threshold) identity from PTC winner rows per backbone and
    requires the full CONFIGURED_PTC set to be present.  Also rejects any PTC winner row
    whose bin_mode/threshold is None (a hidden collapse would hide a config).
    """
    for t_id, table in wd_tables.items():
        cols = list(table.get("columns", []))
        if "winner_bin_mode" not in cols or "winner_threshold" not in cols:
            _check(
                f"winner_delta carries threshold identity columns ({t_id})",
                False,
                "missing winner_bin_mode/winner_threshold columns",
            )
            continue
        seen: set[tuple[str, float]] = set()
        collapsed: list[str] = []
        for row in _parse_rows(table):
            if row.get("winner_strategy_type") != "ptc":
                continue
            bm = row.get("winner_bin_mode")
            th = row.get("winner_threshold")
            if bm in (None, "—") or th in (None, "—"):
                collapsed.append(str(row.get("winner_strategy_key")))
                continue
            try:
                seen.add((str(bm), float(th)))
            except (TypeError, ValueError):
                collapsed.append(f"{bm}:{th}")
        missing = sorted(f"{bm}:{th:g}" for bm, th in (CONFIGURED_PTC - seen))
        _check(
            f"winner_delta per-threshold configs non-collapsed ({t_id})",
            not missing and not collapsed,
            f"missing config(s) {missing}; collapsed {collapsed[:4]}"
            if (missing or collapsed)
            else f"{len(seen)}/{len(CONFIGURED_PTC)} configured (bin_mode, threshold) present",
        )


def _check_no_ctp_primary(wd_tables: dict[str, dict]) -> None:
    """No CTP primary winner row anywhere: no strategy_type ctp, no ctp: strategy key."""
    offenders: list[str] = []
    for t_id, table in wd_tables.items():
        for row in _parse_rows(table):
            st = row.get("winner_strategy_type")
            key = row.get("winner_strategy_key")
            if st == "ctp" or (isinstance(key, str) and key.startswith("ctp:")):
                offenders.append(f"{t_id}:{st}:{key}")
    _check(
        "no CTP primary winner rows",
        not offenders,
        "; ".join(offenders[:5]) if offenders else "no ctp strategy_type/key in any winner_delta table",
    )


def _check_head_phase(sections: list[dict], effnet_hash: str | None) -> None:
    """Shared-boundary head-phase section: present, effnet_ptc provenance, hash-consistent."""
    section = next((s for s in sections if s.get("id") == "head-output-shared-ptc-boundary"), None)
    _check(
        "head-output-shared-ptc-boundary section present",
        section is not None,
        "no section with id=head-output-shared-ptc-boundary" if section is None else "found",
    )
    if section is None:
        return
    _check(
        "head-output-shared-ptc-boundary section populated",
        not section.get("empty_message"),
        "empty_message set (no provenance rows)" if section.get("empty_message") else "rendered with provenance",
    )
    tables = {t["id"]: t for t in _collect_tables(section)}
    prov = tables.get("head_phase_provenance")
    _check(
        "head_phase_provenance table present",
        prov is not None,
        "no head_phase_provenance table in section" if prov is None else "found",
    )
    if prov is None:
        return
    cols = list(prov.get("columns", []))
    for needed in ("boundary_source", "head_pool_variant", "reference_corpus_hash", "n_songs", "n_pooled"):
        if needed not in cols:
            _check(f"head_phase_provenance carries {needed} column", False, f"missing {needed}")
    rows = _parse_rows(prov)
    _check(
        "head_phase_provenance has rows",
        len(rows) > 0,
        f"{len(rows)} row(s)",
    )
    if not rows:
        return
    bad_boundary = [r for r in rows if r.get("boundary_source") != EXPECTED_BOUNDARY_SOURCE]
    bad_variant = [r for r in rows if r.get("head_pool_variant") != EXPECTED_HEAD_POOL_VARIANT]
    # Coverage sanity: n_pooled <= n_songs when both numeric.
    bad_cov: list[str] = []
    for r in rows:
        ns, np_ = r.get("n_songs"), r.get("n_pooled")
        if isinstance(ns, str) and ns.isdigit() and isinstance(np_, str) and np_.isdigit() and int(np_) > int(ns):
            bad_cov.append(f"{r.get('head')}:{r.get('bin_mode')}:{r.get('threshold')} n_pooled={np_}>n_songs={ns}")
    _check(
        "head_phase_provenance boundary_source=effnet_ptc",
        not bad_boundary,
        f"bad boundary_source: {[r['boundary_source'] for r in bad_boundary][:5]}"
        if bad_boundary
        else "all rows effnet_ptc",
    )
    _check(
        "head_phase_provenance head_pool_variant=shared_effnet_ptc_boundary",
        not bad_variant,
        f"bad head_pool_variant: {[r['head_pool_variant'] for r in bad_variant][:5]}"
        if bad_variant
        else "all rows shared_effnet_ptc_boundary",
    )
    _check(
        "head_phase_provenance n_pooled <= n_songs",
        not bad_cov,
        "; ".join(bad_cov[:5]) if bad_cov else "coverage consistent",
    )
    hashes = {r.get("reference_corpus_hash") for r in rows if r.get("reference_corpus_hash") not in (None, "—")}
    _check(
        "head_phase_provenance reference_corpus_hash consistent with effnet corpus",
        effnet_hash is not None and hashes == {effnet_hash},
        f"hashes={sorted(hashes)} effnet={effnet_hash}"
        if (effnet_hash is None or hashes != {effnet_hash})
        else f"all rows reference the effnet corpus hash {effnet_hash}",
    )


def main(path: str | Path | None = None, *, explicit: bool | None = None) -> int:
    global _failures
    _failures = []  # reset per run so repeated main() calls in one process stay isolated
    # Optional explicit mode: allows MusicNN in addition to effnet.  Used to validate the
    # explicit opt-in fixture (generator --include-musicnn-ctp).  CTP is still rejected as
    # a primary winner in both modes.  When not passed, the CLI flag --explicit-musicnn-ctp
    # enables it (so callers may also pass a positional report path).
    if explicit is None:
        explicit = "--explicit-musicnn-ctp" in sys.argv[1:]

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
        expected_backbones = sorted(EXPLICIT_BACKBONES) if explicit else sorted(DEFAULT_BACKBONES)
        _check(
            "winner_delta tables per backbone",
            backbones == expected_backbones,
            str(backbones),
        )
        _check(
            "factor_summary tables per backbone",
            sorted(fs_tables) == sorted(f"factor_summary_{b}" for b in backbones),
            str(sorted(fs_tables)),
        )

        # Winner-delta columns: enforce the ABSOLUTE canonical WINNER_DELTA_COLUMNS set on
        # EVERY winner_delta table.  The schema-v2 serializer does NOT drop all-None
        # columns — make_table keeps rows[0].keys() and DataFrame construction forces all
        # 33 canonical columns — so any table missing ANY canonical column (or carrying an
        # extra non-canonical column) is a clean FAIL, never an unhandled KeyError.
        canonical_wd = set(WINNER_DELTA_COLUMNS)
        for t_id, table in wd_tables.items():
            colset = set(table.get("columns", []))
            non_canonical = sorted(colset - canonical_wd)
            missing = sorted(canonical_wd - colset)
            _check(
                f"winner_delta rows carry the full canonical column set ({t_id})",
                not non_canonical and not missing,
                f"non-canonical={non_canonical} missing={missing}"
                if (non_canonical or missing)
                else f"all {len(canonical_wd)} canonical winner column(s) present, none extra",
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

        # Per-threshold non-collapse + trace finiteness + no CTP primary rows
        _check_per_threshold_configs(wd_tables)
        _check_trace_finiteness(wd_tables)
        _check_no_ctp_primary(wd_tables)

        # Evaluation-lens wording in the winners section description
        desc = winners.get("description", "")
        _check(
            "winners section uses evaluation-lens wording",
            "evaluation lens" in desc,
            "description does not label MAP/MRR/NDCG/Recall/discrimination as evaluation lenses"
            if "evaluation lens" not in desc
            else "MAP/MRR/NDCG/Recall/discrimination labelled as evaluation lenses, not objectives",
        )

        # Shared-boundary head-phase provenance, consistent with the effnet corpus hash
        effnet_hash = next(iter(corpus_hashes.get("effnet", set())), None)
        _check_head_phase(sections, effnet_hash)

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
