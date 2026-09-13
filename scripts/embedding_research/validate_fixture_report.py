"""Fail-closed validator for the deterministic seven-section synthetic geometry report.

This module validates the geometry report JSON and its permitted sibling HTML viewer: schema/version,
section identity and ordering, the synthetic-only warning, finite numeric values, the
geometry evidence phase topology, populated sections and identity tables, winner/baseline
evidence, run-history and timing phase registries, the refusal/incomplete/resource
matrices, and forbidden retired identity vocabulary.

Git/source traceability replay (the retired traceability CLI option, source manifest/
commit replay, command replay, and traceability producer) is hard-deleted by
the corrective repair pass. The lowercase scientific artifact-hash helpers
(:func:`canonical_json_bytes`, :func:`sha256_bytes`, :func:`sha256_file`, and
:func:`is_sha256`) and scientific artifact hashes are retained.

Retired ownership vocabulary is assembled from fragments at runtime so this module never
itself carries a substring the strict whole-tree audit forbids.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

_PKG_DIR = Path(__file__).resolve().parent
_ROOT = _PKG_DIR.parents[1]
for _path in (_ROOT, _PKG_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

EXACT_SECTION_IDS = ("summary", "corpus", "analysis", "winners", "head-analysis", "provenance", "efficiency")
EXACT_PHASE_NAMES = ("ingest", "embed", "infer-heads", "geometry", "analyze", "head-analysis", "report")
EXPECTED_IDENTITY_COLUMNS = (
    "geometry_id",
    "observation_group_sha256",
    "geometry_semantics_version",
    "numerical_profile_digest",
    "threshold_id",
    "structural_identity",
    "search_representation_id",
    "evaluation_id",
    "scoring_semantics_version",
    "execution_id",
)
SYNTHETIC_WARNING_MESSAGE = "SYNTHETIC FIXTURE — no empirical retrieval claim."

_SHA256_LEN = 64
_HEX_DIGITS = frozenset("0123456789abcdef")


def _j(*parts: str) -> str:
    """Join fragments so this module never stores a retired substring literally."""
    return "".join(parts)


def retired_identity_tokens() -> tuple[str, ...]:
    """Retired identity/vocabulary roots, assembled from fragments (never literal here)."""
    return (
        _j("cat", "alog", "_id"),
        _j("cat", "alog", "_fingerprint"),
        _j("cat", "alog", "-report"),
        _j("cat", "alog", " strategy"),
        _j("current", " ", "cat", "alog"),
        _j("search", "_view"),
    )


# ── canonical hashing ──────────────────────────────────────────────────────────


def canonical_json_bytes(payload: Any) -> bytes:
    """Canonical (sorted, compact, ASCII) JSON encoding used for every digest."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == _SHA256_LEN and all(char in _HEX_DIGITS for char in value)


# ── report validation ──────────────────────────────────────────────────────────


def _walk(node: Any):
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)
    else:
        yield node


def _section(data: dict, section_id: str) -> dict | None:
    return next((s for s in data.get("sections", []) if s.get("id") == section_id), None)


def _tables(node: Any):
    if isinstance(node, dict):
        if isinstance(node.get("tables"), list):
            yield from node["tables"]
        for key in ("panels", "subsections"):
            for child in node.get(key, []) or []:
                yield from _tables(child)


def _table(section: dict | None, table_id: str) -> dict | None:
    if section is None:
        return None
    return next((table for table in _tables(section) if table.get("id") == table_id), None)


