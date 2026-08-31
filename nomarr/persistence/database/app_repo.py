"""AppRepository — KV-table operations for locks, health, meta, sessions, etc.

Groups multiple KV-table operations under one repository.
Note: This file is ~413 lines covering 8 KV-style table operations. If it
grows further, consider splitting into sub-repos (e.g. app_lock_repo.py,
app_health_repo.py, app_session_repo.py, app_claim_repo.py).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import Table, delete, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nomarr.helpers.dataclasses.app_dataclasses import (
    CapacityEstimate,
    ConfigOption,
    GpuResourceSnapshot,
    ModelVramLimit,
)
from nomarr.helpers.dataclasses.app_dataclasses import (
    VramPromise as DomainVramPromise,
)
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

    from nomarr.persistence.database.song_repo import SongRepository

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
    value = cast("dict[str, Any]", m["value"])
    result: WorkerClaimRow = {
        "id": cast("int", m["id"]),
        "worker_id": cast("str", m["worker_id"]),
        "key": cast("str", m["key"]),
        "value": value,
        "claimed_at": cast("int", m["claimed_at"]),
    }
    if "file_id" in value:
        result["file_id"] = cast("str | int", value["file_id"])
    if "claim_type" in value:
        result["claim_type"] = cast("str", value["claim_type"])
    return result


class AppRepository:
    """Repository grouping KV-table operations (locks, health, meta, …)."""

    def __init__(self, session: scoped_session[Session], song_repo: SongRepository | None = None) -> None:
        self._session = session
        self._song_repo = song_repo

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
                data = {"key": resource_id, "value": payload["value"]}
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
        data = {"key": resource_id, "value": payload["value"]}
        try:
            with map_persistence_exceptions():
                with self._session.begin_nested():
                    insert_one(_L, data, session=self._session)
                self._session.commit()
            return True
        except DuplicateEntityError:
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
                data = {**fields, "worker_id": component_id}
                existing = self._session.execute(select(_H.c.worker_id).where(_H.c.worker_id == component_id)).first()
                if existing:
                    update_by_field(_H, "worker_id", component_id, fields, session=self._session)
                else:
                    insert_one(_H, data, session=self._session)
            self._session.commit()

    def update_health(self, component_id: str, fields: dict[str, Any]) -> None:
        """Insert or update a health row keyed on ``worker_id``.

        Health rows are recreated by startup maintenance, so an update-only
        write cannot be used by the runtime telemetry path.  Keep the write
        constrained to the actual ``worker_health`` columns.
        """
        data = {key: value for key, value in fields.items() if key in {"status", "last_seen"}}
        if not data:
            return

        with map_persistence_exceptions():
            with self._session.begin_nested():
                existing = self._session.execute(select(_H.c.worker_id).where(_H.c.worker_id == component_id)).first()
                if existing:
                    update_by_field(_H, "worker_id", component_id, data, session=self._session)
                else:
                    insert_one(_H, {**data, "worker_id": component_id}, session=self._session)
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
                data = {**payload, "key": key}
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

    def _delete_meta_keys_atomic(self, keys: list[str]) -> None:
        """Delete multiple meta rows in a single transaction."""
        if not keys:
            return
        with map_persistence_exceptions():
            with self._session.begin_nested():
                for key in keys:
                    delete_by_key(_M, key, session=self._session, key_col="key")
            self._session.commit()

    # ── Semantic config / app-state methods ──────────────────────
    # These map domain inputs/returns onto the raw meta primitives above. They
    # intentionally never expose raw storage rows, payload dicts, or key encodings
    # to higher layers.

    def get_config_option(self, key: str) -> ConfigOption | None:
        """Return a user configuration value by its full storage identity."""
        row = self.get_meta(key)
        return ConfigOption(key=row["key"], value=row["value"]) if row is not None else None

    def list_config_options(self) -> list[ConfigOption]:
        """Return every ``config_*`` configuration value."""
        results: list[ConfigOption] = []
        for key in self.list_meta_keys_by_prefix("config_"):
            row = self.get_meta(key)
            if row is not None:
                results.append(ConfigOption(key=row["key"], value=row["value"]))
        return results

    def set_config_option(self, key: str, value: Any) -> None:
        """Persist a user configuration value under its full storage identity."""
        self.upsert_meta(key, {"value": value})

    def remove_config_option(self, key: str) -> None:
        """Remove a user configuration value by its full storage identity."""
        self.delete_meta(key)

    def get_schema_version(self) -> str | None:
        """Return the schema version, coercing non-string stored values to ``str``."""
        row = self.get_meta("version")
        if row is None:
            return None
        value = row["value"]
        return str(value) if value is not None else None

    def set_schema_version(self, version: str) -> None:
        """Persist the schema version."""
        self.upsert_meta("version", {"value": version})

    def get_api_key(self) -> str | None:
        """Return the stored API key, or ``None`` when not set."""
        row = self.get_meta("api_key")
        return cast("str", row["value"]) if row is not None else None

    def set_api_key(self, value: str) -> None:
        """Persist the API key."""
        self.upsert_meta("api_key", {"value": value})

    def get_admin_password_hash(self) -> str | None:
        """Return the stored admin password hash, or ``None`` when not set."""
        row = self.get_meta("admin_password_hash")
        return cast("str", row["value"]) if row is not None else None

    def set_admin_password_hash(self, value: str) -> None:
        """Persist the admin password hash."""
        self.upsert_meta("admin_password_hash", {"value": value})

    def get_calibration_version(self) -> str | None:
        """Return the calibration version hash, or ``None`` when not set."""
        row = self.get_meta("calibration_version")
        return cast("str", row["value"]) if row is not None else None

    def set_calibration_version(self, version_hash: str) -> None:
        """Persist the calibration version hash."""
        self.upsert_meta("calibration_version", {"value": version_hash})

    def get_calibration_last_run(self) -> int | None:
        """Return the calibration last-run timestamp (ms), or ``None`` when not set."""
        row = self.get_meta("calibration_last_run")
        if row is None:
            return None
        value = row["value"]
        return int(cast("str", value)) if value is not None else None

    def set_calibration_last_run(self, timestamp_ms: str) -> None:
        """Persist the calibration last-run timestamp as a string (read back as int)."""
        self.upsert_meta("calibration_last_run", {"value": timestamp_ms})

    def clear_calibration_metadata(self) -> int:
        """Atomically clear calibration bookkeeping values; return how many were removed."""
        keys = [k for k in ("calibration_version", "calibration_last_run") if self.get_meta(k) is not None]
        self._delete_meta_keys_atomic(keys)
        return len(keys)

    def get_model_vram_limit(self, model_path: str) -> int | None:
        """Return a model's VRAM limit in bytes, or ``None`` when not measured."""
        row = self.get_meta(f"ml_model_vram:{model_path}")
        if row is None:
            return None
        return int(cast("str", row["value"]))

    def set_model_vram_limit(self, model_path: str, limit_bytes: int) -> None:
        """Persist a model's VRAM limit in bytes (stored as a string)."""
        self.upsert_meta(f"ml_model_vram:{model_path}", {"value": str(limit_bytes)})

    def list_model_vram_limits(self) -> list[ModelVramLimit]:
        """Return every stored per-model VRAM limit as a domain value."""
        prefix = "ml_model_vram:"
        results: list[ModelVramLimit] = []
        for key in self.list_meta_keys_by_prefix(prefix):
            row = self.get_meta(key)
            if row is not None:
                results.append(
                    ModelVramLimit(model_path=key[len(prefix) :], limit_bytes=int(cast("str", row["value"])))
                )
        return results

    def clear_model_vram_limits(self) -> int:
        """Atomically clear all stored VRAM limits; return how many were removed."""
        keys = self.list_meta_keys_by_prefix("ml_model_vram:")
        self._delete_meta_keys_atomic(keys)
        return len(keys)

    def get_capacity_estimate(self, model_set_hash: str) -> CapacityEstimate | None:
        """Return the stored capacity estimate for a model set, or ``None``."""
        row = self.get_meta(f"capacity_estimate:{model_set_hash}")
        if row is None:
            return None
        value = row["value"]
        return CapacityEstimate(
            model_set_hash=value.get("model_set_hash", model_set_hash),
            measured_backbone_vram_mb=value["measured_backbone_vram_mb"],
            estimated_worker_ram_mb=value["estimated_worker_ram_mb"],
            gpu_capable=value.get("gpu_capable", False),
            is_conservative=value.get("is_conservative", False),
        )

    def set_capacity_estimate(self, estimate: CapacityEstimate) -> None:
        """Persist a capacity estimate for its model set."""
        self.upsert_meta(
            f"capacity_estimate:{estimate.model_set_hash}",
            {"value": asdict(estimate)},
        )

    def remove_capacity_estimate(self, model_set_hash: str) -> None:
        """Remove the stored capacity estimate for a model set."""
        self.delete_meta(f"capacity_estimate:{model_set_hash}")

    def get_gpu_resource_snapshot(self) -> GpuResourceSnapshot | None:
        """Return the stored GPU resource snapshot, or ``None`` when absent."""
        row = self.get_meta("gpu_resources")
        if row is None:
            return None
        value = row["value"]
        return GpuResourceSnapshot(
            gpu_available=bool(value.get("gpu_available", False)),
            error_summary=value.get("error_summary"),
        )

    def set_gpu_resource_snapshot(self, snapshot: GpuResourceSnapshot) -> None:
        """Persist a GPU resource snapshot."""
        self.upsert_meta(
            "gpu_resources",
            {"value": {"gpu_available": snapshot.gpu_available, "error_summary": snapshot.error_summary}},
        )

    def get_worker_system_enabled(self) -> bool | None:
        """Return whether the worker system is enabled, or ``None`` when not set."""
        row = self.get_meta("worker_enabled")
        if row is None:
            return None
        return row["value"] == "true"

    def set_worker_system_enabled(self, enabled: bool) -> None:
        """Persist the worker-system enabled state as a boolean."""
        self.upsert_meta("worker_enabled", {"value": "true" if enabled else "false"})

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

    def get_sessions_expiring_before(self, timestamp_ms: int, limit: int | None = None) -> list[SessionRow]:
        """Return sessions expiring before *timestamp_ms*."""
        with map_persistence_exceptions():
            stmt = select(_S).where(_S.c.expires_at < timestamp_ms)
            if limit is not None:
                stmt = stmt.limit(limit)
            result = self._session.execute(stmt)
            return [_session_row_to_dto(r) for r in result.all()]

    def get_active_sessions(self, not_before_ms: int, limit: int | None = None) -> list[SessionRow]:
        """Return sessions whose expiry is at or after *not_before_ms*."""
        with map_persistence_exceptions():
            stmt = select(_S).where(_S.c.expires_at >= not_before_ms)
            if limit is not None:
                stmt = stmt.limit(limit)
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
        file_id = payload.get("file_id")
        if file_id is not None and self._song_repo is not None and self._song_repo.get_song(file_id) is None:
            raise ValueError(f"Song {file_id} does not exist")
        with map_persistence_exceptions():
            with self._session.begin_nested():
                data = {
                    "worker_id": payload["worker_id"],
                    "key": payload["key"],
                    "value": {
                        **dict(payload.get("value", {})),
                        **{key: payload[key] for key in ("file_id", "claim_type") if key in payload},
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

    def release_claim(
        self,
        worker_id: str | int,
        song_id: int | None = None,
        claim_type: str | None = None,
    ) -> None:
        """Release one worker's claim for a song."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                worker_filter: str | None = worker_id if isinstance(worker_id, str) else None
                if song_id is None:
                    song_id = int(worker_id)
                prefix = f"claim_{claim_type}_" if claim_type else "claim_"
                stmt = delete(_WC).where(
                    _WC.c.key == f"{prefix}{song_id}",
                )
                if worker_filter is not None:
                    stmt = stmt.where(_WC.c.worker_id == worker_filter)
                self._session.execute(stmt)
            self._session.commit()

    def release_claim_by_song(self, song_id: int, claim_type: str | None = None) -> None:
        """Release a song claim regardless of which worker owns it."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                prefix = f"claim_{claim_type}_" if claim_type else "claim_"
                stmt = delete(_WC).where(_WC.c.key == f"{prefix}{song_id}")
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

    def delete_claims(
        self,
        *,
        worker_ids: list[str] | None = None,
        song_ids: list[int] | None = None,
    ) -> int:
        """Delete claims matching either worker or song filters atomically."""
        with map_persistence_exceptions():
            if not worker_ids and not song_ids:
                return 0

            filters = []
            if worker_ids:
                filters.append(_WC.c.worker_id.in_(worker_ids))
            if song_ids:
                claim_keys = [
                    condition
                    for sid in song_ids
                    for condition in (
                        _WC.c.key == f"claim_{sid}",
                        _WC.c.key.like(f"claim_%_{sid}"),
                    )
                ]
                filters.append(or_(*claim_keys))

            with self._session.begin_nested():
                stmt = delete(_WC).where(or_(*filters))
                result = self._session.execute(stmt)
            self._session.commit()
            return int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult vs Result — mypy sees Result but .rowcount exists at runtime

    def delete_claims_for_songs(self, song_ids: list[int]) -> int:
        """Delete claims for the given song ids (stored as ``key`` strings)."""
        with map_persistence_exceptions():
            if not song_ids:
                return 0
            claim_keys = [
                condition
                for sid in song_ids
                for condition in (
                    _WC.c.key == f"claim_{sid}",
                    _WC.c.key.like(f"claim_%_{sid}"),
                )
            ]
            with self._session.begin_nested():
                stmt = delete(_WC).where(or_(*claim_keys))
                result = self._session.execute(stmt)
            self._session.commit()
            return int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult vs Result — mypy sees Result but .rowcount exists at runtime

    def steal_claim(self, payload: dict[str, Any], now: int, lease_ms: int) -> bool:
        """Atomically replace one expired claim.

        The claim key is part of the update predicate, and the expiry check is
        evaluated by the database in the same ``UPDATE`` statement.  A caller
        therefore cannot delete a claim that another worker acquired after it
        read the old claim.

        Returns ``True`` if the targeted expired row was updated.
        """
        key = payload["key"]
        data = {
            "worker_id": payload["worker_id"],
            "value": payload["value"],
            "claimed_at": payload["claimed_at"],
        }
        with map_persistence_exceptions():
            with self._session.begin_nested():
                stmt = (
                    update(_WC)
                    .where(
                        _WC.c.key == key,
                        _WC.c.claimed_at < now - lease_ms,
                    )
                    .values(**data)
                )
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
                data = {**fields, "name": name}
                upsert_by_field(_AM, "name", name, data, session=self._session)
            self._session.commit()

    def list_migrations(self) -> list[dict[str, Any]]:
        """Return all migration records as dicts."""
        with map_persistence_exceptions():
            result = self._session.execute(select(_AM))
            return [dict(r._mapping) for r in result.all()]

    # ── VRAM promises ───────────────────────────────────────────

    def insert_vram_promise(
        self,
        *,
        worker_id: str,
        pid: int,
        model_path: str,
        promised_mb: float,
        total_mb: float,
        used_mb: float,
    ) -> None:
        """Insert one VRAM promise, leaving generated ids repository-internal."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                self._session.execute(
                    insert(_VP).values(
                        worker_id=worker_id,
                        pid=pid,
                        model_path=model_path,
                        promised_mb=promised_mb,
                        total_mb=total_mb,
                        used_mb=used_mb,
                    )
                )
            self._session.commit()

    def get_vram_promises(self) -> list[DomainVramPromise]:
        """Return VRAM promises as domain values, hiding row identifiers."""
        with map_persistence_exceptions():
            result = self._session.execute(select(_VP))
            return [
                DomainVramPromise(
                    worker_id=row.worker_id,
                    pid=row.pid,
                    model_path=row.model_path,
                    promised_mb=row.promised_mb,
                    total_mb=row.total_mb,
                    used_mb=row.used_mb,
                )
                for row in result
            ]

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

    def count_vram_promises(self) -> int:
        """Return the number of currently persisted VRAM promises."""
        with map_persistence_exceptions():
            result = self._session.execute(select(func.count()).select_from(_VP))
            return int(result.scalar_one())

    def delete_vram_promises_by_worker(self, worker_id: str) -> int:
        """Delete every VRAM promise owned by a worker; return row count.

        This is one database ``DELETE`` statement, enclosed by the
        repository's savepoint/commit transaction. With PostgreSQL's default
        READ COMMITTED isolation, the statement targets promises visible when
        the DELETE starts. A promise committed after that statement snapshot
        is a new promise and may remain for a subsequent release; no
        read-modify-write snapshot is exposed to the facade.
        """
        with map_persistence_exceptions():
            with self._session.begin_nested():
                stmt = delete(_VP).where(_VP.c.worker_id == worker_id)
                result = self._session.execute(stmt)
            self._session.commit()
            return int(result.rowcount)  # type: ignore[attr-defined]  # CursorResult vs Result — mypy sees Result but .rowcount exists at runtime

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
                data = {"component_id": component_id, "policy_data": {**fields}}
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
