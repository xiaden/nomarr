"""Durable, report-readable NON-METRIC diagnostics for non-comparable geometry analysis.

Research-only.  The explicit ``analyze_incomplete_diagnostics`` table (see
``db/_schema._INCOMPLETE_DIAGNOSTIC_COLUMN_DEFS``) carries one versioned diagnostic for a
geometry representation the analyze phase could NOT score completely (it lost an eligible
whole-song observation, so it is ``not comparable``).  That representation must NEVER become an
``analyze_metrics`` row — its only durable evidence is this diagnostic, keyed by the complete
eleven-field geometry identity.

Writer contract (``write_incomplete_analyze_diagnostic``):

* Persists ONLY after that backbone's MANDATORY observed ``global_pool:{backbone}:medoid``
  baseline succeeds (the producer never calls it on the refusal path — fail closed).
* Refuses (raises) a COMPARABLE result: a complete representation is never recorded as an
  incomplete diagnostic.
* Application-scoped replacement by ``(run_id, geometry_id, evaluation_id, sim_metric)`` — no
  PK/UNIQUE on the table (DuckDB ART/WAL policy) — so a re-run of the same scope replaces only
  its own diagnostic and never touches unrelated runs.
* Never calls ``write_analyze_metrics`` / the geometry corpus writer.

Reader contract (``read_incomplete_analyze_diagnostics``) returns the raw column rows, optionally
restricted to one run_id.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from scripts.embedding_research.db._schema import _INCOMPLETE_DIAGNOSTIC_COLUMN_DEFS

if TYPE_CHECKING:
    from collections.abc import Mapping

#: ``analyze_incomplete_diagnostics`` column names, in DDL order (single source of truth:
#: derived from the schema definitions so the writer/reader never drift from the DDL).
incomplete_diagnostic_columns: tuple[str, ...] = tuple(
    line.split(None, 1)[0].strip() for line in _INCOMPLETE_DIAGNOSTIC_COLUMN_DEFS
)

#: Current diagnostic schema version (bumped only on a breaking field/semantics change).
DIAGNOSTIC_VERSION: int = 1

#: A non-comparable (skipped) representation's diagnostic status.
STATUS_INCOMPLETE: str = "incomplete"

#: The geometry corpus pass scores under ``sim_metric = "geometry"``.
ANALYZE_SIM_METRIC: str = "geometry"

#: The eleven exact geometry identity fields, in canonical order.
_GEOMETRY_IDENTITY_FIELDS: tuple[str, ...] = (
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

_TABLE = "analyze_incomplete_diagnostics"


class DiagnosticError(RuntimeError):
    """A diagnostic could not be written (e.g. a comparable result or missing table)."""


def _now_ms() -> int:
    return int(time.time() * 1000)


def _table_exists(con) -> bool:
    row = con.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", [_TABLE]).fetchone()
    return bool(row and row[0])


def _dumps(value: Any) -> str:
    """Deterministic canonical JSON (sorted keys, compact separators) for TEXT evidence columns."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _identity_values(identity: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field in _GEOMETRY_IDENTITY_FIELDS:
        value = identity.get(field, "")
        if field == "scoring_semantics_version":
            try:
                values[field] = int(value)
            except (TypeError, ValueError) as exc:
                raise DiagnosticError("scoring_semantics_version must be an integer") from exc
        else:
            text = str(value or "")
            if not text:
                raise DiagnosticError(f"geometry identity field {field!r} is required")
            values[field] = text
    return values


