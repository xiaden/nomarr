"""Exact geometry-era persistence for analysis and head evidence."""

from __future__ import annotations

import json
import math
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable


class IdentityRefusal(ValueError):  # noqa: N818
    """Evidence is incomplete, stale, superseded, non-finite, or ambiguous."""


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


_HEAD_EVIDENCE_COLUMNS: tuple[str, ...] = (
    "run_id",
    "geometry_id",
    "observation_id",
    "geometry_semantics_version",
    "numerical_profile_digest",
    "threshold_id",
    "structural_identity",
    "search_representation_id",
    "evaluation_id",
    "scoring_semantics_version",
    "execution_id",
    "head",
    "segment_id",
    "evidence_json",
)


def _identity(value: Any) -> dict[str, Any]:
    names = (
        "geometry_id",
        "observation_id",
        "geometry_semantics_version",
        "numerical_profile_digest",
        "threshold_id",
        "structural_identity",
        "search_representation_id",
        "evaluation_id",
        "scoring_semantics_version",
        "execution_id",
    )
    data = {
        name: (
            int(getattr(value, name)) if name == "scoring_semantics_version" else str(getattr(value, name, "") or "")
        )
        for name in names
    }
    missing = [
        name
        for name, item in data.items()
        if item == "" or item is None or (name == "scoring_semantics_version" and item < 1)
    ]
    if missing:
        raise IdentityRefusal("incomplete geometry-era identity: " + ", ".join(missing))
    return data


def _finite(value: Any) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise IdentityRefusal("non-finite metric evidence")
    return result


def _transaction(con):
    """Return a context manager that commits on success and rolls back on failure."""

    class Tx:
        def __enter__(self):
            con.execute("BEGIN")
            return con

        def __exit__(self, typ, value, tb):
            con.execute("ROLLBACK" if typ else "COMMIT")
            return False

    return Tx()


def write_analysis_rows_in_transaction(
    con, *, run_id: str, identity: Any, metrics: dict[str, Any], evidence: Any = None
) -> None:
    """Write one exact identity's finite evidence on the caller's already-open transaction.

    This is the transaction-participating half of :func:`write_analysis_rows`: it performs
    the same complete-identity, finite-value and duplicate-identity validation but never
    opens its own ``BEGIN``, so a multi-table corpus publication can share exactly one
    atomic transaction (DuckDB has no nested transactions).
    """
    if not run_id:
        raise IdentityRefusal("run_id is required")
    ident = _identity(identity)
    rows = [(str(name), _finite(value)) for name, value in sorted(metrics.items())]
    if not rows:
        raise IdentityRefusal("analysis has no metric evidence")
    payload = _json(evidence if evidence is not None else {})
    stamp = int(time.time() * 1000)
    for metric, value in rows:
        key = (run_id, *ident.values(), metric)
        count = con.execute(
            "SELECT count(*) FROM geometry_analysis_records WHERE run_id=? AND geometry_id=? AND observation_id=? AND geometry_semantics_version=? AND numerical_profile_digest=? AND threshold_id=? AND structural_identity=? AND search_representation_id=? AND evaluation_id=? AND scoring_semantics_version=? AND execution_id=? AND metric=?",
            key,
        ).fetchone()[0]
        if count:
            raise IdentityRefusal("duplicate geometry analysis identity")
        con.execute(
            "INSERT INTO geometry_analysis_records (run_id,geometry_id,observation_id,geometry_semantics_version,numerical_profile_digest,threshold_id,structural_identity,search_representation_id,evaluation_id,scoring_semantics_version,execution_id,metric,value,evidence_json,created_at_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [run_id, *ident.values(), metric, value, payload, stamp],
        )


def write_analysis_rows(con, *, run_id: str, identity: Any, metrics: dict[str, Any], evidence: Any = None) -> None:
    """Persist geometry analysis metric rows under one complete geometry identity."""
    with _transaction(con):
        write_analysis_rows_in_transaction(con, run_id=run_id, identity=identity, metrics=metrics, evidence=evidence)


def read_analysis_rows(con, *, run_id: str, identity: Any) -> tuple[dict[str, Any], ...]:
    """Read the metric rows for one exact geometry identity, refusing when absent."""
    ident = _identity(identity)
    rows = con.execute(
        "SELECT metric,value,evidence_json FROM geometry_analysis_records WHERE run_id=? AND geometry_id=? AND observation_id=? AND geometry_semantics_version=? AND numerical_profile_digest=? AND threshold_id=? AND structural_identity=? AND search_representation_id=? AND evaluation_id=? AND scoring_semantics_version=? AND execution_id=? ORDER BY metric",
        [run_id, *ident.values()],
    ).fetchall()
    if not rows:
        raise IdentityRefusal("exact geometry analysis identity not found")
    return tuple({"metric": row[0], "value": float(row[1]), "evidence": json.loads(row[2])} for row in rows)


