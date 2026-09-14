"""Normalized Experiment One result surfaces (Plan A Phase 5).

The retired design persisted one giant nested ``role="corpus"`` JSON blob.  These surfaces
replace it with flat, query-ready rows:

* B ``geometry_class_aggregate_metrics`` -- one row per ``(class, ruler, metric, k)``
* C ``geometry_class_query_metrics``    -- one row per ``(class, query, ruler, metric, k)``
* D ``geometry_class_neighborhoods``    -- one retained row per ``(class, query, candidate)``
* E ``geometry_baseline_aggregate_metrics`` -- one row per ``(backbone, ruler, metric, k)``
* F ``geometry_baseline_query_metrics`` -- one row per ``(backbone, query, ruler, metric, k)``
* G ``geometry_baseline_neighborhoods`` -- one retained row per ``(backbone, query, candidate)``
* ``geometry_result_provenance``        -- ONE compact provenance row per run

There is no PRIMARY KEY / UNIQUE (DuckDB ART/WAL policy); every row identity is enforced in
the writer here, and an empty batch is a no-op so a run with no comparable class still
publishes its baseline.  A query is never its own candidate.
"""

from __future__ import annotations

import json
import math
import time
from typing import TYPE_CHECKING, Any

from scripts.embedding_research.db.identity_persistence import IdentityRefusal

if TYPE_CHECKING:
    from collections.abc import Iterable

_CANONICAL_NONCOMPARABLE_REASONS: tuple[str, ...] = (
    "alignment_failed",
    "zero_searchable",
    "no_medoid",
    "no_candidates",
    "label_missing",
)
_RULER_NAMES: tuple[str, ...] = ("artist", "genre", "head")
_CLASS_METRIC_NAMES: tuple[str, ...] = ("map_k", "mrr", "ndcg_k", "recall_k", "disc")
_METRIC_STATUSES: tuple[str, ...] = ("defined", "undefined")

_CLASS_AGGREGATE_METRIC_COLUMNS: tuple[str, ...] = (
    "run_id",
    "execution_id",
    "evaluation_id",
    "corpus_search_class_id",
    "ruler",
    "metric",
    "k",
    "value",
    "evaluable_query_count",
    "undefined_query_count",
    "created_at_ms",
)
_CLASS_QUERY_METRIC_COLUMNS: tuple[str, ...] = (
    "run_id",
    "corpus_search_class_id",
    "query_song_id",
    "ruler",
    "metric",
    "k",
    "value",
    "status",
    "created_at_ms",
)
_CLASS_NEIGHBORHOOD_COLUMNS: tuple[str, ...] = (
    "run_id",
    "corpus_search_class_id",
    "query_song_id",
    "candidate_song_id",
    "rank",
    "score",
    "created_at_ms",
)
_BASELINE_AGGREGATE_METRIC_COLUMNS: tuple[str, ...] = (
    "run_id",
    "execution_id",
    "evaluation_id",
    "backbone",
    "ruler",
    "metric",
    "k",
    "value",
    "evaluable_query_count",
    "undefined_query_count",
    "created_at_ms",
)
_BASELINE_QUERY_METRIC_COLUMNS: tuple[str, ...] = (
    "run_id",
    "backbone",
    "query_song_id",
    "ruler",
    "metric",
    "k",
    "value",
    "status",
    "created_at_ms",
)
_BASELINE_NEIGHBORHOOD_COLUMNS: tuple[str, ...] = (
    "run_id",
    "backbone",
    "query_song_id",
    "candidate_song_id",
    "rank",
    "score",
    "created_at_ms",
)
_RESULT_PROVENANCE_COLUMNS: tuple[str, ...] = (
    "run_id",
    "execution_id",
    "evaluation_id",
    "experiment",
    "scoring_semantics_version",
    "geometry_semantics_version",
    "numerical_profile_digest",
    "evidence_mode",
    "synthetic_only",
    "comparable",
    "reasons_json",
    "geometry_axes_json",
    "head_evidence_provenance_json",
    "counters_json",
    "created_at_ms",
)


def _text(value: Any, name: str) -> str:
    result = str(value or "")
    if not result:
        raise IdentityRefusal(f"{name} is required")
    return result


