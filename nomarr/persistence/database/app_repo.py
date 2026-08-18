"""AppRepository — KV-table operations for locks, health, meta, sessions, etc.

Groups multiple KV-table operations under one repository.
Note: This file is ~413 lines covering 8 KV-style table operations. If it
grows further, consider splitting into sub-repos (e.g. app_lock_repo.py,
app_health_repo.py, app_session_repo.py, app_claim_repo.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import Table, delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nomarr.helpers.dto.repo_dto import (
    HealthRow,
    LockRow,
    MetaRow,
    SessionRow,
    WorkerClaimRow,
)
from nomarr.helpers.exceptions import DuplicateEntityError
from nomarr.persistence.models.applied_migration import AppliedMigration
from nomarr.persistence.models.health import Health
from nomarr.persistence.models.lock import Lock
from nomarr.persistence.models.meta import Meta
from nomarr.persistence.models.session import (
    Session as SessionModel,
)
from nomarr.persistence.models.vram_promise import VramPromise
from nomarr.persistence.models.worker_claim import WorkerClaim
from nomarr.persistence.models.worker_restart_policy import WorkerRestartPolicy
from nomarr.persistence.sql.exceptions import map_persistence_exceptions
from nomarr.persistence.sql.primitives import (
    delete_by_key,
    insert_one,
    select_by_key,
    update_by_field,
    upsert_by_field,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Row
    from sqlalchemy.orm import Session, scoped_session

_L = cast("Table", Lock.__table__)
_H = cast("Table", Health.__table__)
_M = cast("Table", Meta.__table__)
_S = cast("Table", SessionModel.__table__)
_WC = cast("Table", WorkerClaim.__table__)
_AM = cast("Table", AppliedMigration.__table__)
_VP = cast("Table", VramPromise.__table__)
_WRP = cast("Table", WorkerRestartPolicy.__table__)


# ── DTO helpers ─────────────────────────────────────────────────


def _lock_row_to_dto(row: Row) -> LockRow:
    m = row._mapping
    return LockRow(key=m["key"], value=m["value"])


def _health_row_to_dto(row: Row) -> HealthRow:
    m = row._mapping
    return HealthRow(
        id=m["id"],
        worker_id=m["worker_id"],
        status=m["status"],
        last_seen=m["last_seen"],
    )


def _meta_row_to_dto(row: Row) -> MetaRow:
    m = row._mapping
    return MetaRow(key=m["key"], value=m["value"])


def _session_row_to_dto(row: Row) -> SessionRow:
    m = row._mapping
    return SessionRow(
        id=m["id"],
        data=m["data"],
        expires_at=m["expires_at"],
    )


def _claim_row_to_dto(row: Row) -> WorkerClaimRow:
    m = row._mapping
    value = m["value"]
    claim_fields = {key: value[key] for key in ("file_id", "claim_type") if key in value}
    return WorkerClaimRow(
        id=m["id"],
        worker_id=m["worker_id"],
        key=m["key"],
        value=value,
        claimed_at=m["claimed_at"],
        **claim_fields,
    )


class AppRepository:
    """Repository grouping KV-table operations (locks, health, meta, …)."""

    def __init__(self, session: scoped_session[Session]) -> None:
        self._session = session

    # ── Lock ────────────────────────────────────────────────────

    def insert_lock(self, payload: dict[str, Any]) -> str:
        """Insert a lock row and return the lock key."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                row = insert_one(_L, payload, session=self._session)
            self._session.commit()
            return str(row._mapping["key"])

    def upsert_lock(self, resource_id: str, payload: dict[str, Any]) -> None:
        """Insert-or-update a lock keyed on *resource_id*."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                data = {"key": resource_id, **payload}
                upsert_by_field(_L, "key", resource_id, data, session=self._session)
            self._session.commit()

    def release_lock(self, resource_id: str) -> None:
        """Delete a lock by its resource key."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                delete_by_key(_L, resource_id, session=self._session, key_col="key")
            self._session.commit()

    def get_lock(self, resource_id: str) -> LockRow | None:
        """Fetch a lock row by resource key."""
        with map_persistence_exceptions():
            row = select_by_key(_L, resource_id, session=self._session, key_col="key")
            return _lock_row_to_dto(row) if row else None

    def acquire_lock(self, resource_id: str, payload: dict[str, Any]) -> bool:
        """Try to insert a lock; return ``False`` if it already exists."""
        data = {"key": resource_id, **payload}
        try:
            with map_persistence_exceptions():
                with self._session.begin_nested():
                    insert_one(_L, data, session=self._session)
                self._session.commit()
            return True
        except DuplicateEntityError:
            self._session.rollback()
            return False

    def list_locks(self) -> list[LockRow]:
        """Return all lock rows."""
        with map_persistence_exceptions():
            result = self._session.execute(select(_L))
            return [_lock_row_to_dto(r) for r in result.all()]

    # ── Health ──────────────────────────────────────────────────

    def get_health(self, component_id: str) -> HealthRow | None:
        """Fetch health by ``worker_id``."""
        with map_persistence_exceptions():
            stmt = select(_H).where(_H.c.worker_id == component_id)
            result = self._session.execute(stmt)
            row = result.fetchone()
            return _health_row_to_dto(row) if row else None

    def count_healthy(self) -> int:
        """Count rows where ``status = 'healthy'``."""
        with map_persistence_exceptions():
            stmt = select(func.count()).select_from(_H).where(_H.c.status == "healthy")
            result = self._session.execute(stmt)
            return result.scalar() or 0

    def list_worker_health(self) -> list[HealthRow]:
        """Return all worker health rows."""
        with map_persistence_exceptions():
            result = self._session.execute(select(_H))
            return [_health_row_to_dto(r) for r in result.all()]

    def upsert_health(self, component_id: str, fields: dict[str, Any]) -> None:
        """Insert-or-update a health row keyed on ``worker_id``."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                data = {"worker_id": component_id, **fields}
                upsert_by_field(_H, "worker_id", component_id, data, session=self._session)
            self._session.commit()

    def update_health(self, component_id: str, fields: dict[str, Any]) -> None:
        """Update fields on a health row keyed on ``worker_id``."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                update_by_field(_H, "worker_id", component_id, fields, session=self._session)
            self._session.commit()

    # ── Meta ────────────────────────────────────────────────────

    def get_meta(self, key: str) -> MetaRow | None:
        """Fetch a meta row by key."""
        with map_persistence_exceptions():
            row = select_by_key(_M, key, session=self._session, key_col="key")
            return _meta_row_to_dto(row) if row else None

    def upsert_meta(self, key: str, payload: dict[str, Any]) -> None:
        """Insert-or-update a meta row keyed on *key*."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                data = {"key": key, **payload}
                upsert_by_field(_M, "key", key, data, session=self._session)
            self._session.commit()

    def delete_meta(self, key: str) -> None:
        """Delete a meta row by key."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                delete_by_key(_M, key, session=self._session, key_col="key")
            self._session.commit()

    def list_meta_keys_by_prefix(self, prefix: str) -> list[str]:
        """Return meta keys matching ``prefix%``."""
        with map_persistence_exceptions():
            stmt = select(_M.c.key).where(_M.c.key.like(prefix + "%"))
            result = self._session.execute(stmt)
            return [row[0] for row in result.all()]

    # ── Session ─────────────────────────────────────────────────

    def insert_session(self, payloads: list[dict[str, Any]]) -> None:
        """Batch-insert session rows."""
        with map_persistence_exceptions():
            if not payloads:
                return
            with self._session.begin_nested():
                self._session.execute(pg_insert(_S).values(payloads))
            self._session.commit()

    def delete_session(self, session_id: str) -> None:
        """Delete a session by primary key."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                delete_by_key(_S, session_id, session=self._session, key_col="id")
            self._session.commit()

    def get_sessions_expiring_before(self, timestamp_ms: int, limit: int) -> list[SessionRow]:
        """Return sessions expiring before *timestamp_ms*."""
        with map_persistence_exceptions():
            stmt = select(_S).where(_S.c.expires_at < timestamp_ms).limit(limit)
            result = self._session.execute(stmt)
            return [_session_row_to_dto(r) for r in result.all()]

    def get_active_sessions(self, not_before_ms: int, limit: int) -> list[SessionRow]:
        """Return sessions whose expiry is at or after *not_before_ms*."""
        with map_persistence_exceptions():
            stmt = select(_S).where(_S.c.expires_at >= not_before_ms).limit(limit)
            result = self._session.execute(stmt)
            return [_session_row_to_dto(r) for r in result.all()]

    def count_sessions(self) -> int:
        """Return total session count."""
        with map_persistence_exceptions():
            stmt = select(func.count()).select_from(_S)
            result = self._session.execute(stmt)
            return result.scalar() or 0

    # ── Worker claims ───────────────────────────────────────────

    def insert_worker_claim(self, payload: dict[str, Any]) -> int:
        """Insert a worker-claim row and return its ``id``."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                data = {
                    "worker_id": payload["worker_id"],
                    "key": payload["key"],
                    "value": {
                        **dict(payload.get("value", {})),
                        **{
                            key: payload[key]
                            for key in ("file_id", "claim_type")
                            if key in payload
                        },
                    },
                    "claimed_at": payload.get("claimed_at", 0),
                }
                row = insert_one(_WC, data, session=self._session)
            self._session.commit()
            return int(row._mapping["id"])

    def claim_file(self, song_id: int, worker_id: str, payload: dict[str, Any]) -> None:
        """Record a worker's claim on a song."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                data = {
                    "worker_id": worker_id,
                    "key": f"claim_{song_id}",
                    "value": payload,
                    "claimed_at": payload.get("claimed_at", 0),
                }
                insert_one(_WC, data, session=self._session)
            self._session.commit()

    def release_claim(self, song_id: int) -> None:
        """Release a song claim by its deterministic claim key."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                keys = (f"claim_{song_id}", f"claim_reconcile_{song_id}")
                stmt = delete(_WC).where(_WC.c.key.in_(keys))
                self._session.execute(stmt)
            self._session.commit()

    def delete_claims_for_workers(self, worker_ids: list[str]) -> int:
        """Delete all claims for the given worker ids; return row count."""
        with map_persistence_exceptions():
            if not worker_ids:
                return 0
            with self._session.begin_nested():
                stmt = delete(_WC).where(_WC.c.worker_id.in_(worker_ids))
                result = self._session.execute(stmt)
            self._session.commit()
            return int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult vs Result — mypy sees Result but .rowcount exists at runtime

    def delete_claims_for_songs(self, song_ids: list[int]) -> int:
        """Delete claims for the given song ids (stored as ``key`` strings)."""
        with map_persistence_exceptions():
            if not song_ids:
                return 0
            str_ids = [key for sid in song_ids for key in (f"claim_{sid}", f"claim_reconcile_{sid}")]
            with self._session.begin_nested():
                stmt = delete(_WC).where(_WC.c.key.in_(str_ids))
                result = self._session.execute(stmt)
            self._session.commit()
            return int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult vs Result — mypy sees Result but .rowcount exists at runtime

    def steal_claim(self, payload: dict[str, Any], now: int, lease_ms: int) -> bool:
        """Steal an expired claim (``claimed_at + lease_ms < now``).

        Returns ``True`` if a row was updated.
        """
        with map_persistence_exceptions():
            with self._session.begin_nested():
                stmt = update(_WC).where(_WC.c.claimed_at + lease_ms < now).values(**payload)
                result = self._session.execute(stmt)
            self._session.commit()
            return int(result.rowcount) > 0  # type: ignore[attr-defined]  # CursorResult vs Result — mypy sees Result but .rowcount exists at runtime

    def list_claims(self) -> list[WorkerClaimRow]:
        """Return all worker-claim rows."""
        with map_persistence_exceptions():
            result = self._session.execute(select(_WC))
            return [_claim_row_to_dto(r) for r in result.all()]

    # ── Migrations ──────────────────────────────────────────────

    def upsert_migration(self, name: str, fields: dict[str, Any]) -> None:
        """Insert-or-update a migration record keyed on *name*."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                data = {"name": name, **fields}
                upsert_by_field(_AM, "name", name, data, session=self._session)
            self._session.commit()

    def list_migrations(self) -> list[dict[str, Any]]:
        """Return all migration records as dicts."""
        with map_persistence_exceptions():
            result = self._session.execute(select(_AM))
            return [dict(r._mapping) for r in result.all()]

    # ── VRAM promises ───────────────────────────────────────────

    def upsert_vram_promise(self, payload: dict[str, Any]) -> None:
        """Insert-or-update a VRAM promise keyed on ``id``.

        When ``payload`` has no ``id`` (e.g. a fresh promise from
        ``AppDb.promise_vram``), the row is plain-inserted and ``id`` is
        filled by the autoincrement column.
        """
        with map_persistence_exceptions():
            with self._session.begin_nested():
                if "id" not in payload:
                    self._session.execute(insert(_VP).values(**payload))
                else:
                    promise_id = payload["id"]
                    upsert_by_field(_VP, "id", promise_id, payload, session=self._session)
            self._session.commit()

    def get_vram_promises(self) -> list[dict[str, Any]]:
        """Return all VRAM promise rows as dicts."""
        with map_persistence_exceptions():
            result = self._session.execute(select(_VP))
            return [dict(r._mapping) for r in result.all()]

    def delete_vram_promise(self, promise_id: int) -> None:
        """Delete a VRAM promise by primary key."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                delete_by_key(_VP, promise_id, session=self._session)
            self._session.commit()

    def delete_vram_promise_by_worker_model(self, worker_id: str, model_path: str) -> int:
        """Delete all VRAM promises for a worker+model pair; return row count.

        Runs the delete in a single transaction that first locks the matching
        rows with ``SELECT ... FOR UPDATE``. This eliminates the read-
        modify-write race of the old adapter release (list-all, match,
        delete-by-id): concurrent releases can no longer miss rows. SQLite
        ignores ``FOR UPDATE`` (no-op) — the atomic no-stale semantics are
        still exercised by the concurrent integration test; true row-locking
        requires PostgreSQL (Docker, deferred).
        """
        with map_persistence_exceptions():
            with self._session.begin_nested():
                stmt = (
                    select(_VP.c.id)
                    .where(_VP.c.worker_id == worker_id, _VP.c.model_path == model_path)
                    .with_for_update()
                )
                rows = self._session.execute(stmt).all()
                ids = [row[0] for row in rows]
                deleted = 0
                if ids:
                    result = self._session.execute(delete(_VP).where(_VP.c.id.in_(ids)))
                    deleted = int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult vs Result — mypy sees Result but .rowcount exists at runtime
            self._session.commit()
            return deleted

    # ── Worker restart policy ───────────────────────────────────

    def get_worker_restart_policy(self, component_id: str) -> dict[str, Any] | None:
        """Return ``policy_data`` for a component, or ``None``."""
        with map_persistence_exceptions():
            stmt = select(_WRP).where(_WRP.c.component_id == component_id)
            result = self._session.execute(stmt)
            row = result.fetchone()
            if row is None:
                return None
            return dict(row._mapping["policy_data"])

    def upsert_worker_restart_policy(self, component_id: str, fields: dict[str, Any]) -> None:
        """Insert-or-update a restart policy keyed on ``component_id``."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                data = {"component_id": component_id, **fields}
                upsert_by_field(_WRP, "component_id", component_id, data, session=self._session)
            self._session.commit()

    # ── maintenance ─────────────────────────────────────────────

    def truncate_worker_claims(self) -> None:
        """Delete all rows from ``worker_claims``."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._session.execute(delete(_WC))
            self._session.commit()

    def truncate_health(self) -> None:
        """Delete all rows from ``worker_health``."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._session.execute(delete(_H))
            self._session.commit()

    def delete_sessions_by_ids(self, session_ids: list[str]) -> None:
        """Batch-delete sessions by their ids."""
        with map_persistence_exceptions():
            if not session_ids:
                return
            with self._session.begin_nested():
                stmt = delete(_S).where(_S.c.id.in_(session_ids))
                self._session.execute(stmt)
            self._session.commit()