def write_head_evidence(con, *, run_id: str, outputs: Iterable[Any]) -> None:
    """Persist done head-evidence payloads, refusing empty or duplicate identities."""
    materialized = list(outputs)
    if not materialized:
        raise IdentityRefusal("head evidence is empty")
    rows = []
    for output in materialized:
        ident = _identity(output)
        if str(getattr(output, "status", "done")) != "done":
            raise IdentityRefusal("refused head evidence")
        payload = output.to_dict() if hasattr(output, "to_dict") else dict(output)
        _json(payload)
        rows.append(
            (run_id, *ident.values(), str(output.head), int(output.segment_id), _json(payload), int(time.time() * 1000))
        )
    with _transaction(con):
        for row in rows:
            count = con.execute(
                "SELECT count(*) FROM geometry_head_evidence WHERE run_id=? AND geometry_id=? AND observation_id=? AND geometry_semantics_version=? AND numerical_profile_digest=? AND threshold_id=? AND structural_identity=? AND search_representation_id=? AND evaluation_id=? AND scoring_semantics_version=? AND execution_id=? AND head=? AND segment_id=?",
                row[:13],
            ).fetchone()[0]
            if count:
                raise IdentityRefusal("duplicate geometry head identity")
        con.executemany(
            "INSERT INTO geometry_head_evidence (run_id,geometry_id,observation_id,geometry_semantics_version,numerical_profile_digest,threshold_id,structural_identity,search_representation_id,evaluation_id,scoring_semantics_version,execution_id,head,segment_id,evidence_json,created_at_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )


def read_head_evidence(con, *, run_id: str, identity: Any) -> tuple[dict[str, Any], ...]:
    """Read persisted head-evidence payloads for one exact geometry identity."""
    ident = _identity(identity)
    rows = con.execute(
        "SELECT evidence_json FROM geometry_head_evidence WHERE run_id=? AND geometry_id=? AND observation_id=? AND geometry_semantics_version=? AND numerical_profile_digest=? AND threshold_id=? AND evaluation_id=? AND search_representation_id=? AND execution_id=? ORDER BY head,segment_id",
        [run_id, *ident.values()],
    ).fetchall()
    if not rows:
        raise IdentityRefusal("exact geometry head identity not found")
    return tuple(json.loads(row[0]) for row in rows)


def read_head_evidence_for_run(con, *, run_id: str) -> tuple[dict[str, Any], ...]:
    """Return every persisted head-evidence payload for *run_id*, ordered deterministically.

    Report/read-side counterpart of :func:`read_head_evidence`: it does not presuppose a
    single geometry identity (a run may carry several) but still refuses an empty run and
    never infers a latest/current run.
    """
    if not run_id:
        raise IdentityRefusal("run_id is required")
    rows = con.execute(
        "SELECT run_id,geometry_id,observation_id,geometry_semantics_version,"
        "numerical_profile_digest,threshold_id,structural_identity,search_representation_id,"
        "evaluation_id,scoring_semantics_version,execution_id,head,segment_id,evidence_json "
        "FROM geometry_head_evidence WHERE run_id=? ORDER BY geometry_id,observation_id,"
        "evaluation_id,head,segment_id",
        (str(run_id),),
    ).fetchall()
    if not rows:
        raise IdentityRefusal("no geometry head evidence for run")
    return tuple(dict(zip(_HEAD_EVIDENCE_COLUMNS, row, strict=True)) for row in rows)


def read_threshold_map_rows(
    con: Any,
    *,
    run_id: str,
    evaluation_id: str,
    execution_id: str,
) -> tuple[dict[str, Any], ...]:
    """Read the per-threshold structural/search mapping rows for one exact corpus scope.

    Threshold rows carry the structural identity and search representation chosen for one
    threshold plus the role/song/backbone/comparability evidence.  Rows from another
    evaluation or execution are never substituted.
    """
    rows = con.execute(
        "SELECT threshold_id, structural_identity, search_representation_id, evidence_json "
        "FROM geometry_analysis_records WHERE run_id=? AND evaluation_id=? AND execution_id=? "
        "AND metric='total_searchable' ORDER BY threshold_id",
        (run_id, evaluation_id, execution_id),
    ).fetchall()
    entries: list[dict[str, Any]] = []
    for threshold_id, structural_identity, search_representation_id, evidence_json in rows:
        evidence = json.loads(evidence_json) if evidence_json else {}
        if not isinstance(evidence, dict) or evidence.get("role") != "threshold":
            continue
        entries.append(
            {
                "song_id": str(evidence.get("song_id", "")),
                "backbone": str(evidence.get("backbone", "")),
                "threshold_id": str(threshold_id),
                "structural_identity": str(structural_identity),
                "search_representation_id": str(search_representation_id),
                "comparable": bool(evidence.get("comparable", True)),
            }
        )
    return tuple(entries)