def _finite(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise IdentityRefusal("non-finite metric evidence")
    return result


def _index(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise IdentityRefusal(f"{name} must be a non-negative integer")
    return value


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _ruler(value: Any) -> str:
    result = _text(value, "ruler")
    if result not in _RULER_NAMES:
        raise IdentityRefusal("ruler must be artist, genre, or head")
    return result


def _metric(value: Any) -> str:
    result = _text(value, "metric")
    if result not in _CLASS_METRIC_NAMES:
        raise IdentityRefusal("metric must be a canonical class-scoped metric")
    return result


def _status(value: Any) -> str:
    result = _text(value, "status")
    if result not in _METRIC_STATUSES:
        raise IdentityRefusal("metric status must be defined or undefined")
    return result


def _insert_normalized_rows(
    con: Any,
    *,
    table: str,
    columns: tuple[str, ...],
    key_columns: tuple[str, ...],
    records: list[tuple[Any, ...]],
    label: str,
    self_columns: tuple[int, int] | None = None,
) -> None:
    """Insert normalized rows, refusing duplicates and self-referential windows.

    ``self_columns`` names the ``(query, candidate)`` positions for neighborhood tables; a
    row whose query equals its candidate is refused.  An empty batch is a no-op.
    """
    if not records:
        return
    key_index = tuple(columns.index(column) for column in key_columns)
    seen: set[tuple[Any, ...]] = set()
    for record in records:
        if self_columns is not None and record[self_columns[0]] == record[self_columns[1]]:
            raise IdentityRefusal(f"{label} query and candidate must differ")
        key = tuple(record[index] for index in key_index)
        if key in seen:
            raise IdentityRefusal(f"duplicate {label} identity in one write")
        seen.add(key)
        where = " AND ".join(f"{column}=?" for column in key_columns)
        exists = con.execute(f"SELECT count(*) FROM {table} WHERE {where}", list(key)).fetchone()[0]
        if exists:
            raise IdentityRefusal(f"{label} identity already exists")
    placeholders = ",".join("?" for _ in columns)
    con.executemany(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})", records)


def write_class_aggregate_metrics_in_transaction(
    con: Any,
    *,
    run_id: str,
    execution_id: str,
    evaluation_id: str,
    rows: Iterable[Any],
) -> None:
    """Insert class-scoped aggregate metrics (surface B) on the caller's transaction.

    Identity is ``(run_id, corpus_search_class_id, ruler, metric, k)``.  The evaluable and
    undefined query counts stay side by side so a metric an eligible query could not
    evaluate never silently shrinks the population.
    """
    run_id = _text(run_id, "run_id")
    execution_id = _text(execution_id, "execution_id")
    evaluation_id = _text(evaluation_id, "evaluation_id")
    stamp = int(time.time() * 1000)
    records = [
        (
            run_id,
            execution_id,
            evaluation_id,
            _text(getattr(row, "corpus_search_class_id", ""), "corpus_search_class_id"),
            _ruler(getattr(row, "ruler", None)),
            _metric(getattr(row, "metric", None)),
            _index(getattr(row, "k", None), "k"),
            _finite(getattr(row, "value", None)),
            _index(getattr(row, "evaluable_query_count", None), "evaluable_query_count"),
            _index(getattr(row, "undefined_query_count", None), "undefined_query_count"),
            stamp,
        )
        for row in rows
    ]
    _insert_normalized_rows(
        con,
        table="geometry_class_aggregate_metrics",
        columns=_CLASS_AGGREGATE_METRIC_COLUMNS,
        key_columns=("run_id", "corpus_search_class_id", "ruler", "metric", "k"),
        records=records,
        label="class aggregate metric",
    )


def write_class_query_metrics_in_transaction(con: Any, *, run_id: str, rows: Iterable[Any]) -> None:
    """Insert class-scoped per-query metrics (surface C) on the caller's transaction.

    Identity is ``(run_id, corpus_search_class_id, query_song_id, ruler, metric, k)`` with an
    explicit ``defined``/``undefined`` status.
    """
    run_id = _text(run_id, "run_id")
    stamp = int(time.time() * 1000)
    records = [
        (
            run_id,
            _text(getattr(row, "corpus_search_class_id", ""), "corpus_search_class_id"),
            _text(getattr(row, "query_song_id", ""), "query_song_id"),
            _ruler(getattr(row, "ruler", None)),
            _metric(getattr(row, "metric", None)),
            _index(getattr(row, "k", None), "k"),
            _finite(getattr(row, "value", None)),
            _status(getattr(row, "status", None)),
            stamp,
        )
        for row in rows
    ]
    _insert_normalized_rows(
        con,
        table="geometry_class_query_metrics",
        columns=_CLASS_QUERY_METRIC_COLUMNS,
        key_columns=("run_id", "corpus_search_class_id", "query_song_id", "ruler", "metric", "k"),
        records=records,
        label="class query metric",
    )


def write_class_neighborhoods_in_transaction(con: Any, *, run_id: str, rows: Iterable[Any]) -> None:
    """Insert retained class-scoped browsing windows (surface D) on the caller's transaction."""
    run_id = _text(run_id, "run_id")
    stamp = int(time.time() * 1000)
    records = [
        (
            run_id,
            _text(getattr(row, "corpus_search_class_id", ""), "corpus_search_class_id"),
            _text(getattr(row, "query_song_id", ""), "query_song_id"),
            _text(getattr(row, "candidate_song_id", ""), "candidate_song_id"),
            _index(getattr(row, "rank", None), "rank"),
            _finite(getattr(row, "score", None)),
            stamp,
        )
        for row in rows
    ]
    _insert_normalized_rows(
        con,
        table="geometry_class_neighborhoods",
        columns=_CLASS_NEIGHBORHOOD_COLUMNS,
        key_columns=("run_id", "corpus_search_class_id", "query_song_id", "candidate_song_id"),
        records=records,
        label="class neighborhood",
        self_columns=(2, 3),
    )


def write_baseline_aggregate_metrics_in_transaction(
    con: Any,
    *,
    run_id: str,
    execution_id: str,
    evaluation_id: str,
    rows: Iterable[Any],
) -> None:
    """Insert threshold-independent baseline aggregates (surface E) on the caller's transaction.

    Identity is ``(run_id, backbone, ruler, metric, k)``.  These rows are the run-lifecycle
    reachability signal: baseline presence per backbone is independent of the configured
    threshold count.
    """
    run_id = _text(run_id, "run_id")
    execution_id = _text(execution_id, "execution_id")
    evaluation_id = _text(evaluation_id, "evaluation_id")
    stamp = int(time.time() * 1000)
    records = [
        (
            run_id,
            execution_id,
            evaluation_id,
            _text(getattr(row, "backbone", ""), "backbone"),
            _ruler(getattr(row, "ruler", None)),
            _metric(getattr(row, "metric", None)),
            _index(getattr(row, "k", None), "k"),
            _finite(getattr(row, "value", None)),
            _index(getattr(row, "evaluable_query_count", None), "evaluable_query_count"),
            _index(getattr(row, "undefined_query_count", None), "undefined_query_count"),
            stamp,
        )
        for row in rows
    ]
    _insert_normalized_rows(
        con,
        table="geometry_baseline_aggregate_metrics",
        columns=_BASELINE_AGGREGATE_METRIC_COLUMNS,
        key_columns=("run_id", "backbone", "ruler", "metric", "k"),
        records=records,
        label="baseline aggregate metric",
    )


def write_baseline_query_metrics_in_transaction(con: Any, *, run_id: str, rows: Iterable[Any]) -> None:
    """Insert baseline per-query metrics (surface F) on the caller's transaction."""
    run_id = _text(run_id, "run_id")
    stamp = int(time.time() * 1000)
    records = [
        (
            run_id,
            _text(getattr(row, "backbone", ""), "backbone"),
            _text(getattr(row, "query_song_id", ""), "query_song_id"),
            _ruler(getattr(row, "ruler", None)),
            _metric(getattr(row, "metric", None)),
            _index(getattr(row, "k", None), "k"),
            _finite(getattr(row, "value", None)),
            _status(getattr(row, "status", None)),
            stamp,
        )
        for row in rows
    ]
    _insert_normalized_rows(
        con,
        table="geometry_baseline_query_metrics",
        columns=_BASELINE_QUERY_METRIC_COLUMNS,
        key_columns=("run_id", "backbone", "query_song_id", "ruler", "metric", "k"),
        records=records,
        label="baseline query metric",
    )


def write_baseline_neighborhoods_in_transaction(con: Any, *, run_id: str, rows: Iterable[Any]) -> None:
    """Insert retained baseline browsing windows (surface G) on the caller's transaction."""
    run_id = _text(run_id, "run_id")
    stamp = int(time.time() * 1000)
    records = [
        (
            run_id,
            _text(getattr(row, "backbone", ""), "backbone"),
            _text(getattr(row, "query_song_id", ""), "query_song_id"),
            _text(getattr(row, "candidate_song_id", ""), "candidate_song_id"),
            _index(getattr(row, "rank", None), "rank"),
            _finite(getattr(row, "score", None)),
            stamp,
        )
        for row in rows
    ]
    _insert_normalized_rows(
        con,
        table="geometry_baseline_neighborhoods",
        columns=_BASELINE_NEIGHBORHOOD_COLUMNS,
        key_columns=("run_id", "backbone", "query_song_id", "candidate_song_id"),
        records=records,
        label="baseline neighborhood",
        self_columns=(2, 3),
    )


def write_result_provenance_in_transaction(con: Any, *, run_id: str, row: Any) -> None:
    """Insert the ONE compact per-run provenance row on the caller's transaction.

    A second row for the same run is refused.  Nested reasons/axes/head-provenance/counters
    are JSON-encoded with ``allow_nan=False``; reasons must be canonical.
    """
    run_id = _text(run_id, "run_id")
    execution_id = _text(getattr(row, "execution_id", ""), "execution_id")
    evaluation_id = _text(getattr(row, "evaluation_id", ""), "evaluation_id")
    experiment = _text(getattr(row, "experiment", ""), "experiment")
    scoring_semantics_version = _index(getattr(row, "scoring_semantics_version", None), "scoring_semantics_version")
    if scoring_semantics_version < 1:
        raise IdentityRefusal("scoring_semantics_version must be positive")
    geometry_semantics_version = _text(getattr(row, "geometry_semantics_version", ""), "geometry_semantics_version")
    numerical_profile_digest = _text(getattr(row, "numerical_profile_digest", ""), "numerical_profile_digest")
    evidence_mode = _text(getattr(row, "evidence_mode", ""), "evidence_mode")
    synthetic_only = getattr(row, "synthetic_only", None)
    comparable = getattr(row, "comparable", None)
    for name, value in (("synthetic_only", synthetic_only), ("comparable", comparable)):
        if not isinstance(value, bool):
            raise IdentityRefusal(f"result provenance {name} must be boolean")
    reasons = getattr(row, "reasons", ())
    if not isinstance(reasons, tuple):
        reasons = tuple(reasons)
    if any(str(reason) not in _CANONICAL_NONCOMPARABLE_REASONS for reason in reasons):
        raise IdentityRefusal("result provenance reasons must be canonical")
    exists = con.execute("SELECT count(*) FROM geometry_result_provenance WHERE run_id=?", [run_id]).fetchone()[0]
    if exists:
        raise IdentityRefusal("result provenance already exists for run")
    con.execute(
        "INSERT INTO geometry_result_provenance (run_id,execution_id,evaluation_id,experiment,"
        "scoring_semantics_version,geometry_semantics_version,numerical_profile_digest,evidence_mode,"
        "synthetic_only,comparable,reasons_json,geometry_axes_json,head_evidence_provenance_json,"
        "counters_json,created_at_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            run_id,
            execution_id,
            evaluation_id,
            experiment,
            scoring_semantics_version,
            geometry_semantics_version,
            numerical_profile_digest,
            evidence_mode,
            synthetic_only,
            comparable,
            _json(list(reasons)),
            _json(list(getattr(row, "geometry_axes", ()))),
            _json(dict(getattr(row, "head_evidence_provenance", {}))),
            _json(dict(getattr(row, "counters", {}))),
            int(time.time() * 1000),
        ],
    )


