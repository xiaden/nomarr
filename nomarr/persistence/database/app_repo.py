"""AppRepository — KV-table operations for locks, health, meta, sessions, etc.

Groups multiple KV-table operations under one repository.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import Table, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nomarr.helpers.dto.repo_dto import (
    HealthRow,
    LockRow,
    MetaRow,
    SessionRow,
    WorkerClaimRow,
)
from nomarr.persistence.exceptions import DuplicateKeyError
from nomarr.persistence.models.applied_migration import AppliedMigration
from nomarr.persistence.models.health import Health
from nomarr.persistence.models.lock import Lock
from nomarr.persistence.models.meta import Meta
from nomarr.persistence.models.session import Session
from nomarr.persistence.models.vram_promise import VramPromise
from nomarr.persistence.models.worker_claim import WorkerClaim
from nomarr.persistence.models.worker_restart_policy import WorkerRestartPolicy
from nomarr.persistence.sql.primitives import (
    delete_by_key,
    insert_one,
    select_by_key,
    update_by_field,
    upsert_by_field,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Row
    from sqlalchemy.ext.asyncio import AsyncSession

_L: Table = Lock.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table
_H: Table = Health.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table
_M: Table = Meta.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table
_S: Table = Session.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table
_WC: Table = WorkerClaim.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table
_AM: Table = AppliedMigration.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table
_VP: Table = VramPromise.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table
_WRP: Table = WorkerRestartPolicy.__table__  # type: ignore[assignment]  # Model.__table__ is typed as FromClause; we know it's Table


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
    return WorkerClaimRow(
        id=m["id"],
        worker_id=m["worker_id"],
        key=m["key"],
        value=m["value"],
        claimed_at=m["claimed_at"],
    )


class AppRepository:
    """Repository grouping KV-table operations (locks, health, meta, …)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Lock ────────────────────────────────────────────────────

    async def insert_lock(self, payload: dict[str, Any]) -> str:
        """Insert a lock row and return the lock key."""
        row = await insert_one(_L, payload, session=self._session)
        await self._session.commit()
        return str(row._mapping["key"])

    async def upsert_lock(self, resource_id: str, payload: dict[str, Any]) -> None:
        """Insert-or-update a lock keyed on *resource_id*."""
        data = {"key": resource_id, **payload}
        await upsert_by_field(_L, "key", resource_id, data, session=self._session)
        await self._session.commit()

    async def release_lock(self, resource_id: str) -> None:
        """Delete a lock by its resource key."""
        await delete_by_key(_L, resource_id, session=self._session, key_col="key")
        await self._session.commit()

    async def get_lock(self, resource_id: str) -> LockRow | None:
        """Fetch a lock row by resource key."""
        row = await select_by_key(_L, resource_id, session=self._session, key_col="key")
        return _lock_row_to_dto(row) if row else None

    async def acquire_lock(self, resource_id: str, payload: dict[str, Any]) -> bool:
        """Try to insert a lock; return ``False`` if it already exists."""
        data = {"key": resource_id, **payload}
        try:
            await insert_one(_L, data, session=self._session)
            await self._session.commit()
            return True
        except DuplicateKeyError:
            await self._session.rollback()
            return False

    async def list_locks(self) -> list[LockRow]:
        """Return all lock rows."""
        result = await self._session.execute(select(_L))
        return [_lock_row_to_dto(r) for r in result.all()]

    # ── Health ──────────────────────────────────────────────────

    async def get_health(self, component_id: str) -> HealthRow | None:
        """Fetch health by ``worker_id``."""
        stmt = select(_H).where(_H.c.worker_id == component_id)
        result = await self._session.execute(stmt)
        row = result.fetchone()
        return _health_row_to_dto(row) if row else None

    async def count_healthy(self) -> int:
        """Count rows where ``status = 'healthy'``."""
        stmt = select(func.count()).select_from(_H).where(_H.c.status == "healthy")
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def list_worker_health(self) -> list[HealthRow]:
        """Return all worker health rows."""
        result = await self._session.execute(select(_H))
        return [_health_row_to_dto(r) for r in result.all()]

    async def upsert_health(self, component_id: str, fields: dict[str, Any]) -> None:
        """Insert-or-update a health row keyed on ``worker_id``."""
        data = {"worker_id": component_id, **fields}
        await upsert_by_field(_H, "worker_id", component_id, data, session=self._session)
        await self._session.commit()

    async def update_health(self, component_id: str, fields: dict[str, Any]) -> None:
        """Update fields on a health row keyed on ``worker_id``."""
        await update_by_field(_H, "worker_id", component_id, fields, session=self._session)
        await self._session.commit()

    # ── Meta ────────────────────────────────────────────────────

    async def get_meta(self, key: str) -> MetaRow | None:
        """Fetch a meta row by key."""
        row = await select_by_key(_M, key, session=self._session, key_col="key")
        return _meta_row_to_dto(row) if row else None

    async def upsert_meta(self, key: str, payload: dict[str, Any]) -> None:
        """Insert-or-update a meta row keyed on *key*."""
        data = {"key": key, **payload}
        await upsert_by_field(_M, "key", key, data, session=self._session)
        await self._session.commit()

    async def delete_meta(self, key: str) -> None:
        """Delete a meta row by key."""
        await delete_by_key(_M, key, session=self._session, key_col="key")
        await self._session.commit()

    async def list_meta_keys_by_prefix(self, prefix: str) -> list[str]:
        """Return meta keys matching ``prefix%``."""
        stmt = select(_M.c.key).where(_M.c.key.like(prefix + "%"))
        result = await self._session.execute(stmt)
        return [row[0] for row in result.all()]

    # ── Session ─────────────────────────────────────────────────

    async def insert_session(self, payloads: list[dict[str, Any]]) -> None:
        """Batch-insert session rows."""
        if not payloads:
            return
        await self._session.execute(pg_insert(_S).values(payloads))
        await self._session.commit()

    async def delete_session(self, session_id: str) -> None:
        """Delete a session by primary key."""
        await delete_by_key(_S, session_id, session=self._session, key_col="id")
        await self._session.commit()

    async def get_sessions_expiring_before(self, timestamp_ms: int, limit: int) -> list[SessionRow]:
        """Return sessions expiring before *timestamp_ms*."""
        stmt = select(_S).where(_S.c.expires_at < timestamp_ms).limit(limit)
        result = await self._session.execute(stmt)
        return [_session_row_to_dto(r) for r in result.all()]

    async def get_active_sessions(self, not_before_ms: int, limit: int) -> list[SessionRow]:
        """Return sessions whose expiry is at or after *not_before_ms*."""
        stmt = select(_S).where(_S.c.expires_at >= not_before_ms).limit(limit)
        result = await self._session.execute(stmt)
        return [_session_row_to_dto(r) for r in result.all()]

    async def count_sessions(self) -> int:
        """Return total session count."""
        stmt = select(func.count()).select_from(_S)
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    # ── Worker claims ───────────────────────────────────────────

    async def insert_worker_claim(self, payload: dict[str, Any]) -> int:
        """Insert a worker-claim row and return its ``id``."""
        row = await insert_one(_WC, payload, session=self._session)
        await self._session.commit()
        return int(row._mapping["id"])

    async def claim_file(self, file_id: int, worker_id: str, payload: dict[str, Any]) -> None:
        """Record a worker's claim on a file."""
        data = {
            "worker_id": worker_id,
            "key": str(file_id),
            "value": payload,
            "claimed_at": payload.get("claimed_at", 0),
        }
        await insert_one(_WC, data, session=self._session)
        await self._session.commit()

    async def release_claim(self, file_id: int) -> None:
        """Release a file claim by its key (``str(file_id)``)."""
        stmt = delete(_WC).where(_WC.c.key == str(file_id))
        await self._session.execute(stmt)
        await self._session.commit()

    async def delete_claims_for_workers(self, worker_ids: list[str]) -> int:
        """Delete all claims for the given worker ids; return row count."""
        if not worker_ids:
            return 0
        stmt = delete(_WC).where(_WC.c.worker_id.in_(worker_ids))
        result = await self._session.execute(stmt)
        await self._session.commit()
        return int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult vs Result — mypy sees Result but .rowcount exists at runtime

    async def delete_claims_for_files(self, file_ids: list[int]) -> int:
        """Delete claims for the given file ids (stored as ``key`` strings)."""
        if not file_ids:
            return 0
        str_ids = [str(fid) for fid in file_ids]
        stmt = delete(_WC).where(_WC.c.key.in_(str_ids))
        result = await self._session.execute(stmt)
        await self._session.commit()
        return int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult vs Result — mypy sees Result but .rowcount exists at runtime

    async def steal_claim(self, payload: dict[str, Any], now: int, lease_ms: int) -> bool:
        """Steal an expired claim (``claimed_at + lease_ms < now``).

        Returns ``True`` if a row was updated.
        """
        stmt = update(_WC).where(_WC.c.claimed_at + lease_ms < now).values(**payload)
        result = await self._session.execute(stmt)
        await self._session.commit()
        return int(result.rowcount) > 0  # type: ignore[attr-defined]  # CursorResult vs Result — mypy sees Result but .rowcount exists at runtime

    async def list_claims(self) -> list[WorkerClaimRow]:
        """Return all worker-claim rows."""
        result = await self._session.execute(select(_WC))
        return [_claim_row_to_dto(r) for r in result.all()]

    # ── Migrations ──────────────────────────────────────────────

    async def upsert_migration(self, name: str, fields: dict[str, Any]) -> None:
        """Insert-or-update a migration record keyed on *name*."""
        data = {"name": name, **fields}
        await upsert_by_field(_AM, "name", name, data, session=self._session)
        await self._session.commit()

    async def list_migrations(self) -> list[dict[str, Any]]:
        """Return all migration records as dicts."""
        result = await self._session.execute(select(_AM))
        return [dict(r._mapping) for r in result.all()]

    # ── VRAM promises ───────────────────────────────────────────

    async def upsert_vram_promise(self, payload: dict[str, Any]) -> None:
        """Insert-or-update a VRAM promise keyed on ``id``."""
        promise_id = payload["id"]
        await upsert_by_field(_VP, "id", promise_id, payload, session=self._session)
        await self._session.commit()

    async def get_vram_promises(self) -> list[dict[str, Any]]:
        """Return all VRAM promise rows as dicts."""
        result = await self._session.execute(select(_VP))
        return [dict(r._mapping) for r in result.all()]

    async def delete_vram_promise(self, promise_id: int) -> None:
        """Delete a VRAM promise by primary key."""
        await delete_by_key(_VP, promise_id, session=self._session)
        await self._session.commit()

    # ── Worker restart policy ───────────────────────────────────

    async def get_worker_restart_policy(self, component_id: str) -> dict[str, Any] | None:
        """Return ``policy_data`` for a component, or ``None``."""
        stmt = select(_WRP).where(_WRP.c.component_id == component_id)
        result = await self._session.execute(stmt)
        row = result.fetchone()
        if row is None:
            return None
        return dict(row._mapping["policy_data"])

    async def upsert_worker_restart_policy(self, component_id: str, fields: dict[str, Any]) -> None:
        """Insert-or-update a restart policy keyed on ``component_id``."""
        data = {"component_id": component_id, **fields}
        await upsert_by_field(_WRP, "component_id", component_id, data, session=self._session)
        await self._session.commit()

    # ── maintenance ─────────────────────────────────────────────

    async def truncate_worker_claims(self) -> None:
        """Delete all rows from ``worker_claims``."""
        await self._session.execute(delete(_WC))
        await self._session.commit()

    async def truncate_health(self) -> None:
        """Delete all rows from ``worker_health``."""
        await self._session.execute(delete(_H))
        await self._session.commit()

    async def delete_sessions_by_ids(self, session_ids: list[str]) -> None:
        """Batch-delete sessions by their ids."""
        if not session_ids:
            return
        stmt = delete(_S).where(_S.c.id.in_(session_ids))
        await self._session.execute(stmt)
        await self._session.commit()
