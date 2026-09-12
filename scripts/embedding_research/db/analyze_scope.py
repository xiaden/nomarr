"""Geometry-era analyze invocation lifecycle bookkeeping.

The earlier analyze-scope identity DTOs, encoders/decoders, parsers, and the
retired metric writer were removed by the Plan K hard cut.  This module now owns
only the run-scoped analyze *invocation lifecycle*: the canonical single-line
obligations/terminal records appended to the run's ``run_provenance.output_artifact_hashes``.

Geometry analysis/retrieval identities live in ``db.identity_persistence`` and
``common.geometry_analysis``; there is no scope anchor, scope kind, member identity,
view keyset, or compatibility encoder here.
"""

from __future__ import annotations

import json

#: The provenance phase that carries the analyze invocation records.
_ANALYZE_PHASE = "analyze"

#: Single-line invocation-obligations record prefix (the invocation is ``running`` from this line).
_INVOCATION_PREFIX = "analyze_invocation_v1"
#: Single-line terminal-outcome record prefix (appended once, only after obligations resolve).
_TERMINAL_PREFIX = "analyze_terminal_v1"
#: The one terminal outcome that makes a run a clean completed analyze scope.
_TERMINAL_COMPLETED = "completed"

#: Canonical single-line markers (record-kind discriminators) — kept importable for predicates.
INVOCATION_MARKER_PREFIX = _INVOCATION_PREFIX
TERMINAL_MARKER_PREFIX = _TERMINAL_PREFIX
TERMINAL_OUTCOME_COMPLETED = _TERMINAL_COMPLETED


class AnalyzeInvocationError(RuntimeError):
    """The invocation-obligations/terminal lifecycle contract was violated (duplicate/conflict)."""


class AnalyzeInvocationIncompleteError(AnalyzeInvocationError):
    """An invocation obligation is unresolved, so the run cannot terminalize ``completed``.

    Raised by :func:`terminalize_analyze_completed` when a declared obligation (a requested
    backbone's MANDATORY observed ``global_pool:{backbone}:medoid`` baseline) has no persisted
    evidence, or when no obligations-start record exists to terminalize.  The caller fails
    closed (propagates -> a ``failed`` analyze provenance row) rather than recording a terminal
    ``completed`` for an invocation whose obligations are not all resolved.
    """


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)


def _output_lines(blob: str | None) -> list[str]:
    return [ln for ln in (blob or "").splitlines() if ln.strip()] if blob else []


def _marker_payload(line: str, prefix: str) -> dict | None:
    """Parse a ``<prefix>|<json>`` line to its payload dict; None for any other line."""
    if not line.startswith(prefix + "|"):
        return None
    try:
        payload = json.loads(line.split("|", 1)[1])
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _analyze_row_blobs(con, *, run_id: str) -> list[str]:
    rows = con.execute(
        "SELECT output_artifact_hashes FROM run_provenance WHERE run_id=? AND phase=?",
        (run_id, _ANALYZE_PHASE),
    ).fetchall()
    return [(b or "") for (b,) in rows]


def encode_invocation_obligations(backbones) -> dict:
    """Canonical obligations payload for an analyze invocation over *backbones*.

    *backbones* is an ordered iterable of ``(backbone, geometry_id)`` pairs. Each entry declares
    one mandatory observed baseline geometry identity for the invocation.
    """
    ordered = sorted((str(b), str(k)) for b, k in backbones)
    return {"version": 2, "backbones": [{"backbone": b, "geometry_id": k} for b, k in ordered]}


def record_analyze_invocation(
    con,
    *,
    run_id: str,
    backbones,
    started_at: int | None = None,
) -> None:
    """Start an analyze invocation by recording its declared obligations (``running``).

    Appends the ``analyze_invocation_v1|...`` record onto the run's ``phase='analyze'``
    provenance row(s) (creating a ``complete``-status row when none exists yet, so the invocation
    ledger anchor always precedes/coincides with the scope evidence).  Raises
    :class:`AnalyzeInvocationError` if the run already has an invocation record (a run starts its
    invocation exactly once).  Evidence recorded later rides on the same append-only rows and
    never terminalizes this invocation.
    """
    payload = encode_invocation_obligations(backbones)
    line = f"{_INVOCATION_PREFIX}|{json.dumps(payload, sort_keys=True, separators=(',', ':'))}"
    for blob in _analyze_row_blobs(con, run_id=run_id):
        if any(_marker_payload(ln, _INVOCATION_PREFIX) is not None for ln in _output_lines(blob)):
            raise AnalyzeInvocationError(
                f"analyze invocation obligations already recorded for run_id={run_id!r}; "
                "an invocation starts exactly once"
            )
    _append_analyze_line(con, run_id=run_id, line=line, started_at=started_at)


