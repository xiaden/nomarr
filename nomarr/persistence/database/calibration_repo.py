"""CalibrationRepo — CRUD for ``calibration_states`` and ``calibration_history``.

Uses Part B primitives for simple lookups and direct SQLAlchemy Core for
upserts and joins.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import Table, delete, func, select, update

from nomarr.helpers.dto.calibration_repo_dto import (
    CalibrationHistoryRecord,
    CalibrationStateJoined,
    CalibrationStateRecord,
)
from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.models.calibration_history import CalibrationHistory
from nomarr.persistence.models.calibration_state import CalibrationState
from nomarr.persistence.models.ml_model import MlModel
from nomarr.persistence.sql.exceptions import map_persistence_exceptions
from nomarr.persistence.sql.primitives import insert_one

if TYPE_CHECKING:
    from sqlalchemy.engine import CursorResult, Row
    from sqlalchemy.orm import Session, scoped_session

_T_STATE = cast("Table", CalibrationState.__table__)
_T_HISTORY = cast("Table", CalibrationHistory.__table__)

# Stable internal event name for persisted calibration history snapshots.  This
# is a repository-internal constant: the caller-facing domain surface never
# exposes the ``event``/``data`` envelope (ADR-032/040, ASR-0013/0014).  All
# snapshots for a model/head/label share this event tag; scoping is by natural
# identity (model_id + JSONB head/label), not by event.
_HISTORY_SNAPSHOT_EVENT = "calibration_snapshot"


def _state_identity_clauses(model_id: str, head_name: str, label: str) -> list[Any]:
    """Return the JSONB head/label predicates identifying one calibration state.

    ``head_name``/``label`` live inside the ``state_data`` JSONB envelope
    (there are no dedicated columns), so every state predicate filters on the
    stable ``model_id`` plus JSONB ``head_name`` and ``label``.  ``.astext``
    predicates work on both SQLite (``json_extract``) and PostgreSQL.
    """
    return [
        _T_STATE.c.model_id == model_id,
        _T_STATE.c.state_data["head_name"].astext == head_name,
        _T_STATE.c.state_data["label"].astext == label,
    ]


def _history_identity_clauses(model_id: str, head_name: str, label: str) -> list[Any]:
    """Return the JSONB head/label predicates identifying one calibration history identity.

    The relational ``calibration_history`` table has no ``head_name``/``label``
    columns — they live inside the ``data`` JSONB envelope — so every scoped
    history predicate filters on the stable ``model_id`` plus JSONB ``head_name``
    and ``label``.  ``.astext`` predicates work on both SQLite (``json_extract``)
    and PostgreSQL.
    """
    return [
        _T_HISTORY.c.model_id == model_id,
        _T_HISTORY.c.data["head_name"].astext == head_name,
        _T_HISTORY.c.data["label"].astext == label,
    ]


def _row_to_state_record(row: Row[Any]) -> CalibrationStateRecord:
    """Convert a SQLAlchemy ``Row`` to a ``CalibrationStateRecord`` TypedDict."""
    m = row._mapping
    return CalibrationStateRecord(
        id=m["id"],
        model_id=m["model_id"],
        state_data=m["state_data"],
        updated_at=m["updated_at"],
    )


def _row_to_history_record(row: Row[Any]) -> CalibrationHistoryRecord:
    """Convert a SQLAlchemy ``Row`` to a ``CalibrationHistoryRecord`` TypedDict."""
    m = row._mapping
    return CalibrationHistoryRecord(
        id=m["id"],
        model_id=m["model_id"],
        event=m["event"],
        data=m["data"],
        created_at=m["created_at"],
    )


def _row_to_state_joined(row: Row[Any]) -> CalibrationStateJoined:
    """Convert a SQLAlchemy join ``Row`` to a ``CalibrationStateJoined``."""
    m = row._mapping
    return CalibrationStateJoined(
        model_id=m["model_id"],
        state_data=m["state_data"],
        updated_at=m["updated_at"],
        id=m["id"],
        path=m["path"],
        model_type=m["model_type"],
        backbone_id=m["backbone_id"],
        backbone=m["backbone"],
        head_type=m["head_type"],
        model_stem=m["model_stem"],
        output_count=m["output_count"],
        fully_configured=m["fully_configured"],
        is_known=m["is_known"],
        source=m["source"],
        head_release_date=m["head_release_date"],
        embedder_release_date=m["embedder_release_date"],
    )


class CalibrationRepo:
    """Repository for the ``calibration_states`` and ``calibration_history`` tables."""

    def __init__(self, session: scoped_session[Session]) -> None:
        self._session = session

    # ── calibration state ───────────────────────────────────────

    def get_state(self, model_id: str) -> CalibrationStateRecord | None:
        """Fetch the calibration state for a given model."""
        with map_persistence_exceptions():
            stmt = select(_T_STATE).where(_T_STATE.c.model_id == model_id)
            result = self._session.execute(stmt)
            row = result.fetchone()
            return _row_to_state_record(row) if row else None

    def set_state(self, model_id: str, state_data: dict[str, Any]) -> CalibrationStateRecord:
        """Upsert a calibration state for a model/head/label.

        The public signature keeps ``(model_id, state_data)`` (``ml.py`` calls
        it), but the upsert predicates use the complete
        ``(model_id, head_name, label)`` logical identity.  ``head_name`` and
        ``label`` are read from the JSONB payload only to form that identity;
        the row is always located by the JSONB predicates via
        :func:`_state_identity_clauses`, never by a storage primary key.
        """
        with map_persistence_exceptions():
            now = now_ms().value
            head_name = str(state_data.get("head_name", ""))
            label = str(state_data.get("label", ""))
            existing = self.get_state_by_identity(model_id, head_name, label)
            if existing is not None:
                with self._session.begin_nested():
                    stmt = (
                        update(_T_STATE)
                        .where(*_state_identity_clauses(model_id, head_name, label))
                        .values(state_data=state_data, updated_at=now)
                        .returning(_T_STATE)
                    )
                    result = self._session.execute(stmt)
                    row = result.fetchone()
                self._session.commit()
                assert row is not None
                return _row_to_state_record(row)

            with self._session.begin_nested():
                row = insert_one(
                    _T_STATE,
                    {
                        "model_id": model_id,
                        "state_data": state_data,
                        "updated_at": now,
                    },
                    session=self._session,
                )
            self._session.commit()
            return _row_to_state_record(row)

    def get_state_by_identity(self, model_id: str, head_name: str, label: str) -> CalibrationStateRecord | None:
        """Fetch one state by owning model and logical head/label identity."""
        with map_persistence_exceptions():
            stmt = select(_T_STATE).where(*_state_identity_clauses(model_id, head_name, label))
            result = self._session.execute(stmt)
            row = result.fetchone()
            return _row_to_state_record(row) if row else None

    def get_state_by_head_label(self, head_name: str, label: str) -> CalibrationStateRecord | None:
        """Fetch one state by its logical head and label identity."""
        with map_persistence_exceptions():
            stmt = select(_T_STATE).where(
                _T_STATE.c.state_data["head_name"].astext == head_name,
                _T_STATE.c.state_data["label"].astext == label,
            )
            result = self._session.execute(stmt)
            row = result.fetchone()
            return _row_to_state_record(row) if row else None

    def list_states(self) -> list[CalibrationStateRecord]:
        """Return all calibration state rows."""
        with map_persistence_exceptions():
            stmt = select(_T_STATE)
            result = self._session.execute(stmt)
            return [_row_to_state_record(r) for r in result.all()]

    def list_states_for_model(
        self,
        model_id: str,
        head_name: str | None = None,
        label: str | None = None,
    ) -> list[CalibrationStateRecord]:
        """Return all calibration states for one model, optionally narrowed by head/label.

        ``head_name`` and/or ``label`` are applied as JSONB repository-side
        predicates so callers never scan rows in Python.  Integer row ids and
        JSONB envelopes stay repository-internal in the returned records.
        """
        with map_persistence_exceptions():
            clauses: list[Any] = [_T_STATE.c.model_id == model_id]
            if head_name is not None:
                clauses.append(_T_STATE.c.state_data["head_name"].astext == head_name)
            if label is not None:
                clauses.append(_T_STATE.c.state_data["label"].astext == label)
            stmt = select(_T_STATE).where(*clauses)
            result = self._session.execute(stmt)
            return [_row_to_state_record(r) for r in result.all()]

    def list_states_with_models(self) -> list[CalibrationStateJoined]:
        """Return calibration states joined with model metadata.

        Each result is a typed, repository-internal ``CalibrationStateJoined``
        carrying the state fields (``model_id``/``state_data``/``updated_at``)
        plus the model metadata needed to build a ``RegisteredModel``.  Integer
        row ids and the JSONB envelope are never exposed to callers.
        """
        with map_persistence_exceptions():
            cs = _T_STATE
            mm = MlModel.__table__
            stmt = select(
                cs.c.model_id,
                cs.c.state_data,
                cs.c.updated_at,
                mm.c.id,
                mm.c.path,
                mm.c.model_type,
                mm.c.backbone_id,
                mm.c.backbone,
                mm.c.head_type,
                mm.c.model_stem,
                mm.c.output_count,
                mm.c.fully_configured,
                mm.c.is_known,
                mm.c.source,
                mm.c.head_release_date,
                mm.c.embedder_release_date,
            ).select_from(cs.join(mm, cs.c.model_id == mm.c.id))
            result = self._session.execute(stmt)
            return [_row_to_state_joined(r) for r in result.all()]

    def delete_state(self, model_id: str, head_name: str, label: str) -> None:
        """Delete a state by its owning model and logical calibration identity."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                stmt = delete(_T_STATE).where(*_state_identity_clauses(model_id, head_name, label))
                self._session.execute(stmt)
            self._session.commit()

    def truncate_states(self) -> None:
        """Delete all rows from ``calibration_states`` (full reset)."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._session.execute(delete(_T_STATE))
            self._session.commit()

    # ── calibration history ─────────────────────────────────────

    def record_history(self, model_id: str, event: str, data: dict[str, Any]) -> CalibrationHistoryRecord:
        """Insert a calibration history event and return it."""
        with map_persistence_exceptions():
            now = now_ms().value
            with self._session.begin_nested():
                row = insert_one(
                    _T_HISTORY,
                    {
                        "model_id": model_id,
                        "event": event,
                        "data": data,
                        "created_at": now,
                    },
                    session=self._session,
                )
            self._session.commit()
            return _row_to_history_record(row)

    def get_history(self, model_id: str) -> list[CalibrationHistoryRecord]:
        """Return calibration history for a model, newest first."""
        with map_persistence_exceptions():
            stmt = select(_T_HISTORY).where(_T_HISTORY.c.model_id == model_id).order_by(_T_HISTORY.c.created_at.desc())
            result = self._session.execute(stmt)
            return [_row_to_history_record(r) for r in result.all()]

    # ── repository-owned snapshot intents (natural identity) ────
    #
    # The relational storage keeps the historical ``event``/``data`` envelope;
    # these intents map the domain snapshot semantics onto it without exposing
    # that envelope.  ``head_name``/``label``/``output_id`` are written INTO the
    # ``data`` JSONB envelope (there are no dedicated columns) so scoped queries
    # and stable output identity work; ``snapshot_at`` maps to the ``created_at``
    # epoch-ms column (the same semantic instant).  No event/data envelope,
    # JSONB internals, or generated integer id is ever surfaced to callers.

    def add_calibration_history_snapshot(
        self,
        model_id: str,
        head_name: str,
        label: str,
        snapshot_at: int,
        metrics: dict[str, Any],
    ) -> None:
        """Persist one calibration history snapshot under its natural identity.

        Repository-internal intent that maps a named snapshot to the relational
        ``event``/``data`` storage.  ``metrics`` is the mapper-supplied internal
        payload carrying the named snapshot fields (``p5``/``p95``,
        ``sample_count``/``underflow_count``/``overflow_count``, the optional
        deltas, and the optional stable ``output_id``).  This method builds the
        storage ``data`` envelope itself: ``head_name`` and ``label`` are written
        INTO it (scoping relies on JSONB predicates), the ``event`` is the stable
        internal :data:`_HISTORY_SNAPSHOT_EVENT` constant, and ``snapshot_at``
        maps to the ``created_at`` epoch-ms column.  ``output_id`` is forwarded
        verbatim (string-only, never int-encoded).  Returns ``None`` — callers
        never receive a generated row id.
        """
        with map_persistence_exceptions():
            data = dict(metrics)
            data["head_name"] = head_name
            data["label"] = label
            with self._session.begin_nested():
                insert_one(
                    _T_HISTORY,
                    {
                        "model_id": model_id,
                        "event": _HISTORY_SNAPSHOT_EVENT,
                        "data": data,
                        "created_at": snapshot_at,
                    },
                    session=self._session,
                )
            self._session.commit()

    def list_calibration_history(
        self,
        model_id: str,
        head_name: str,
        label: str,
    ) -> list[CalibrationHistoryRecord]:
        """Return calibration history snapshots for one model/head/label, newest first.

        Scoped by the natural identity via JSONB head/label predicates (there are
        no dedicated columns).  Ordered ``created_at DESC`` with an ``id DESC``
        tiebreak for deterministic ordering of same-instant snapshots.
        """
        with map_persistence_exceptions():
            stmt = (
                select(_T_HISTORY)
                .where(*_history_identity_clauses(model_id, head_name, label))
                .order_by(_T_HISTORY.c.created_at.desc(), _T_HISTORY.c.id.desc())
            )
            result = self._session.execute(stmt)
            return [_row_to_history_record(r) for r in result.all()]

    def get_latest_calibration_history_snapshot(
        self,
        model_id: str,
        head_name: str,
        label: str,
    ) -> CalibrationHistoryRecord | None:
        """Return the single newest calibration history snapshot for one identity, or None."""
        with map_persistence_exceptions():
            stmt = (
                select(_T_HISTORY)
                .where(*_history_identity_clauses(model_id, head_name, label))
                .order_by(_T_HISTORY.c.created_at.desc(), _T_HISTORY.c.id.desc())
                .limit(1)
            )
            result = self._session.execute(stmt)
            row = result.fetchone()
            return _row_to_history_record(row) if row else None

    def count_calibration_history(self, model_id: str, head_name: str, label: str) -> int:
        """Return ``COUNT(*)`` of calibration history snapshots for one identity.

        Database-side count — replaces the fetch-all-and-``len`` anti-pattern.
        """
        with map_persistence_exceptions():
            stmt = select(func.count(_T_HISTORY.c.id)).where(*_history_identity_clauses(model_id, head_name, label))
            result = self._session.execute(stmt)
            return int(result.scalar_one())

    def remove_calibration_history(
        self,
        model_id: str,
        head_name: str,
        label: str,
        keep_count: int,
    ) -> int:
        """Retain the NEWEST ``keep_count`` snapshots for one identity, delete the rest.

        Natural-identity keep-count retention intent, not a primary-key list.
        ``keep_count`` is the number of newest snapshots kept; ``keep_count=0``
        deletes all snapshots for the identity; a negative ``keep_count`` raises
        ``ValueError``.  Implemented as a single set-based ``DELETE`` (the rows to
        keep are selected by ``created_at DESC, id DESC LIMIT keep_count``) — no
        Python row-by-row filtering.  Returns the number of rows removed.
        """
        if keep_count < 0:
            raise ValueError(f"keep_count must be non-negative, got {keep_count}")
        identity = _history_identity_clauses(model_id, head_name, label)
        stmt = delete(_T_HISTORY).where(*identity)
        if keep_count > 0:
            keep_ids = (
                select(_T_HISTORY.c.id)
                .where(*identity)
                .order_by(_T_HISTORY.c.created_at.desc(), _T_HISTORY.c.id.desc())
                .limit(keep_count)
            )
            stmt = delete(_T_HISTORY).where(*identity, ~_T_HISTORY.c.id.in_(keep_ids))
        with map_persistence_exceptions():
            with self._session.begin_nested():
                result = cast("CursorResult[Any]", self._session.execute(stmt))
            removed = result.rowcount
            self._session.commit()
            return int(removed)

    def truncate_history(self) -> None:
        """Delete all rows from ``calibration_history`` (full reset)."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._session.execute(delete(_T_HISTORY))
            self._session.commit()

    def delete_history_for_model(self, model_id: str) -> None:
        """Delete all calibration history entries for a model."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                stmt = delete(_T_HISTORY).where(_T_HISTORY.c.model_id == model_id)
                self._session.execute(stmt)
            self._session.commit()

    def delete_history_entries(self, entry_ids: list[int]) -> None:
        """Delete calibration history entries by primary key list.

        .. note::
           Repository-internal maintenance only.  Not part of the caller-facing
           contract: the natural-identity retention intent
           :meth:`remove_calibration_history` is the sanctioned path.  The
           ``ml.py`` facade no longer calls this (Plan C removed the
           ``remove_calibration_history_entries`` shim), so it remains a
           repository-internal maintenance helper.
        """
        with map_persistence_exceptions():
            with self._session.begin_nested():
                stmt = delete(_T_HISTORY).where(_T_HISTORY.c.id.in_(entry_ids))
                self._session.execute(stmt)
            self._session.commit()