def _read(con: Any, *, sql: str, columns: tuple[str, ...], run_id: str) -> tuple[dict[str, Any], ...]:
    return tuple(dict(zip(columns, row, strict=True)) for row in con.execute(sql, [run_id]).fetchall())


def read_class_aggregate_metrics(con: Any, *, run_id: str) -> tuple[dict[str, Any], ...]:
    """Read class-scoped aggregate metrics (surface B), ordered deterministically."""
    return _read(
        con,
        sql=(
            "SELECT run_id,execution_id,evaluation_id,corpus_search_class_id,ruler,metric,k,value,"
            "evaluable_query_count,undefined_query_count,created_at_ms FROM geometry_class_aggregate_metrics "
            "WHERE run_id=? ORDER BY corpus_search_class_id,ruler,metric,k"
        ),
        columns=_CLASS_AGGREGATE_METRIC_COLUMNS,
        run_id=run_id,
    )


def read_class_query_metrics(con: Any, *, run_id: str) -> tuple[dict[str, Any], ...]:
    """Read class-scoped per-query metrics (surface C), ordered deterministically."""
    return _read(
        con,
        sql=(
            "SELECT run_id,corpus_search_class_id,query_song_id,ruler,metric,k,value,status,created_at_ms "
            "FROM geometry_class_query_metrics "
            "WHERE run_id=? ORDER BY corpus_search_class_id,query_song_id,ruler,metric,k"
        ),
        columns=_CLASS_QUERY_METRIC_COLUMNS,
        run_id=run_id,
    )