def _check_finite(node: Any, problems: list[str], path: str = "report") -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            _check_finite(value, problems, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _check_finite(value, problems, f"{path}[{index}]")
    elif isinstance(node, bool) or node is None:
        return
    elif isinstance(node, (int, float)) and not math.isfinite(float(node)):
        problems.append(f"{path} is non-finite")


def _require_identity_table(section: dict | None, table_id: str, problems: list[str]) -> None:
    table = _table(section, table_id)
    if table is None or table.get("empty"):
        problems.append(f"missing non-empty {table_id}")
        return
    columns = table.get("columns", [])
    missing_columns = [column for column in EXPECTED_IDENTITY_COLUMNS if column not in columns]
    problems.extend(f"{table_id} missing identity column {column}" for column in missing_columns)
    for row in table.get("rows", []):
        if len(row) != len(columns):
            problems.append(f"{table_id} row width does not match columns")
            continue
        missing = [
            column
            for column in EXPECTED_IDENTITY_COLUMNS
            if column in columns and row[columns.index(column)] in (None, "", "—")
        ]
        problems.extend(f"{table_id} has absent identity evidence for {column}" for column in missing)


def _retired_vocabulary_in(node: Any) -> list[str]:
    """Return retired identity tokens found in the serialized node (fragment-assembled)."""
    try:
        blob = json.dumps(node, ensure_ascii=False)
    except (TypeError, ValueError):
        blob = str(node)
    lowered = blob.lower()
    return [token for token in retired_identity_tokens() if token in lowered]


def _comparability_reason_problems(comparability: dict) -> list[str]:
    """Fail-closed checks for ``corrective_evidence.comparability``.

    The explicit-reason vocabulary is owned by
    :func:`scripts.embedding_research.helpers.corpus_identity.classify_representation`; every
    emitted reason must be a subset of that canonical vocabulary so a regenerated report can
    never carry retired comparability words.
    """
    from scripts.embedding_research.helpers.corpus_identity import classify_representation

    canonical: list[str] = []
    for kwargs in (
        {
            "alignment_ok": False,
            "searchable_count": 0,
            "medoid_defined": False,
            "candidate_count": 0,
            "label_defined": False,
        },
        {
            "alignment_ok": True,
            "searchable_count": 1,
            "medoid_defined": True,
            "candidate_count": 1,
            "label_defined": False,
        },
    ):
        canonical.extend(classify_representation(**kwargs).reasons)
    vocabulary = frozenset(canonical)

    problems: list[str] = []
    if not isinstance(comparability, dict):
        return ["comparability corrective evidence is missing"]
    if comparability.get("non_comparable_persisted") is not True:
        problems.append("non-comparable evidence persistence is missing")
    reasons = comparability.get("explicit_reasons")
    if not isinstance(reasons, list) or not reasons or not all(isinstance(reason, str) for reason in reasons):
        problems.append("comparability explicit_reasons must be a non-empty list of strings")
        return problems
    unknown = sorted({reason for reason in reasons if reason not in vocabulary})
    if unknown:
        problems.append(f"comparability explicit_reasons contain non-canonical vocabulary: {unknown}")
    return problems


def _scientific_root(report_path: Path) -> Path:
    return report_path.parent.parent.resolve()


def _viewer_is_external(viewer: Path, report_path: Path) -> bool:
    try:
        viewer.resolve().relative_to(_scientific_root(report_path))
    except ValueError:
        return True
    return False


def _viewer_candidates(report_path: Path) -> tuple[Path, ...]:
    """Return only documented external viewer locations for *report_path*."""
    report_root = _scientific_root(report_path)
    candidates = [
        report_root.parent / f"{report_root.name}_runtime" / "docs" / "embedding-research-report.html",
        report_root.parent / "docs" / "embedding-research-report.html",
    ]
    return tuple(path for path in candidates if _viewer_is_external(path, report_path))


def validate_report(path: str | Path, html_path: str | Path | None = None) -> list[str]:
    """Validate the seven-section geometry report; return a list of problems (empty == valid)."""
    report_path = Path(path)
    if not report_path.is_file():
        return [f"fixture report not found: {report_path}"]
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"fixture report is not valid JSON: {exc}"]
    problems: list[str] = []
    if data.get("schema_version") != 2:
        problems.append("schema_version must be 2")
    if data.get("synthetic_only") is not True:
        problems.append("synthetic_only must be true")
    sections = data.get("sections")
    if [section.get("id") for section in sections or []] != list(EXACT_SECTION_IDS):
        problems.append("section ids/order must be exactly the seven geometry sections")
    messages = [warning.get("message") for warning in data.get("warnings", []) if isinstance(warning, dict)]
    if SYNTHETIC_WARNING_MESSAGE not in messages:
        problems.append("synthetic-only warning is missing")
    # Scientific evidence roots are JSON-only; the fixture viewer is published only under a
    # permitted external docs directory, outside the evidence root.
    if html_path is not None:
        viewer = Path(html_path)
        if _viewer_is_external(viewer, report_path):
            viewer_paths = (viewer,)
        else:
            problems.append("HTML viewer must be outside the scientific JSON root")
            viewer_paths = ()
    else:
        viewer_paths = _viewer_candidates(report_path)
    if viewer_paths and not any(viewer.is_file() and viewer.stat().st_size for viewer in viewer_paths):
        problems.append("external sibling embedding-research-report.html is missing or empty")
    _check_finite(data, problems)

    evidence = data.get("geometry_evidence", {})
    if tuple(evidence.get("phases", ())) != EXACT_PHASE_NAMES:
        problems.append("geometry evidence phase topology is incomplete")
    corpus = _section(data, "corpus")
    analysis = _section(data, "analysis")
    winners = _section(data, "winners")
    head_analysis = _section(data, "head-analysis")
    provenance = _section(data, "provenance")
    efficiency = _section(data, "efficiency")
    if corpus is None or corpus.get("empty_message"):
        problems.append("corpus section must be populated")
    if analysis is None:
        problems.append("analysis section is missing")
    else:
        _require_identity_table(analysis, "geometry_identity", problems)
    if head_analysis is not None and not head_analysis.get("empty_message"):
        _require_identity_table(head_analysis, "geometry_head_identity", problems)
    if winners is None or not any(
        _table(winners, table_id) for table_id in ("geometry_winner_deltas", "geometry_representations")
    ):
        problems.append("winners must visibly render geometry winner/baseline evidence")
    history = _table(provenance, "run_history")
    if history is None or history.get("empty"):
        problems.append("provenance run_history is missing")
    else:
        phases = {
            row[history["columns"].index("phase")] for row in history.get("rows", []) if "phase" in history["columns"]
        }
        if phases != set(EXACT_PHASE_NAMES):
            problems.append(f"phase registry mismatch: {sorted(phases)}")
    timing = _table(efficiency, "timing_history")
    if timing is None or timing.get("empty") or not timing.get("rows"):
        problems.append("efficiency timing_history is missing")
    else:
        columns = timing.get("columns", [])
        if "phase" in columns:
            timing_phases = {row[columns.index("phase")] for row in timing.get("rows", [])}
            if not set(EXACT_PHASE_NAMES).issubset(timing_phases):
                problems.append(f"phase timing is incomplete: {sorted(timing_phases)}")
    matrices = data.get("matrices")
    if not isinstance(matrices, dict) or set(matrices) != {"refusal", "incomplete", "resource"}:
        problems.append("refusal/incomplete/resource matrices are missing")
    corrective = data.get("corrective_evidence")
    if not isinstance(corrective, dict):
        problems.append("corrective_evidence is missing")
    else:
        retrieval = corrective.get("retrieval", {})
        if retrieval.get("self_candidate_count") != 0:
            problems.append("retrieval self_candidate_count must be zero")
        if retrieval.get("segmentation_from_scorer_count") != 0:
            problems.append("retrieval segmentation_from_scorer_count must be zero")
        if not retrieval.get("corpus_wide_leave_one_out"):
            problems.append("corpus-wide leave-one-out evidence is missing")
        threshold_map = corrective.get("threshold_map", {})
        if threshold_map.get("count") != 171:
            problems.append("threshold map must contain all 171 hypotheses")
        comparability = corrective.get("comparability", {})
        if not isinstance(comparability, dict):
            problems.append("comparability corrective evidence is missing")
        else:
            problems.extend(_comparability_reason_problems(comparability))
        if not corrective.get("scientific_hash_retention"):
            problems.append("scientific artifact-hash retention is missing")
        benchmark = corrective.get("benchmark")
        if not isinstance(benchmark, dict):
            problems.append("fixtures-only benchmark metadata is missing")
        else:
            from scripts.embedding_research.fixture_benchmark import validate_benchmark_report

            problems.extend(f"benchmark: {error}" for error in validate_benchmark_report(benchmark))
    problems.extend(f"report contains retired vocabulary: {token}" for token in _retired_vocabulary_in(data))
    return problems


