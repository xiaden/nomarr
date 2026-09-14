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
    "observation_group_sha256",
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
            "SELECT count(*) FROM geometry_analysis_records WHERE run_id=? AND geometry_id=? AND observation_group_sha256=? AND geometry_semantics_version=? AND numerical_profile_digest=? AND threshold_id=? AND structural_identity=? AND search_representation_id=? AND evaluation_id=? AND scoring_semantics_version=? AND execution_id=? AND metric=?",
            key,
        ).fetchone()[0]
        if count:
            raise IdentityRefusal("duplicate geometry analysis identity")
        con.execute(
            "INSERT INTO geometry_analysis_records (run_id,geometry_id,observation_group_sha256,geometry_semantics_version,numerical_profile_digest,threshold_id,structural_identity,search_representation_id,evaluation_id,scoring_semantics_version,execution_id,metric,value,evidence_json,created_at_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
        "SELECT metric,value,evidence_json FROM geometry_analysis_records WHERE run_id=? AND geometry_id=? AND observation_group_sha256=? AND geometry_semantics_version=? AND numerical_profile_digest=? AND threshold_id=? AND structural_identity=? AND search_representation_id=? AND evaluation_id=? AND scoring_semantics_version=? AND execution_id=? ORDER BY metric",
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
                "SELECT count(*) FROM geometry_head_evidence WHERE run_id=? AND geometry_id=? AND observation_group_sha256=? AND geometry_semantics_version=? AND numerical_profile_digest=? AND threshold_id=? AND structural_identity=? AND search_representation_id=? AND evaluation_id=? AND scoring_semantics_version=? AND execution_id=? AND head=? AND segment_id=?",
                row[:13],
            ).fetchone()[0]
            if count:
                raise IdentityRefusal("duplicate geometry head identity")
        con.executemany(
            "INSERT INTO geometry_head_evidence (run_id,geometry_id,observation_group_sha256,geometry_semantics_version,numerical_profile_digest,threshold_id,structural_identity,search_representation_id,evaluation_id,scoring_semantics_version,execution_id,head,segment_id,evidence_json,created_at_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )


def read_head_evidence(con, *, run_id: str, identity: Any) -> tuple[dict[str, Any], ...]:
    """Read persisted head-evidence payloads for one exact geometry identity."""
    ident = _identity(identity)
    rows = con.execute(
        "SELECT evidence_json FROM geometry_head_evidence WHERE run_id=? AND geometry_id=? AND observation_group_sha256=? AND geometry_semantics_version=? AND numerical_profile_digest=? AND threshold_id=? AND structural_identity=? AND search_representation_id=? AND evaluation_id=? AND scoring_semantics_version=? AND execution_id=? ORDER BY head,segment_id",
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
        "SELECT run_id,geometry_id,observation_group_sha256,geometry_semantics_version,"
        "numerical_profile_digest,threshold_id,structural_identity,search_representation_id,"
        "evaluation_id,scoring_semantics_version,execution_id,head,segment_id,evidence_json "
        "FROM geometry_head_evidence WHERE run_id=? ORDER BY geometry_id,observation_group_sha256,"
        "evaluation_id,head,segment_id",
        (str(run_id),),
    ).fetchall()
    if not rows:
        raise IdentityRefusal("no geometry head evidence for run")
    return tuple(dict(zip(_HEAD_EVIDENCE_COLUMNS, row, strict=True)) for row in rows)


_EVALUATION_CORPUS_COLUMNS: tuple[str, ...] = (
    "run_id",
    "execution_id",
    "evaluation_id",
    "experiment",
    "song_id",
    "backbone",
    "geometry_id",
    "observation_group_sha256",
    "numerical_profile_digest",
    "searchable_count",
    "comparable",
    "reasons_json",
    "baseline_valid",
    "created_at_ms",
)


def _required_text(value: Any, name: str) -> str:
    text = "" if value is None else str(value)
    if not text:
        raise IdentityRefusal(f"evaluation corpus {name} is required")
    return text


def _evaluation_corpus_row(
    entry: Any,
    *,
    run_id: str,
    evaluation_id: str,
    experiment: str,
    execution_id: str,
) -> tuple[Any, ...]:
    song_id = _required_text(getattr(entry, "song_id", ""), "song_id")
    backbone = _required_text(getattr(entry, "backbone", ""), "backbone")
    geometry_id = _required_text(getattr(entry, "geometry_id", ""), "geometry_id")
    observation_group = _required_text(getattr(entry, "observation_group_sha256", ""), "observation_group_sha256")
    profile_digest = _required_text(getattr(entry, "numerical_profile_digest", ""), "numerical_profile_digest")
    searchable_count = getattr(entry, "searchable_count", None)
    if isinstance(searchable_count, bool) or not isinstance(searchable_count, int) or searchable_count < 0:
        raise IdentityRefusal("evaluation corpus searchable_count must be a non-negative integer")
    for name in ("comparable", "baseline_valid"):
        if not isinstance(getattr(entry, name, None), bool):
            raise IdentityRefusal(f"evaluation corpus {name} must be boolean")
    reasons = tuple(str(reason) for reason in getattr(entry, "reasons", ()))
    return (
        run_id,
        execution_id,
        evaluation_id,
        experiment,
        song_id,
        backbone,
        geometry_id,
        observation_group,
        profile_digest,
        searchable_count,
        bool(entry.comparable),
        _json(list(reasons)),
        bool(entry.baseline_valid),
        int(time.time() * 1000),
    )


def write_evaluation_corpus_in_transaction(
    con,
    *,
    run_id: str,
    evaluation_id: str,
    experiment: str,
    execution_id: str,
    entries: Iterable[Any],
) -> None:
    """Insert the fixed evaluation-corpus membership on the caller's open transaction.

    One row per ``(run_id, evaluation_id, song_id, backbone)`` is application-enforced: a
    duplicate in the batch or already present in the table is refused, so membership can
    never be duplicated per threshold.
    """
    run_id = _required_text(run_id, "run_id")
    evaluation_id = _required_text(evaluation_id, "evaluation_id")
    experiment = _required_text(experiment, "experiment")
    execution_id = _required_text(execution_id, "execution_id")
    materialized = list(entries)
    if not materialized:
        raise IdentityRefusal("evaluation corpus is empty")
    seen: set[tuple[str, str]] = set()
    rows: list[tuple[Any, ...]] = []
    for entry in materialized:
        row = _evaluation_corpus_row(
            entry,
            run_id=run_id,
            evaluation_id=evaluation_id,
            experiment=experiment,
            execution_id=execution_id,
        )
        key = (str(row[4]), str(row[5]))
        if key in seen:
            raise IdentityRefusal("duplicate evaluation corpus membership in one write")
        seen.add(key)
        exists = con.execute(
            "SELECT count(*) FROM geometry_evaluation_corpus "
            "WHERE run_id=? AND evaluation_id=? AND song_id=? AND backbone=?",
            [run_id, evaluation_id, key[0], key[1]],
        ).fetchone()[0]
        if exists:
            raise IdentityRefusal("evaluation corpus membership already exists")
        rows.append(row)
    con.executemany(
        "INSERT INTO geometry_evaluation_corpus (run_id,execution_id,evaluation_id,experiment,song_id,backbone,"
        "geometry_id,observation_group_sha256,numerical_profile_digest,searchable_count,comparable,reasons_json,"
        "baseline_valid,created_at_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )


def write_evaluation_corpus(
    con,
    *,
    run_id: str,
    evaluation_id: str,
    experiment: str,
    execution_id: str,
    entries: Iterable[Any],
) -> None:
    """Persist the ONE fixed evaluation corpus, once per ``(run, evaluation, song, backbone)``."""
    with _transaction(con):
        write_evaluation_corpus_in_transaction(
            con,
            run_id=run_id,
            evaluation_id=evaluation_id,
            experiment=experiment,
            execution_id=execution_id,
            entries=entries,
        )


def read_evaluation_corpus(
    con: Any,
    *,
    run_id: str,
    evaluation_id: str | None = None,
    execution_id: str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Read persisted evaluation-corpus membership, ordered deterministically."""
    sql = (
        "SELECT run_id,execution_id,evaluation_id,experiment,song_id,backbone,geometry_id,"
        "observation_group_sha256,numerical_profile_digest,searchable_count,comparable,"
        "reasons_json,baseline_valid,created_at_ms FROM geometry_evaluation_corpus WHERE run_id=?"
    )
    params: list[Any] = [run_id]
    if evaluation_id is not None:
        sql += " AND evaluation_id=?"
        params.append(evaluation_id)
    if execution_id is not None:
        sql += " AND execution_id=?"
        params.append(execution_id)
    sql += " ORDER BY evaluation_id,execution_id,backbone,song_id"
    rows = con.execute(sql, params).fetchall()
    records: list[dict[str, Any]] = []
    for row in rows:
        record = dict(zip(_EVALUATION_CORPUS_COLUMNS, row, strict=True))
        record["reasons"] = tuple(json.loads(record.pop("reasons_json")))
        records.append(record)
    return tuple(records)


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


_THRESHOLD_CLASS_MAP_COLUMNS: tuple[str, ...] = (
    "run_id",
    "execution_id",
    "evaluation_id",
    "experiment",
    "threshold_index",
    "threshold_value",
    "threshold_id",
    "corpus_search_class_id",
    "comparable",
    "reasons_json",
    "created_at_ms",
)

_THRESHOLD_STRUCTURAL_COLUMNS: tuple[str, ...] = (
    "run_id",
    "evaluation_id",
    "song_id",
    "backbone",
    "threshold_index",
    "threshold_id",
    "structural_identity",
    "search_representation_id",
    "searchable_count",
    "medoid_defined",
    "alignment_ok",
    "comparable",
    "reasons_json",
    "created_at_ms",
)


def _non_negative_index(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise IdentityRefusal(f"{name} must be a non-negative integer")
    return value


def _threshold_class_row(
    row: Any, *, run_id: str, evaluation_id: str, execution_id: str, experiment: str
) -> tuple[Any, ...]:
    index = _non_negative_index(getattr(row, "threshold_index", None), "threshold class threshold_index")
    threshold_value = getattr(row, "threshold_value", None)
    if isinstance(threshold_value, bool) or not isinstance(threshold_value, (int, float)):
        raise IdentityRefusal("threshold class threshold_value must be finite")
    if not isinstance(row.comparable, bool):
        raise IdentityRefusal("threshold class comparable must be boolean")
    reasons = tuple(str(reason) for reason in getattr(row, "reasons", ()))
    return (
        run_id,
        execution_id,
        evaluation_id,
        experiment,
        index,
        float(threshold_value),
        _required_text(getattr(row, "threshold_id", ""), "threshold_id"),
        _required_text(getattr(row, "corpus_search_class_id", ""), "corpus_search_class_id"),
        bool(row.comparable),
        _json(list(reasons)),
        int(time.time() * 1000),
    )


def write_threshold_class_map_in_transaction(
    con,
    *,
    run_id: str,
    evaluation_id: str,
    execution_id: str,
    experiment: str,
    rows: Iterable[Any],
) -> None:
    """Insert the threshold-to-class map on the caller's open transaction.

    Exactly one row per configured threshold is written, keyed by
    ``(run_id, execution_id, evaluation_id, threshold_index)``.  A duplicate index in the
    batch or already present in the table is refused; equal ordered corpus scoring inputs
    may share ``corpus_search_class_id`` without collapsing away any threshold row.
    """
    run_id = _required_text(run_id, "run_id")
    evaluation_id = _required_text(evaluation_id, "evaluation_id")
    execution_id = _required_text(execution_id, "execution_id")
    experiment = _required_text(experiment, "experiment")
    materialized = list(rows)
    if not materialized:
        raise IdentityRefusal("threshold class map is empty")
    seen: set[int] = set()
    records: list[tuple[Any, ...]] = []
    for row in materialized:
        record = _threshold_class_row(
            row,
            run_id=run_id,
            evaluation_id=evaluation_id,
            execution_id=execution_id,
            experiment=experiment,
        )
        index = int(record[4])
        if index in seen:
            raise IdentityRefusal("duplicate threshold class map identity in one write")
        seen.add(index)
        exists = con.execute(
            "SELECT count(*) FROM geometry_threshold_class_map "
            "WHERE run_id=? AND execution_id=? AND evaluation_id=? AND threshold_index=?",
            [run_id, execution_id, evaluation_id, index],
        ).fetchone()[0]
        if exists:
            raise IdentityRefusal("threshold class map identity already exists")
        records.append(record)
    con.executemany(
        "INSERT INTO geometry_threshold_class_map (run_id,execution_id,evaluation_id,experiment,threshold_index,"
        "threshold_value,threshold_id,corpus_search_class_id,comparable,reasons_json,created_at_ms) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        records,
    )


def _threshold_structural_row(row: Any, *, run_id: str, evaluation_id: str) -> tuple[Any, ...]:
    index = _non_negative_index(getattr(row, "threshold_index", None), "threshold structural threshold_index")
    searchable_count = getattr(row, "searchable_count", None)
    if isinstance(searchable_count, bool) or not isinstance(searchable_count, int) or searchable_count < 0:
        raise IdentityRefusal("threshold structural searchable_count must be a non-negative integer")
    for name in ("medoid_defined", "alignment_ok", "comparable"):
        if not isinstance(getattr(row, name, None), bool):
            raise IdentityRefusal(f"threshold structural {name} must be boolean")
    reasons = tuple(str(reason) for reason in getattr(row, "reasons", ()))
    return (
        run_id,
        evaluation_id,
        _required_text(getattr(row, "song_id", ""), "song_id"),
        _required_text(getattr(row, "backbone", ""), "backbone"),
        index,
        _required_text(getattr(row, "threshold_id", ""), "threshold_id"),
        _required_text(getattr(row, "structural_identity", ""), "structural_identity"),
        _required_text(getattr(row, "search_representation_id", ""), "search_representation_id"),
        searchable_count,
        bool(row.medoid_defined),
        bool(row.alignment_ok),
        bool(row.comparable),
        _json(list(reasons)),
        int(time.time() * 1000),
    )


def write_threshold_structural_in_transaction(
    con,
    *,
    run_id: str,
    evaluation_id: str,
    rows: Iterable[Any],
) -> None:
    """Insert per-``(song, threshold)`` structural/search evidence on the caller's transaction.

    Row identity is application-enforced by ``(run_id, evaluation_id, song_id, threshold_index)``;
    a duplicate in the batch or already present in the table is refused.  These rows carry
    structural/search evidence only - never a retrieval metric.
    """
    run_id = _required_text(run_id, "run_id")
    evaluation_id = _required_text(evaluation_id, "evaluation_id")
    materialized = list(rows)
    if not materialized:
        raise IdentityRefusal("threshold structural rows are empty")
    seen: set[tuple[str, int]] = set()
    records: list[tuple[Any, ...]] = []
    for row in materialized:
        record = _threshold_structural_row(row, run_id=run_id, evaluation_id=evaluation_id)
        key = (str(record[2]), int(record[4]))
        if key in seen:
            raise IdentityRefusal("duplicate threshold structural identity in one write")
        seen.add(key)
        exists = con.execute(
            "SELECT count(*) FROM geometry_threshold_structural "
            "WHERE run_id=? AND evaluation_id=? AND song_id=? AND threshold_index=?",
            [run_id, evaluation_id, key[0], key[1]],
        ).fetchone()[0]
        if exists:
            raise IdentityRefusal("threshold structural identity already exists")
        records.append(record)
    con.executemany(
        "INSERT INTO geometry_threshold_structural (run_id,evaluation_id,song_id,backbone,threshold_index,"
        "threshold_id,structural_identity,search_representation_id,searchable_count,medoid_defined,alignment_ok,"
        "comparable,reasons_json,created_at_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        records,
    )


def read_threshold_class_map(
    con: Any,
    *,
    run_id: str,
    evaluation_id: str | None = None,
    execution_id: str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Read the persisted threshold-to-class map, ordered by threshold index."""
    sql = (
        "SELECT run_id,execution_id,evaluation_id,experiment,threshold_index,threshold_value,"
        "threshold_id,corpus_search_class_id,comparable,reasons_json,created_at_ms "
        "FROM geometry_threshold_class_map WHERE run_id=?"
    )
    params: list[Any] = [run_id]
    if evaluation_id is not None:
        sql += " AND evaluation_id=?"
        params.append(evaluation_id)
    if execution_id is not None:
        sql += " AND execution_id=?"
        params.append(execution_id)
    sql += " ORDER BY evaluation_id,execution_id,threshold_index"
    records: list[dict[str, Any]] = []
    for row in con.execute(sql, params).fetchall():
        record = dict(zip(_THRESHOLD_CLASS_MAP_COLUMNS, row, strict=True))
        record["reasons"] = tuple(json.loads(record.pop("reasons_json")))
        records.append(record)
    return tuple(records)


def read_threshold_structural(
    con: Any,
    *,
    run_id: str,
    evaluation_id: str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Read per-``(song, threshold)`` structural/search evidence, ordered deterministically."""
    sql = (
        "SELECT run_id,evaluation_id,song_id,backbone,threshold_index,threshold_id,structural_identity,"
        "search_representation_id,searchable_count,medoid_defined,alignment_ok,comparable,reasons_json,"
        "created_at_ms FROM geometry_threshold_structural WHERE run_id=?"
    )
    params: list[Any] = [run_id]
    if evaluation_id is not None:
        sql += " AND evaluation_id=?"
        params.append(evaluation_id)
    sql += " ORDER BY evaluation_id,song_id,threshold_index"
    records: list[dict[str, Any]] = []
    for row in con.execute(sql, params).fetchall():
        record = dict(zip(_THRESHOLD_STRUCTURAL_COLUMNS, row, strict=True))
        record["reasons"] = tuple(json.loads(record.pop("reasons_json")))
        records.append(record)
    return tuple(records)


_HEAD_LABEL_PROVENANCE_COLUMNS: tuple[str, ...] = (
    "run_id",
    "evaluation_id",
    "song_id",
    "backbone",
    "present",
    "semantic_label_json",
    "labels_json",
    "pooled_json",
    "head_set_fingerprint",
    "head_ids",
    "dim_by_head",
    "stream_ref",
    "stream_digest",
    "mask_ref",
    "mask_digest",
    "created_at_ms",
)


def _head_label_provenance_row(row: Any, *, run_id: str, evaluation_id: str) -> tuple[Any, ...]:
    present = getattr(row, "present", None)
    if not isinstance(present, bool):
        raise IdentityRefusal("head label provenance present must be boolean")
    song_id = _required_text(getattr(row, "song_id", ""), "song_id")
    backbone = _required_text(getattr(row, "backbone", ""), "backbone")
    if present:
        full_tuple = getattr(row, "full_tuple", None)
        if not full_tuple:
            raise IdentityRefusal("present head label provenance requires a full_tuple")
        semantic = [[str(head), int(side)] for head, side in full_tuple]
        labels = [str(label) for label in getattr(row, "labels", ())]
        pooled = [float(value) for value in getattr(row, "pooled", ())]
        if not all(math.isfinite(value) for value in pooled):
            raise IdentityRefusal("head label provenance pooled values must be finite")
        if len(labels) != len(semantic) or len(pooled) != len(semantic):
            raise IdentityRefusal("head label provenance tuple/labels/pooled must be aligned")
        fingerprint = _required_text(getattr(row, "head_set_fingerprint", ""), "head_set_fingerprint")
        head_ids = _required_text(getattr(row, "head_ids", ""), "head_ids")
        dim_by_head = _required_text(getattr(row, "dim_by_head", ""), "dim_by_head")
        stream_ref = _required_text(getattr(row, "stream_ref", ""), "stream_ref")
        stream_digest = _required_text(getattr(row, "stream_digest", ""), "stream_digest")
        mask_ref = _required_text(getattr(row, "mask_ref", ""), "mask_ref")
        mask_digest = _required_text(getattr(row, "mask_digest", ""), "mask_digest")
    else:
        semantic = None
        labels = []
        pooled = []
        fingerprint = head_ids = dim_by_head = stream_ref = stream_digest = mask_ref = mask_digest = ""
    return (
        run_id,
        evaluation_id,
        song_id,
        backbone,
        present,
        _json(semantic),
        _json(labels),
        _json(pooled),
        fingerprint,
        head_ids,
        dim_by_head,
        stream_ref,
        stream_digest,
        mask_ref,
        mask_digest,
        int(time.time() * 1000),
    )


def write_head_label_provenance_in_transaction(
    con,
    *,
    run_id: str,
    evaluation_id: str,
    rows: Iterable[Any],
) -> None:
    """Insert frozen semantic-head label + head-suite provenance on the caller's transaction.

    Row identity is application-enforced by ``(run_id, evaluation_id, song_id, backbone)``;
    a duplicate in the batch or already present in the table is refused.  The activation-derived
    semantic ruler label and the head-suite identity are persisted in SEPARATE columns: the
    suite fingerprint is provenance only and is never used as the ruler label.  A ``row`` with
    ``present = False`` records a per-song HEAD ruler exclusion (missing frozen head evidence)
    with empty identity strings and null/empty payloads.
    """
    run_id = _required_text(run_id, "run_id")
    evaluation_id = _required_text(evaluation_id, "evaluation_id")
    materialized = list(rows)
    if not materialized:
        raise IdentityRefusal("head label provenance rows are empty")
    seen: set[tuple[str, str]] = set()
    records: list[tuple[Any, ...]] = []
    for row in materialized:
        record = _head_label_provenance_row(row, run_id=run_id, evaluation_id=evaluation_id)
        key = (str(record[2]), str(record[3]))
        if key in seen:
            raise IdentityRefusal("duplicate head label provenance identity in one write")
        seen.add(key)
        exists = con.execute(
            "SELECT count(*) FROM geometry_head_label_provenance "
            "WHERE run_id=? AND evaluation_id=? AND song_id=? AND backbone=?",
            [run_id, evaluation_id, key[0], key[1]],
        ).fetchone()[0]
        if exists:
            raise IdentityRefusal("head label provenance identity already exists")
        records.append(record)
    con.executemany(
        "INSERT INTO geometry_head_label_provenance (run_id,evaluation_id,song_id,backbone,present,"
        "semantic_label_json,labels_json,pooled_json,head_set_fingerprint,head_ids,dim_by_head,"
        "stream_ref,stream_digest,mask_ref,mask_digest,created_at_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        records,
    )


def read_head_label_provenance(
    con: Any,
    *,
    run_id: str,
    evaluation_id: str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Read frozen semantic-head label + head-suite provenance, ordered deterministically."""
    sql = (
        "SELECT run_id,evaluation_id,song_id,backbone,present,semantic_label_json,labels_json,"
        "pooled_json,head_set_fingerprint,head_ids,dim_by_head,stream_ref,stream_digest,mask_ref,"
        "mask_digest,created_at_ms FROM geometry_head_label_provenance WHERE run_id=?"
    )
    params: list[Any] = [run_id]
    if evaluation_id is not None:
        sql += " AND evaluation_id=?"
        params.append(evaluation_id)
    sql += " ORDER BY evaluation_id,song_id,backbone"
    records: list[dict[str, Any]] = []
    for row in con.execute(sql, params).fetchall():
        record = dict(zip(_HEAD_LABEL_PROVENANCE_COLUMNS, row, strict=True))
        raw_semantic = json.loads(record.pop("semantic_label_json"))
        record["semantic_label"] = (
            None if raw_semantic is None else tuple((str(entry[0]), int(entry[1])) for entry in raw_semantic)
        )
        record["labels"] = tuple(str(label) for label in json.loads(record.pop("labels_json")))
        record["pooled"] = tuple(float(value) for value in json.loads(record.pop("pooled_json")))
        records.append(record)
    return tuple(records)