def read_class_neighborhoods(con: Any, *, run_id: str) -> tuple[dict[str, Any], ...]:
    """Read retained class-scoped neighborhoods (surface D), ordered deterministically."""
    return _read(
        con,
        sql=(
            "SELECT run_id,corpus_search_class_id,query_song_id,candidate_song_id,rank,score,created_at_ms "
            "FROM geometry_class_neighborhoods "
            "WHERE run_id=? ORDER BY corpus_search_class_id,query_song_id,rank,candidate_song_id"
        ),
        columns=_CLASS_NEIGHBORHOOD_COLUMNS,
        run_id=run_id,
    )


def read_baseline_aggregate_metrics(con: Any, *, run_id: str) -> tuple[dict[str, Any], ...]:
    """Read threshold-independent baseline aggregates (surface E), ordered deterministically."""
    return _read(
        con,
        sql=(
            "SELECT run_id,execution_id,evaluation_id,backbone,ruler,metric,k,value,evaluable_query_count,"
            "undefined_query_count,created_at_ms FROM geometry_baseline_aggregate_metrics "
            "WHERE run_id=? ORDER BY backbone,ruler,metric,k"
        ),
        columns=_BASELINE_AGGREGATE_METRIC_COLUMNS,
        run_id=run_id,
    )


def read_baseline_query_metrics(con: Any, *, run_id: str) -> tuple[dict[str, Any], ...]:
    """Read baseline per-query metrics (surface F), ordered deterministically."""
    return _read(
        con,
        sql=(
            "SELECT run_id,backbone,query_song_id,ruler,metric,k,value,status,created_at_ms "
            "FROM geometry_baseline_query_metrics WHERE run_id=? ORDER BY backbone,query_song_id,ruler,metric,k"
        ),
        columns=_BASELINE_QUERY_METRIC_COLUMNS,
        run_id=run_id,
    )