def invocation_state(con, *, run_id: str) -> dict:
    """Return the run's invocation-obligations/terminal state for report-completion predicates.

    Returns ``{"obligations_present": bool, "obligations": dict|None,
    "terminal_completed": bool}``.  ``obligations_present`` is True when the run carries an
    ``analyze_invocation_v1`` record; ``terminal_completed`` is True when it additionally carries
    a ``completed`` ``analyze_terminal_v1`` record.  A run with obligations but no completed
    terminal is an OPEN (running / incompletely-obligated) invocation.
    """
    obligations_present = False
    terminal_completed = False
    obligations_payload: dict | None = None
    for blob in _analyze_row_blobs(con, run_id=run_id):
        for ln in _output_lines(blob):
            inv = _marker_payload(ln, _INVOCATION_PREFIX)
            if inv is not None:
                obligations_present = True
                obligations_payload = inv
                continue
            term = _marker_payload(ln, _TERMINAL_PREFIX)
            if term is not None and term.get("outcome") == _TERMINAL_COMPLETED:
                terminal_completed = True
    return {
        "obligations_present": obligations_present,
        "obligations": obligations_payload,
        "terminal_completed": terminal_completed,
    }


def terminalize_analyze_completed(
    con,
    *,
    run_id: str,
    finished_at: int | None = None,
) -> None:
    """Terminalize *run_id*'s analyze invocation to ``completed`` after every obligation resolves.

    Appends the ``analyze_terminal_v1|{"outcome":"completed"}`` record onto the run's
    ``phase='analyze'`` provenance row(s) and stamps ``finished_at`` on them.  Refuses (raises)
    without recording anything when:

    * the run has NO obligations-start record (nothing to terminalize) — :class:`AnalyzeInvocationIncompleteError`;
    * a terminal record already exists (duplicate terminalization) — :class:`AnalyzeInvocationError`;
    * a declared obligation's mandatory observed baseline has no persisted geometry evidence
      under its exact geometry identity (an obligation is unresolved).

    The ``completed`` terminal is therefore written exactly once and only for a clean all-obligation
    invocation.  On any refusal the caller fails closed (propagates -> a ``failed`` analyze row),
    leaving any partial evidence append-only (never deleted, never reportable as completed).
    """
    if finished_at is None:
        finished_at = _now_ms()
    state = invocation_state(con, run_id=run_id)
    if not state["obligations_present"]:
        raise AnalyzeInvocationIncompleteError(
            f"cannot terminalize run_id={run_id!r} completed: no analyze invocation obligations "
            "record exists (the invocation was never started)"
        )
    if state["terminal_completed"]:
        raise AnalyzeInvocationError(
            f"refusing duplicate terminalization of run_id={run_id!r}: a completed terminal "
            "already exists (an invocation has exactly one terminal outcome)"
        )
    obligations = state["obligations"] or {}
    unresolved: list[str] = []
    for entry in obligations.get("backbones", []):
        geometry_id = str(entry.get("geometry_id", ""))
        backbone = str(entry.get("backbone", ""))
        if not geometry_id:
            unresolved.append(f"{backbone}: missing mandatory geometry identity")
            continue
        n = con.execute(
            "SELECT count(*) FROM geometry_analysis_records WHERE run_id=? AND geometry_id=? AND metric='baseline_present'",
            (run_id, geometry_id),
        ).fetchone()[0]
        if not n:
            unresolved.append(f"{backbone}: no {geometry_id} baseline evidence")
    if unresolved:
        raise AnalyzeInvocationIncompleteError(
            f"refusing to terminalize run_id={run_id!r} completed with unresolved obligations: " + "; ".join(unresolved)
        )
    line = f"{_TERMINAL_PREFIX}|{json.dumps({'outcome': _TERMINAL_COMPLETED}, sort_keys=True, separators=(',', ':'))}"
    _append_analyze_line(con, run_id=run_id, line=line, started_at=None, finished_at=finished_at)


def _append_analyze_line(
    con,
    *,
    run_id: str,
    line: str,
    started_at: int | None = None,
    finished_at: int | None = None,
) -> None:
    """Append one canonical single-line record onto the run's ``phase='analyze'`` row(s).

    Appends *line* (deduped) to every existing ``phase='analyze'`` row of the run; when no such
    row exists yet one is created (status ``complete``) so the record's anchor always exists.
    Rows of other runs (incl. retained) are never modified.  ``finished_at`` is stamped only when
    supplied (terminalize).
    """
    existing = con.execute(
        "SELECT rowid FROM run_provenance WHERE run_id=? AND phase=?",
        (run_id, _ANALYZE_PHASE),
    ).fetchall()
    if not existing:
        from scripts.embedding_research.db.provenance import write_run_provenance

        write_run_provenance(
            con,
            run_id=run_id,
            phase=_ANALYZE_PHASE,
            status="complete",
            started_at=started_at if started_at is not None else _now_ms(),
            finished_at=finished_at if finished_at is not None else _now_ms(),
            output_artifact_hashes=line,
        )
        return
    stamp_sql = "output_artifact_hashes = ?"
    params: list[object] = []
    for (rowid,) in existing:
        (blob,) = con.execute("SELECT output_artifact_hashes FROM run_provenance WHERE rowid=?", (rowid,)).fetchone()
        lines = _output_lines(blob)
        if line not in lines:
            lines.append(line)
        if finished_at is not None:
            stamp_sql = "output_artifact_hashes = ?, finished_at = ?"
            params = ["\n".join(lines), int(finished_at)]
        else:
            params = ["\n".join(lines)]
        con.execute(f"UPDATE run_provenance SET {stamp_sql} WHERE rowid=?", (*params, rowid))