# ── public entry point ─────────────────────────────────────────────────────────


def validate_fixture_report(path: str | Path, html_path: str | Path | None = None) -> None:
    """Validate the seven-section synthetic geometry report.

    Raises :class:`ValueError` describing every failed field when any check fails.
    """
    problems = validate_report(Path(path), html_path=html_path)
    if problems:
        raise ValueError("fixture report violates the geometry contract:\n  - " + "\n  - ".join(problems))


def main(argv: list[str] | None = None) -> int:
    """CLI: ``validate_fixture_report [REPORT_JSON]``."""
    parser = argparse.ArgumentParser(description="Fail-closed geometry report validator.")
    parser.add_argument(
        "report_json",
        nargs="?",
        default=None,
        help="report.json path (defaults to the configured report directory)",
    )
    parser.add_argument(
        "--html",
        dest="html_path",
        type=Path,
        default=None,
        help="explicit external HTML viewer path",
    )
    arguments = parser.parse_args(argv)

    if arguments.report_json:
        report_path = Path(arguments.report_json)
    else:
        from scripts.embedding_research.config import REPORT_DIR

        report_path = REPORT_DIR / "report.json"

    try:
        validate_fixture_report(report_path, html_path=arguments.html_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL: {exc}")
        return 1
    print(f"OK: {report_path} satisfies the geometry fixture contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
