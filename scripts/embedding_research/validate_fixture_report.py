"""Schema-v2 fixture-report validator.

Retargets the old 16-section / legacy-winner validator to the schema-v2 contract: a
generated fixture ``report.json`` (see :mod:`generate_fixture_report`) must expose EXACTLY
the seven sections ``summary`` / ``corpus`` / ``analysis`` / ``winners`` /
``head-analysis`` / ``provenance`` / ``efficiency``, render only *active* catalog
(``strategy_type='catalog'``) analysis rows, keep the EffNet and MusicNN backbone
populations separate, carry deterministic winner/delta/factor tables, sorted alias ids,
finite values, the synthetic-fixture warning/limitations, and zero forbidden legacy
vocabulary.

:func:`validate_fixture_report` returns ``None`` on success and raises
:class:`ValueError` describing the first contract violation otherwise.
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Ensure the research tree is importable whether this runs under pytest (repo root on
# sys.path) or as ``python -m scripts.embedding_research.validate_fixture_report`` / a
# standalone ``python scripts/embedding_research/validate_fixture_report.py`` invocation
# (mirrors the bootstrap in :mod:`generate_fixture_report`).
_PKG_DIR = Path(__file__).resolve().parent
_ROOT = _PKG_DIR.parents[1]  # repo root (parent of scripts/)
for _p in (_ROOT, _PKG_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Exact seven-section id order (schema-v2 report contract).
EXACT_SECTION_IDS: tuple[str, ...] = (
    "summary",
    "corpus",
    "analysis",
    "winners",
    "head-analysis",
    "provenance",
    "efficiency",
)

#: Backbone populations the full fixture must carry as separate analysis/winners groups.
EXPECTED_BACKBONES: tuple[str, ...] = ("effnet", "musicnn")

#: Forbidden legacy vocabulary that must never appear in the emitted fixture report.
#: ``global_pool`` is intentionally absent: the observed ``global_pool:{backbone}:medoid``
#: baseline strategy key is a legitimate winner-section value under the medoid-baseline
#: contract (aligned with tests/_report_seed.py::FORBIDDEN_REPORT_VOCABULARY).
FORBIDDEN_REPORT_VOCABULARY: tuple[str, ...] = (
    "ptc",
    "ctp",
    "binned",
    "truncation",
    "optimizer",
    "weighted",
    "rep_a",
    "rep_b",
    "calibration",
)

#: Message of the synthetic-fixture warning the generator must attach.
SYNTHETIC_WARNING_MESSAGE = "SYNTHETIC FIXTURE — no empirical retrieval claim."

#: The eight EXACT active CLI phase names (run.CLI_PHASES) permitted on report phase
#: surfaces.  The validator requires exactly this vocabulary for the executed pipeline and
#: rejects any obsolete phase name (``stratify``/``segment``/``classify``/standalone ``head``)
#: in phase position.
EXACT_PHASE_NAMES: tuple[str, ...] = (
    "ingest",
    "embed",
    "infer-heads",
    "catalog",
    "catalog-report",
    "analyze",
    "head-analysis",
    "report",
)

#: Maintenance verbs additionally permitted on a phase surface where the generator records
#: them (verify/reindex/cleanup/reset).  The in-memory fixture generator records only the
#: eight executed CLI phases, so a compliant current fixture carries exactly EXACT_PHASE_NAMES;
#: the maintenance names are an allow-list so a fixture that records maintenance provenance is
#: still valid rather than spuriously rejected.
MAINTENANCE_PHASE_NAMES: tuple[str, ...] = ("verify", "reindex", "cleanup", "reset")

#: Every phase name that may legally appear on a report phase surface.
ALLOWED_PHASE_NAMES: tuple[str, ...] = EXACT_PHASE_NAMES + MAINTENANCE_PHASE_NAMES

#: Obsolete phase names that must never appear on a report phase surface (retired command
#: verbs).  ``head`` is intentionally NOT here (``head-analysis`` is a legitimate current phase
#: name); a standalone ``head`` phase value is excluded by the exact-vocabulary assertion.
OBSOLETE_PHASE_NAMES: tuple[str, ...] = ("stratify", "segment", "classify")

#: Em-dash sentinel report cells use for a ``None`` / absent identity (a baseline has no
#: config identity; an alias-free class has no alias ids).
_NONE_CELL = "—"

_NON_FINITE_RE = re.compile(r"^[-+]?inf(?:inity)?$|^nan$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Walkers
# ---------------------------------------------------------------------------


def _iter_leaf_strings(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for value in node.values():
            yield from _iter_leaf_strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_leaf_strings(item)
    elif isinstance(node, str):
        yield node


def _iter_leaf_numbers(node: Any) -> Iterator[float]:
    if isinstance(node, dict):
        for value in node.values():
            yield from _iter_leaf_numbers(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_leaf_numbers(item)
    elif isinstance(node, bool):
        return
    elif isinstance(node, (int, float)):
        yield float(node)


def _find_section(sections: list[dict], section_id: str) -> dict | None:
    for section in sections:
        if section.get("id") == section_id:
            return section
    return None


def _find_table(owner: dict, table_id: str) -> dict | None:
    """Locate *table_id* at section level or inside any subsection/panel."""
    for table in owner.get("tables", []):
        if table.get("id") == table_id:
            return table
    for sub in owner.get("subsections", []):
        found = _find_table(sub, table_id)
        if found is not None:
            return found
    for panel in owner.get("panels", []):
        for table in panel.get("tables", []):
            if table.get("id") == table_id:
                return table
        for sub in panel.get("subsections", []):
            found = _find_table(sub, table_id)
            if found is not None:
                return found
    return None


def _subsection_titles(section: dict) -> list[str]:
    return [sub.get("title", "") for sub in section.get("subsections", [])]


def _cell(table: dict, row, column: str):
    """Return the *row* cell under *column* (None when the column is absent)."""
    if column in table.get("columns", []):
        return row[table["columns"].index(column)]
    return None


def _is_none_cell(value) -> bool:
    """True when *value* renders an absent/None identity (em-dash, empty, or None)."""
    return value is None or value == _NONE_CELL or value == ""


def _finite_cell(value) -> bool:
    """Whether a report cell is finite — non-numeric labels are tolerated, only NaN/Inf flags."""
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, str):
        s = value.strip()
        if not s or s in ("True", "False", _NONE_CELL):
            return True
        try:
            return math.isfinite(float(s))
        except ValueError:
            return True  # a non-numeric label cell, not a number
    return True


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


def _check(problems: list[str], ok: bool, message: str) -> None:
    if not ok:
        problems.append(message)


def validate_fixture_report(path: str | Path) -> None:
    """Validate a schema-v2 fixture ``report.json``; raise ValueError on any violation."""
    report_path = Path(path)
    if not report_path.is_file():
        raise ValueError(f"fixture report not found: {report_path}")

    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise ValueError(f"fixture report is not valid JSON: {exc}") from exc

    problems: list[str] = []

    # ── top-level contract ─────────────────────────────────────────────────────────
    _check(problems, data.get("schema_version") == 2, f"schema_version must be 2, got {data.get('schema_version')!r}")
    _check(problems, isinstance(data.get("title"), str) and data["title"], "title must be a non-empty string")
    _check(problems, isinstance(data.get("run_ts"), str) and data["run_ts"], "run_ts must be a non-empty string")

    # ── forbidden legacy vocabulary anywhere (keys, titles, cells, warnings) ──────
    text = json.dumps(data, default=str).lower()
    emitted = [tok for tok in FORBIDDEN_REPORT_VOCABULARY if tok.lower() in text]
    _check(problems, not emitted, f"forbidden legacy vocabulary emitted: {sorted(emitted)}")

    # ── finiteness (no NaN / ±Inf in any leaf number or formatted string) ─────────
    for value in _iter_leaf_numbers(data):
        _check(problems, math.isfinite(value), f"non-finite numeric value in report: {value!r}")
        if not math.isfinite(value):
            break
    bad_strings = [s for s in _iter_leaf_strings(data) if _NON_FINITE_RE.match(s)]
    _check(problems, not bad_strings, f"non-finite literal strings in report: {bad_strings}")

    # ── exact seven sections, in order ─────────────────────────────────────────────
    sections = data.get("sections")
    _check(problems, isinstance(sections, list), "sections must be a list")
    if not isinstance(sections, list):
        raise ValueError("fixture report has no sections list: " + "; ".join(problems))
    section_ids = [s.get("id") for s in sections]
    _check(
        problems,
        section_ids == list(EXACT_SECTION_IDS),
        f"section ids/order mismatch: got {section_ids}, want {list(EXACT_SECTION_IDS)}",
    )

    # ── synthetic-fixture warning present ──────────────────────────────────────────
    messages = [w.get("message", "") for w in data.get("warnings", []) if isinstance(w, dict)]
    _check(
        problems,
        SYNTHETIC_WARNING_MESSAGE in messages,
        "synthetic-fixture / no-empirical-retrieval-claim warning missing from report.warnings",
    )

    # ── human HTML output present alongside the machine JSON (report.html sibling) ─────
    html_path = report_path.with_name("report.html")
    _check(
        problems,
        html_path.is_file() and html_path.stat().st_size > 0,
        f"human HTML output missing or empty beside the machine JSON: {html_path}",
    )

    summary = _find_section(sections, "summary")
    corpus = _find_section(sections, "corpus")
    analysis = _find_section(sections, "analysis")
    winners = _find_section(sections, "winners")
    head_analysis = _find_section(sections, "head-analysis")
    provenance = _find_section(sections, "provenance")
    efficiency = _find_section(sections, "efficiency")

    # ── summary: active catalog status per backbone ────────────────────────────────
    status = _find_table(summary, "catalog_result_status") if summary else None
    _check(
        problems,
        status is not None and not status.get("empty"),
        "summary must render the non-empty catalog_result_status table",
    )
    if status is not None and not status.get("empty"):
        cols = status.get("columns", [])
        _check(problems, "backbone" in cols, "catalog_result_status must carry a backbone column")
        present_backbones = {row[cols.index("backbone")] for row in status.get("rows", [])}
        _check(
            problems,
            present_backbones == set(EXPECTED_BACKBONES),
            f"summary backbone rows mismatch: {sorted(present_backbones)}, want {list(EXPECTED_BACKBONES)}",
        )

    # ── corpus: active songs / health ──────────────────────────────────────────────
    _check(problems, corpus is not None and not corpus.get("empty_message"), "corpus section must be populated")
    if corpus is not None:
        songs_stat = next((st for st in corpus.get("stats", []) if st.get("label") == "songs"), None)
        _check(
            problems,
            songs_stat is not None and int(songs_stat.get("value", 0)) > 0,
            "corpus must report a positive active song count",
        )

    # ── analysis: catalog-only, per-backbone, aliases collapsed ───────────────────
    _check(problems, analysis is not None, "analysis section missing")
    if analysis is not None:
        titles = _subsection_titles(analysis)
        for backbone in EXPECTED_BACKBONES:
            _check(problems, backbone in titles, f"analysis missing {backbone} subsection; got {titles}")
            table = _find_table(analysis, f"catalog_analysis_{backbone}")
            _check(
                problems,
                table is not None and not table.get("empty"),
                f"analysis missing non-empty catalog_analysis_{backbone} table",
            )
            if table is not None and not table.get("empty"):
                scol = table["columns"].index("strategy_key") if "strategy_key" in table["columns"] else -1
                if scol >= 0:
                    keys = [row[scol] for row in table.get("rows", [])]
                    _check(
                        problems,
                        all(k.startswith("catalog:") for k in keys),
                        f"analysis {backbone} table has non-catalog strategy rows: {[k for k in keys if not k.startswith('catalog:')]}",
                    )
        # Alias collapse: the effnet 'aa' class (canonical 1 + alias 5) must appear exactly
        # once per (K, metric) cell — 2 K values x 2 metrics = 4 rows, NOT alias-multiplied.
        effnet = _find_table(analysis, "catalog_analysis_effnet")
        if effnet is not None and not effnet.get("empty"):
            scol = effnet["columns"].index("strategy_key")
            aa_count = sum(1 for row in effnet.get("rows", []) if row[scol].endswith(":aa"))
            _check(problems, aa_count == 4, f"alias 'aa' not collapsed (expected 4 rows, got {aa_count})")

        # ── durable identity / equivalence fields the analysis surface exposes ────────
        # Every per-backbone analysis table must carry the durable per-class identities:
        # the canonical config id, its sorted alias ids (collapsed classes counted once),
        # the representation (equivalence) hash, and the materialized view content hash.
        for backbone in EXPECTED_BACKBONES:
            table = _find_table(analysis, f"catalog_analysis_{backbone}")
            if table is not None and not table.get("empty"):
                cols = table.get("columns", [])
                for identity_col in (
                    "canonical_config_id",
                    "alias_ids",
                    "representation_hash",
                    "view_content_hash",
                ):
                    _check(
                        problems,
                        identity_col in cols,
                        f"catalog_analysis_{backbone} missing durable identity column {identity_col}",
                    )
                if all(c in cols for c in ("strategy_key", "canonical_config_id", "representation_hash")):
                    # Durable equivalence identity: every row of one strategy_key (class) must
                    # share the same canonical config id and representation hash across K/metric.
                    seen: dict[str, tuple] = {}
                    for row in table.get("rows", []):
                        key = row[cols.index("strategy_key")]
                        ident = (row[cols.index("canonical_config_id")], row[cols.index("representation_hash")])
                        _check(
                            problems,
                            key not in seen or seen[key] == ident,
                            f"catalog_analysis_{backbone} class {key!r} carries inconsistent identity {ident} vs {seen.get(key)}",
                        )
                        seen[key] = ident
                    for key, (config_id, rep_hash) in seen.items():
                        _check(
                            problems,
                            not _is_none_cell(config_id) and bool(rep_hash),
                            f"catalog_analysis_{backbone} class {key!r} missing canonical_config_id/representation_hash",
                        )

    # ── winners: deterministic winner/delta/factor tables per backbone ─────────────
    _check(problems, winners is not None, "winners section missing")
    if winners is not None:
        titles = _subsection_titles(winners)
        for backbone in EXPECTED_BACKBONES:
            _check(problems, backbone in titles, f"winners missing {backbone} subsection; got {titles}")
            delta = _find_table(winners, f"winner_delta_{backbone}")
            factors = _find_table(winners, f"factor_classes_{backbone}")
            _check(
                problems,
                delta is not None and not delta.get("empty"),
                f"winners missing non-empty winner_delta_{backbone} table",
            )
            _check(
                problems,
                factors is not None and not factors.get("empty"),
                f"winners missing non-empty factor_classes_{backbone} table",
            )
            if factors is not None and not factors.get("empty"):
                fcols = factors.get("columns", [])
                for identity_col in ("canonical_config_id", "alias_ids", "representation_hash"):
                    _check(
                        problems,
                        identity_col in fcols,
                        f"factor_classes_{backbone} missing durable identity column {identity_col}",
                    )
            # ── baseline / delta fields (observed-medoid contract) ──────────────────────
            # The baseline for every cell is the observed global medoid for this backbone
            # (``global_pool:{backbone}:medoid``); it is never a config class, so it carries
            # baseline_canonical_config_id = None and never wins.  Delta rows must be finite.
            if delta is not None and not delta.get("empty"):
                dcols = delta.get("columns", [])
                for field in (
                    "n_classes",
                    "baseline_strategy_key",
                    "baseline_canonical_config_id",
                    "baseline_value",
                    "delta",
                ):
                    _check(
                        problems,
                        field in dcols,
                        f"winner_delta_{backbone} missing field column {field}",
                    )
                if all(
                    c in dcols
                    for c in (
                        "baseline_strategy_key",
                        "baseline_canonical_config_id",
                        "delta",
                        "winner_canonical_config_id",
                    )
                ):
                    bsk = dcols.index("baseline_strategy_key")
                    bcid = dcols.index("baseline_canonical_config_id")
                    wcid = dcols.index("winner_canonical_config_id")
                    delta_i = dcols.index("delta")
                    for row in delta.get("rows", []):
                        _check(
                            problems,
                            row[bsk] == f"global_pool:{backbone}:medoid",
                            f"winner_delta_{backbone} baseline identity {row[bsk]!r} != global_pool:{backbone}:medoid",
                        )
                        _check(
                            problems,
                            _is_none_cell(row[bcid]),
                            f"winner_delta_{backbone} baseline carries a config id {row[bcid]!r} (must be None)",
                        )
                        _check(
                            problems,
                            not _is_none_cell(row[wcid]) and _finite_cell(row[delta_i]),
                            f"winner_delta_{backbone} missing finite delta/winner for baseline {row[bsk]!r}",
                        )

    # ── head-analysis: canonical provenance (catalog / shared_catalog_boundary) ───
    _check(problems, head_analysis is not None, "head-analysis section missing")
    if head_analysis is not None:
        table = _find_table(head_analysis, "head_phase_provenance_effnet")
        _check(
            problems,
            table is not None and not table.get("empty"),
            "head-analysis must render the non-empty canonical effnet provenance table",
        )
        if table is not None and not table.get("empty"):
            cols = table.get("columns", [])
            for required in ("boundary_source", "head_pool_variant", "status", "finite", "coverage"):
                _check(problems, required in cols, f"head_phase_provenance_effnet missing column {required}")
            # Canonical head rows over committed masks carry finite coverage/pooling values.
            for numeric_col in ("n_songs", "n_pooled", "coverage", "threshold_effective"):
                _check(
                    problems,
                    numeric_col in cols,
                    f"head_phase_provenance_effnet missing head field column {numeric_col}",
                )
                if numeric_col in cols:
                    idx = cols.index(numeric_col)
                    _check(
                        problems,
                        all(_finite_cell(r[idx]) for r in table.get("rows", [])),
                        f"head_phase_provenance_effnet carries non-finite {numeric_col} value",
                    )
            bs = cols.index("boundary_source") if "boundary_source" in cols else -1
            hpv = cols.index("head_pool_variant") if "head_pool_variant" in cols else -1
            if bs >= 0:
                _check(
                    problems,
                    all(r[bs] == "catalog" for r in table.get("rows", [])),
                    "head provenance rows must carry boundary_source='catalog'",
                )
            if hpv >= 0:
                _check(
                    problems,
                    all(r[hpv] == "shared_catalog_boundary" for r in table.get("rows", [])),
                    "head provenance rows must carry head_pool_variant='shared_catalog_boundary'",
                )

    # ── provenance: active run history + artifact hashes ──────────────────────────
    _check(problems, provenance is not None, "provenance section missing")
    if provenance is not None:
        history = _find_table(provenance, "run_history")
        _check(
            problems,
            history is not None and len(history.get("rows", [])) > 0,
            "provenance must render a populated run_history table",
        )
        # ── exactly the eight CLI phase names (+ optional maintenance verbs) appear ──
        # Report phase surfaces are: run_history.phase and artifact_hashes.phase rows, plus the
        # phase-named timing_history columns in the efficiency section.  Every surfaced phase
        # must be in the allowed vocabulary (the eight exact CLI phases, or a maintenance verb
        # recorded where the generator records one); the executed set must be exactly the eight
        # phases, and no obsolete phase name may surface.
        phase_surfaces: list[str] = []
        if history is not None and not history.get("empty") and "phase" in history.get("columns", []):
            hcols = history["columns"]
            phase_surfaces += [r[hcols.index("phase")] for r in history.get("rows", [])]
        artifact_hashes = _find_table(provenance, "artifact_hashes")
        if (
            artifact_hashes is not None
            and not artifact_hashes.get("empty")
            and "phase" in artifact_hashes.get("columns", [])
        ):
            acols = artifact_hashes["columns"]
            phase_surfaces += [r[acols.index("phase")] for r in artifact_hashes.get("rows", [])]
        phase_surfaces = [p for p in phase_surfaces if p not in (None, _NONE_CELL, "")]
        surfaced = set(phase_surfaces)
        _check(
            problems,
            surfaced <= set(ALLOWED_PHASE_NAMES),
            f"obsolete/unexpected phase name on a report phase surface: {sorted(surfaced - set(ALLOWED_PHASE_NAMES))}",
        )
        _check(
            problems,
            surfaced >= set(EXACT_PHASE_NAMES),
            f"not all eight CLI phase names recorded in provenance: missing {sorted(set(EXACT_PHASE_NAMES) - surfaced)}",
        )
        _check(
            problems,
            not (surfaced & set(OBSOLETE_PHASE_NAMES)),
            f"obsolete phase name(s) emitted: {sorted(surfaced & set(OBSOLETE_PHASE_NAMES))}",
        )
        # Run provenance rows carry finite (integer-ms) started_at/finished_at timings.
        if history is not None and not history.get("empty"):
            hcols = history.get("columns", [])
            for ts_col in ("started_at", "finished_at"):
                if ts_col in hcols:
                    ts_i = hcols.index(ts_col)
                    _check(
                        problems,
                        all(_finite_cell(r[ts_i]) for r in history.get("rows", [])),
                        f"run_history carries non-finite {ts_col} value",
                    )

    # ── efficiency: retained phase timings history ────────────────────────────────
    _check(problems, efficiency is not None, "efficiency section missing")
    if efficiency is not None:
        history = _find_table(efficiency, "timing_history")
        _check(
            problems,
            history is not None and len(history.get("rows", [])) > 0,
            "efficiency must render the retained timing_history table",
        )
        # Every phase-named timing column is one of the eight exact CLI phases (no obsolete
        # phase vocabulary in the timing pivot).
        if history is not None and not history.get("empty"):
            timed_phases = [c for c in history.get("columns", []) if c != "run"]
            _check(
                problems,
                set(timed_phases) <= set(EXACT_PHASE_NAMES),
                f"timing_history carries non-pipeline/obsolete phase column(s): {sorted(set(timed_phases) - set(EXACT_PHASE_NAMES))}",
            )
            _check(
                problems,
                all(_finite_cell(v) for row in history.get("rows", []) for v in row[1:]),
                "timing_history carries a non-finite elapsed value",
            )

    if problems:
        raise ValueError("fixture report violates the schema-v2 contract:\n  - " + "\n  - ".join(problems))


def main(path: str | None = None) -> int:  # pragma: no cover - manual CLI
    """CLI wrapper: validates *path* (default REPORT_DIR/report.json); exit 0/1."""
    import argparse

    from scripts.embedding_research.config import REPORT_DIR

    parser = argparse.ArgumentParser(description="Validate a schema-v2 fixture report.json")
    parser.add_argument(
        "path",
        nargs="?",
        default=str(REPORT_DIR / "report.json"),
        help="Path to the report.json to validate (default: fixture report).",
    )
    args = parser.parse_args((path and [path]) or None)
    try:
        validate_fixture_report(args.path)
    except ValueError as exc:
        print(f"FAIL: {exc}")
        return 1
    print(f"OK: {args.path} satisfies the schema-v2 fixture-report contract.")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
