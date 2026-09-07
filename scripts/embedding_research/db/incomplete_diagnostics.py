"""Durable, report-readable NON-METRIC diagnostics for non-comparable analysis representations.

Research-only.  Execution-reporting Plan B P2 owns one explicit ``analyze_incomplete_diagnostics``
table (see ``db/_schema._INCOMPLETE_DIAGNOSTIC_COLUMN_DEFS``) that carries a versioned diagnostic
for a catalog search-representation class the analyze phase could NOT score completely (it lost an
eligible whole-song song's searchable medoid, so it is ``not comparable``).  That representation
must NEVER become an ``analyze_metrics`` row and NEVER a complete ``analyze_scope_v2`` line — its
only durable evidence is this diagnostic.

Writer contract (``write_incomplete_analyze_diagnostic``):

* Persists ONLY after that backbone's MANDATORY observed ``global_pool:{backbone}:medoid`` baseline
  succeeds (the producer never calls it on the refusal/failure path — fail closed, no orphan rows).
* Refuses (raises) a comparable ``CatalogAnalysisResult``: a complete representation is never
  recorded as an incomplete diagnostic.
* Application-scoped replacement by ``(run_id, strategy_key, sim_metric, k)`` — no PK/UNIQUE on the
  table (DuckDB ART/WAL policy) — so a re-run of the SAME representation scope replaces only its own
  diagnostic and never touches unrelated runs/representations.
* Never calls ``write_analyze_metrics`` / ``write_catalog_analyze_rows`` / ``record_analyze_run_scope``.

Reader contract (``read_incomplete_analyze_diagnostics``) returns the raw column rows, optionally
restricted to one run_id.  The report surface consumes a normalized projection via
``report._retrieval.query_incomplete_analyze_diagnostics``.
"""

from __future__ import annotations

import json
import time
from typing import Any

from scripts.embedding_research.db._schema import _INCOMPLETE_DIAGNOSTIC_COLUMN_DEFS

#: ``analyze_incomplete_diagnostics`` column names, in DDL order (single source of truth:
#: derived from the schema definitions so the writer/reader never drift from the DDL).
incomplete_diagnostic_columns: tuple[str, ...] = tuple(
    line.split(None, 1)[0].strip() for line in _INCOMPLETE_DIAGNOSTIC_COLUMN_DEFS
)

#: Current diagnostic schema version (bumped only on a breaking field/semantics change).
DIAGNOSTIC_VERSION: int = 1

#: A non-comparable (skipped) representation's diagnostic status.
STATUS_INCOMPLETE: str = "incomplete"

#: The analyze catalog pass always scores under ``sim_metric = "cosine"`` (see
#: ``db.analyze_scope.write_catalog_analyze_rows``); diagnostics share that identity so their
#: replacement scope ``(run_id, strategy_key, sim_metric, k)`` matches the class's own identity.
ANALYZE_SIM_METRIC: str = "cosine"

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


def _representation_identity(result: Any) -> tuple[str, int, list[int]]:
    """The durable SEMANTIC class identity for a non-comparable ``CatalogAnalysisResult``.

    Returns ``(search_representation_hash, canonical_config_id, config_ids)``.  The non-comparable
    result does not carry its class scope identity (``_catalog_scope_identity`` runs only on the
    comparable path), so the analyzed class's SEMANTIC hash is recovered from the transient
    per-run ``representation_classes`` collapse (matching ``config_ids``); ``canonical_config_id``
    is the lowest (canonical) member.  Config ids are the tested threshold/member identity and are
    never omitted from the diagnostic.
    """
    config_ids = [int(c) for c in (result.config_ids or ())]
    if config_ids:
        config_ids = sorted({int(c) for c in config_ids})
    canonical = config_ids[0] if config_ids else -1
    hash_val = str(result.search_representation_hash or "")
    if not hash_val:
        for cls in result.representation_classes or ():
            if {int(c) for c in (cls.config_ids or ())} == set(config_ids):
                hash_val = str(cls.search_representation_hash or "")
                break
    return hash_val, canonical, config_ids