def read_baseline_neighborhoods(con: Any, *, run_id: str) -> tuple[dict[str, Any], ...]:
    """Read retained baseline neighborhoods (surface G), ordered deterministically."""
    return _read(
        con,
        sql=(
            "SELECT run_id,backbone,query_song_id,candidate_song_id,rank,score,created_at_ms "
            "FROM geometry_baseline_neighborhoods "
            "WHERE run_id=? ORDER BY backbone,query_song_id,rank,candidate_song_id"
        ),
        columns=_BASELINE_NEIGHBORHOOD_COLUMNS,
        run_id=run_id,
    )


def read_result_provenance(con: Any, *, run_id: str) -> tuple[dict[str, Any], ...]:
    """Read the compact per-run provenance row, decoding each JSON payload."""
    sql = (
        "SELECT run_id,execution_id,evaluation_id,experiment,scoring_semantics_version,"
        "geometry_semantics_version,numerical_profile_digest,evidence_mode,synthetic_only,comparable,"
        "reasons_json,geometry_axes_json,head_evidence_provenance_json,counters_json,created_at_ms "
        "FROM geometry_result_provenance WHERE run_id=? ORDER BY run_id"
    )
    records: list[dict[str, Any]] = []
    for row in con.execute(sql, [run_id]).fetchall():
        record = dict(zip(_RESULT_PROVENANCE_COLUMNS, row, strict=True))
        record["reasons"] = tuple(str(reason) for reason in json.loads(record.pop("reasons_json")))
        record["geometry_axes"] = tuple(json.loads(record.pop("geometry_axes_json")))
        record["head_evidence_provenance"] = json.loads(record.pop("head_evidence_provenance_json"))
        record["counters"] = json.loads(record.pop("counters_json"))
        records.append(record)
    return tuple(records)