def write_incomplete_analyze_diagnostic(
    con,
    *,
    run_id: str,
    identity: Mapping[str, Any],
    reason: str,
    baseline_corpus: Any = None,
    backbone: str = "",
    experiment: str = "",
    sim_metric: str = ANALYZE_SIM_METRIC,
    k: int = 0,
    evaluation_corpus: Any = None,
    missing_song_ids: Any = (),
    missing_count: int = 0,
    missing_digest: str | None = None,
    comparable: bool = False,
) -> None:
    """Durably persist one non-comparable geometry representation diagnostic.

    *identity* carries the complete eleven-field geometry identity (``run_id`` supplied
    separately).  A comparable result is refused (fail closed).  This writes the diagnostic
    ONLY — it never emits ``analyze_metrics`` rows.
    """
    if not _table_exists(con):
        raise DiagnosticError(
            "analyze_incomplete_diagnostics table is absent; run ensure_schema() before writing a diagnostic"
        )
    if comparable:
        raise DiagnosticError(
            "write_incomplete_analyze_diagnostic refuses a COMPARABLE result: a complete "
            "representation is never recorded as an incomplete diagnostic"
        )
    run_id = str(run_id)
    if not run_id:
        raise DiagnosticError("run_id is required")

    ids = _identity_values(identity)
    missing_ids = tuple(sorted(str(s) for s in (missing_song_ids or ())))
    evaluation = evaluation_corpus
    baseline_hash = str(getattr(baseline_corpus, "corpus_hash", "") or "")
    baseline_count = int(getattr(baseline_corpus, "count", 0) or 0)
    baseline_comparable = bool(getattr(baseline_corpus, "comparable", True))

    row = {
        "run_id": run_id,
        **ids,
        "sim_metric": str(sim_metric),
        "k": int(k),
        "experiment": str(experiment),
        "diagnostic_version": DIAGNOSTIC_VERSION,
        "status": STATUS_INCOMPLETE,
        "reason": str(reason),
        "metric": "",
        "evaluation_corpus_hash": str(getattr(evaluation, "corpus_hash", "") or ""),
        "evaluation_corpus_count": int(getattr(evaluation, "count", 0) or 0),
        "evaluation_corpus_comparable": False,
        "missing_song_ids_json": _dumps(missing_ids),
        "missing_count": int(missing_count) if missing_count else len(missing_ids),
        "missing_digest": missing_digest or None,
        "baseline_strategy_key": f"global_pool:{backbone}:medoid",
        "baseline_evaluation_corpus_hash": baseline_hash,
        "baseline_evaluation_corpus_count": baseline_count,
        "baseline_evaluation_corpus_comparable": baseline_comparable,
        "created_at": _now_ms(),
    }

    con.execute(
        f"DELETE FROM {_TABLE} WHERE run_id = ? AND geometry_id = ? AND evaluation_id = ? AND sim_metric = ?",
        [run_id, ids["geometry_id"], ids["evaluation_id"], str(sim_metric)],
    )
    cols = incomplete_diagnostic_columns
    con.execute(
        f"INSERT INTO {_TABLE} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        [row[c] for c in cols],
    )


def read_incomplete_analyze_diagnostics(
    con,
    *,
    run_id: str | None = None,
) -> list[dict]:
    """Return every persisted diagnostic row as a dict (optionally for one *run_id*)."""
    if not _table_exists(con):
        return []
    cols = incomplete_diagnostic_columns
    if run_id is not None:
        rows = con.execute(
            f"SELECT {', '.join(cols)} FROM {_TABLE} WHERE run_id = ? ORDER BY geometry_id, evaluation_id, sim_metric",
            [str(run_id)],
        ).fetchall()
    else:
        rows = con.execute(
            f"SELECT {', '.join(cols)} FROM {_TABLE} ORDER BY run_id, geometry_id, evaluation_id, sim_metric"
        ).fetchall()
    return [dict(zip(cols, r, strict=False)) for r in rows]


__all__ = [
    "ANALYZE_SIM_METRIC",
    "DIAGNOSTIC_VERSION",
    "STATUS_INCOMPLETE",
    "DiagnosticError",
    "incomplete_diagnostic_columns",
    "read_incomplete_analyze_diagnostics",
    "write_incomplete_analyze_diagnostic",
]