def write_incomplete_analyze_diagnostic(
    con,
    *,
    run_id: str,
    result: Any,
    baseline_corpus: Any,
    reason: str,
) -> None:
    """Durably persist one non-comparable representation diagnostic on the research *con*.

    *run_id* is the analyze invocation that produced *result*; *result* is the non-comparable
    :class:`~scripts.embedding_research.common.catalog_analysis.CatalogAnalysisResult` (written ONLY
    after that backbone's MANDATORY observed medoid baseline succeeded); *baseline_corpus* is the
    resolved :class:`~scripts.embedding_research.catalog_identity.EvaluationCorpusIdentity` the
    analyze boundary and the successful baseline shared; *reason* explains the non-comparability.

    Replaces any prior diagnostic for the same ``(run_id, strategy_key, sim_metric, k)`` scope and
    preserves unrelated runs/representations exactly.  A comparable result is refused (fail closed).
    This writes the diagnostic ONLY — it never emits ``analyze_metrics`` rows or a complete scope.
    """
    if not _table_exists(con):
        raise DiagnosticError(
            "analyze_incomplete_diagnostics table is absent; run ensure_schema() before writing a diagnostic"
        )
    if getattr(result, "comparable", True):
        raise DiagnosticError(
            "write_incomplete_analyze_diagnostic refuses a COMPARABLE result: a complete "
            "representation is never recorded as an incomplete diagnostic"
        )
    run_id = str(run_id)
    strategy_key = str(getattr(result, "strategy_key", ""))
    sim_metric = ANALYZE_SIM_METRIC
    k = int(getattr(result, "k", 0))
    backbone = str(getattr(result, "backbone", ""))

    semantic_hash, canonical_id, config_ids = _representation_identity(result)

    evaluation_corpus = getattr(result, "evaluation_corpus", None)
    corpus_hash = str(getattr(evaluation_corpus, "corpus_hash", "") or "")
    corpus_count = int(getattr(evaluation_corpus, "count", 0) or 0)
    missing_song_ids = tuple(sorted(str(s) for s in (getattr(result, "missing_song_ids", ()) or ())))
    missing_count = int(getattr(result, "missing_count", 0) or 0)
    missing_digest = getattr(result, "missing_digest", None) or None

    baseline_hash = str(getattr(baseline_corpus, "corpus_hash", "") or "")
    baseline_count = int(getattr(baseline_corpus, "count", 0) or 0)
    baseline_comparable = bool(getattr(baseline_corpus, "comparable", True))

    members = []
    for cls in getattr(result, "representation_classes", ()) or ():
        if {int(c) for c in (cls.config_ids or ())} == set(config_ids):
            members = [{"config_id": int(c)} for c in cls.config_ids]
            break

    row = {
        "run_id": run_id,
        "strategy_key": strategy_key,
        "sim_metric": sim_metric,
        "k": k,
        "backbone": backbone,
        "experiment": "",
        "diagnostic_version": DIAGNOSTIC_VERSION,
        "status": STATUS_INCOMPLETE,
        "reason": str(reason),
        "metric": "",
        "catalog_id": str(getattr(result, "catalog_id", "") or ""),
        "catalog_fingerprint": str(getattr(result, "catalog_fingerprint", "") or ""),
        "search_representation_hash": semantic_hash,
        "canonical_config_id": canonical_id,
        "config_ids_json": _dumps(config_ids),
        "members_json": _dumps(members),
        "observation_evidence_json": _dumps({}),
        "evaluation_corpus_hash": corpus_hash,
        "evaluation_corpus_count": corpus_count,
        "evaluation_corpus_comparable": False,
        "missing_song_ids_json": _dumps(missing_song_ids),
        "missing_count": missing_count,
        "missing_digest": missing_digest,
        "ruler_status_json": _dumps({}),
        "query_count": int(getattr(result, "n_queries", 0) or 0),
        "baseline_strategy_key": f"global_pool:{backbone}:medoid",
        "baseline_evaluation_corpus_hash": baseline_hash,
        "baseline_evaluation_corpus_count": baseline_count,
        "baseline_evaluation_corpus_comparable": baseline_comparable,
        "created_at": _now_ms(),
    }

    # Application-scoped replacement by the representation scope (no PK/UNIQUE on the table):
    # remove ONLY this run's prior row for this exact representation, preserving all other rows.
    con.execute(
        f"DELETE FROM {_TABLE} WHERE run_id = ? AND strategy_key = ? AND sim_metric = ? AND k = ?",
        [run_id, strategy_key, sim_metric, k],
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
    """Return every persisted diagnostic row as a dict (optionally for one *run_id*).

    Column order matches :data:`incomplete_diagnostic_columns`.  Returns ``[]`` when the table is
    absent or no rows match.
    """
    if not _table_exists(con):
        return []
    cols = incomplete_diagnostic_columns
    if run_id is not None:
        rows = con.execute(
            f"SELECT {', '.join(cols)} FROM {_TABLE} WHERE run_id = ? ORDER BY strategy_key, k",
            [str(run_id)],
        ).fetchall()
    else:
        rows = con.execute(f"SELECT {', '.join(cols)} FROM {_TABLE} ORDER BY run_id, strategy_key, k").fetchall()
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
