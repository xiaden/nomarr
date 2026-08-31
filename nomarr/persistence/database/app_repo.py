"""AppRepository — KV-table operations for locks, health, meta, sessions, etc.

Groups multiple KV-table operations under one repository.
Note: This file is ~936 lines and covers the app-domain KV-table and
bookkeeping operations. If it grows further, consider splitting into sub-repos
(e.g. app_lock_repo.py, app_health_repo.py, app_session_repo.py,
app_claim_repo.py).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import ColumnElement, Table, delete, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from nomarr.helpers.constants.file_states import STATE_ERRORED, STATE_PROCESSED
from nomarr.helpers.dataclasses.app_dataclasses import (
    CapacityEstimate,
    ConfigOption,
    GpuResourceSnapshot,
    ModelVramLimit,
)
from nomarr.helpers.dataclasses.app_dataclasses import (
    VramPromise as DomainVramPromise,
)
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.worker_claim_dataclass import (
    ClaimRemovalRequest,
    WorkerClaim,
    WorkerClaimIdentity,
)
from nomarr.helpers.dto.repo_dto import (
    HealthRow,
    LockRow,
    MetaRow,
    SessionRow,
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
from nomarr.persistence.models.worker_claim import WorkerClaim as WorkerClaimModel
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
    from collections.abc import Sequence

    from sqlalchemy.engine import Row
    from sqlalchemy.orm import Session, scoped_session

    from nomarr.persistence.database.library_repo import LibraryRepository
    from nomarr.persistence.database.song_repo import SongRepository
    from nomarr.persistence.database.song_state_repo import SongStateRepository

_L = cast("Table", Lock.__table__)
_H = cast("Table", Health.__table__)
_M = cast("Table", Meta.__table__)
_S = cast("Table", SessionModel.__table__)
_WC = cast("Table", WorkerClaimModel.__table__)
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


def _claim_key(claim_type: str | None, song_id: int) -> str:
    """Encode a claim's deterministic storage key.

    Untyped claims use ``claim_<song_id>``; typed claims use
    ``claim_<claim_type>_<song_id>``.  The key is the repository's private
    storage encoding — callers never see or construct it.
    """
    if claim_type is None:
        return f"claim_{song_id}"
    return f"claim_{claim_type}_{song_id}"


def _parse_claim_key(key: str) -> tuple[int, str | None] | None:
    """Parse a storage claim key back to ``(song_id, claim_type)``.

    Returns ``None`` for a non-conforming or orphaned key so the repository can
    quarantine/ignore it rather than exposing it to the domain boundary.
    """
    if not key.startswith("claim_"):
        return None
    rest = key[len("claim_") :]
    if not rest:
        return None
    if rest.isdigit():
        return int(rest), None
    sep = rest.rfind("_")
    if sep <= 0:
        return None
    suffix = rest[sep + 1 :]
    if not suffix.isdigit():
        return None
    return int(suffix), rest[:sep]


class AppRepository:
    """Repository grouping KV-table operations (locks, health, meta, …)."""

    def __init__(
        self,
        session: scoped_session[Session],
        song_repo: SongRepository | None = None,
        library_repo: LibraryRepository | None = None,
        song_state_repo: SongStateRepository | None = None,
    ) -> None:
        self._session = session
        self._song_repo = song_repo
        self._library_repo = library_repo
        self._song_state_repo = song_state_repo

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

    def _get_meta(self, key: str) -> MetaRow | None:
        """Fetch a meta row by key."""
        with map_persistence_exceptions():
            row = select_by_key(_M, key, session=self._session, key_col="key")
            return _meta_row_to_dto(row) if row else None

    def _upsert_meta(self, key: str, payload: dict[str, Any]) -> None:
        """Insert-or-update a meta row keyed on *key*."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                data = {**payload, "key": key}
                upsert_by_field(_M, "key", key, data, session=self._session)
            self._session.commit()

    def _delete_meta(self, key: str) -> None:
        """Delete a meta row by key."""
        with map_persistence_exceptions():
            with self._session.begin_nested():
                delete_by_key(_M, key, session=self._session, key_col="key")
            self._session.commit()

    def _list_meta_keys_by_prefix(self, prefix: str) -> list[str]:
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
        row = self._get_meta(key)
        return ConfigOption(key=row["key"], value=row["value"]) if row is not None else None

    def list_config_options(self) -> list[ConfigOption]:
        """Return every ``config_*`` configuration value."""
        results: list[ConfigOption] = []
        for key in self._list_meta_keys_by_prefix("config_"):
            row = self._get_meta(key)
            if row is not None:
                results.append(ConfigOption(key=row["key"], value=row["value"]))
        return results

    def set_config_option(self, key: str, value: Any) -> None:
        """Persist a user configuration value under its full storage identity."""
        self._upsert_meta(key, {"value": value})

    def remove_config_option(self, key: str) -> None:
        """Remove a user configuration value by its full storage identity."""
        self._delete_meta(key)

    def get_schema_version(self) -> str | None:
        """Return the schema version, coercing non-string stored values to ``str``."""
        row = self._get_meta("version")
        if row is None:
            return None
        value = row["value"]
        return str(value) if value is not None else None

    def set_schema_version(self, version: str) -> None:
        """Persist the schema version."""
        self._upsert_meta("version", {"value": version})

    def get_api_key(self) -> str | None:
        """Return the stored API key, or ``None`` when not set."""
        row = self._get_meta("api_key")
        return cast("str", row["value"]) if row is not None else None

    def set_api_key(self, value: str) -> None:
        """Persist the API key."""
        self._upsert_meta("api_key", {"value": value})

    def get_admin_password_hash(self) -> str | None:
        """Return the stored admin password hash, or ``None`` when not set."""
        row = self._get_meta("admin_password_hash")
        return cast("str", row["value"]) if row is not None else None

    def set_admin_password_hash(self, value: str) -> None:
        """Persist the admin password hash."""
        self._upsert_meta("admin_password_hash", {"value": value})

    def get_calibration_version(self) -> str | None:
        """Return the calibration version hash, or ``None`` when not set."""
        row = self._get_meta("calibration_version")
        return cast("str", row["value"]) if row is not None else None

    def set_calibration_version(self, version_hash: str) -> None:
        """Persist the calibration version hash."""
        self._upsert_meta("calibration_version", {"value": version_hash})

    def get_calibration_last_run(self) -> int | None:
        """Return the calibration last-run timestamp (ms), or ``None`` when not set."""
        row = self._get_meta("calibration_last_run")
        if row is None:
            return None
        value = row["value"]
        return int(cast("str", value)) if value is not None else None

    def set_calibration_last_run(self, timestamp_ms: str) -> None:
        """Persist the calibration last-run timestamp as a string (read back as int)."""
        self._upsert_meta("calibration_last_run", {"value": timestamp_ms})

    def clear_calibration_metadata(self) -> int:
        """Atomically clear calibration bookkeeping values; return how many were removed."""
        keys = [k for k in ("calibration_version", "calibration_last_run") if self._get_meta(k) is not None]
        self._delete_meta_keys_atomic(keys)
        return len(keys)

    def get_model_vram_limit(self, model_path: str) -> int | None:
        """Return a model's VRAM limit in bytes, or ``None`` when not measured."""
        row = self._get_meta(f"ml_model_vram:{model_path}")
        if row is None:
            return None
        return int(cast("str", row["value"]))

    def set_model_vram_limit(self, model_path: str, limit_bytes: int) -> None:
        """Persist a model's VRAM limit in bytes (stored as a string)."""
        self._upsert_meta(f"ml_model_vram:{model_path}", {"value": str(limit_bytes)})

    def list_model_vram_limits(self) -> list[ModelVramLimit]:
        """Return every stored per-model VRAM limit as a domain value."""
        prefix = "ml_model_vram:"
        results: list[ModelVramLimit] = []
        for key in self._list_meta_keys_by_prefix(prefix):
            row = self._get_meta(key)
            if row is not None:
                results.append(
                    ModelVramLimit(model_path=key[len(prefix) :], limit_bytes=int(cast("str", row["value"])))
                )
        return results

    def clear_model_vram_limits(self) -> int:
        """Atomically clear all stored VRAM limits; return how many were removed."""
        keys = self._list_meta_keys_by_prefix("ml_model_vram:")
        self._delete_meta_keys_atomic(keys)
        return len(keys)

    def get_capacity_estimate(self, model_set_hash: str) -> CapacityEstimate | None:
        """Return the stored capacity estimate for a model set, or ``None``."""
        row = self._get_meta(f"capacity_estimate:{model_set_hash}")
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
        self._upsert_meta(
            f"capacity_estimate:{estimate.model_set_hash}",
            {"value": asdict(estimate)},
        )

    def remove_capacity_estimate(self, model_set_hash: str) -> None:
        """Remove the stored capacity estimate for a model set."""
        self._delete_meta(f"capacity_estimate:{model_set_hash}")

    def get_gpu_resource_snapshot(self) -> GpuResourceSnapshot | None:
        """Return the stored GPU resource snapshot, or ``None`` when absent."""
        row = self._get_meta("gpu_resources")
        if row is None:
            return None
        value = row["value"]
        return GpuResourceSnapshot(
            gpu_available=bool(value.get("gpu_available", False)),
            error_summary=value.get("error_summary"),
        )

    def set_gpu_resource_snapshot(self, snapshot: GpuResourceSnapshot) -> None:
        """Persist a GPU resource snapshot."""
        self._upsert_meta(
            "gpu_resources",
            {"value": {"gpu_available": snapshot.gpu_available, "error_summary": snapshot.error_summary}},
        )

    def get_worker_system_enabled(self) -> bool | None:
        """Return whether the worker system is enabled, or ``None`` when not set."""
        row = self._get_meta("worker_enabled")
        if row is None:
            return None
        return row["value"] == "true"

    def set_worker_system_enabled(self, enabled: bool) -> None:
        """Persist the worker-system enabled state as a boolean."""
        self._upsert_meta("worker_enabled", {"value": "true" if enabled else "false"})

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
    #
    # The claims intent surface lives on the facade (``AppDb``); this repository
    # implements the storage-backed primitives as private operations that never
    # leak ``WorkerClaimRow``, raw keys, JSON payloads, or generated ids to
    # higher layers.

    def _resolve_song_id(self, song: SongIdentity) -> int | None:
        """Resolve a natural ``SongIdentity`` to its storage song id."""
        if self._library_repo is None or self._song_repo is None:
            return None
        root_path = song.library.root_path
        if root_path is None:
            return None
        library_row = self._library_repo.get_library_by_natural_key(
            song.library.name,
            root_path,
        )
        if library_row is None:
            return None
        row = self._song_repo.get_song_by_normalized_path(library_row["id"], song.normalized_path)
        return row["id"] if row is not None else None

    def _resolve_song_ids(self, songs: Sequence[SongIdentity]) -> list[int]:
        """Resolve a batch of natural song identities to storage song ids."""
        return [sid for sid in (self._resolve_song_id(song) for song in songs) if sid is not None]

    def _song_identity_for_id(self, song_id: int) -> SongIdentity | None:
        """Resolve a storage song id to its natural identity, or ``None``."""
        if self._song_repo is None or self._library_repo is None:
            return None
        row = self._song_repo.get_song(song_id)
        if row is None:
            return None
        library_id = row.get("library_id")
        if library_id is None:
            return None
        library_row = self._library_repo.get_library(int(library_id))
        if library_row is None:
            return None
        return SongIdentity(
            library=LibraryIdentity(name=library_row["name"], root_path=library_row["path"]),
            normalized_path=row["normalized_path"],
        )

    def _song_exists(self, song_id: int) -> bool:
        """Return whether a storage song id currently exists."""
        return self._song_repo is not None and self._song_repo.get_song(song_id) is not None

    def _claim_value(self, song_id: int, claim_type: str | None) -> dict[str, Any]:
        """Assemble the private JSONB payload for a claim row."""
        value: dict[str, Any] = {"file_id": song_id}
        if claim_type is not None:
            value["claim_type"] = claim_type
        return value

    def _claim_row_to_domain(self, row: Row) -> WorkerClaim | None:
        """Map a private claim storage row to its domain ``WorkerClaim``.

        Returns ``None`` for rows whose key does not conform to the canonical
        encoding or whose song identity cannot be resolved (orphaned rows);
        these are quarantined rather than surfaced to the domain boundary.
        """
        m = row._mapping
        parsed = _parse_claim_key(cast("str", m["key"]))
        if parsed is None:
            return None
        song_id, claim_type = parsed
        song = self._song_identity_for_id(song_id)
        if song is None:
            return None
        return WorkerClaim(
            identity=WorkerClaimIdentity(
                song=song,
                worker_id=cast("str", m["worker_id"]),
                claim_type=claim_type,
            ),
            claimed_at_ms=cast("int", m["claimed_at"]),
        )

    def _acquire_claim(
        self,
        claim: WorkerClaim,
        *,
        now_ms: int,
        lease_ms: int | None,
    ) -> bool:
        """Atomically insert or replace one lease-gated claim.

        Enforces a single active claim per logical song across typed and untyped
        claims.  The transaction serializes on the song's existing claim rows
        (``SELECT ... FOR UPDATE``); a fresh claim is inserted when none exists,
        an expired claim is replaced via an exact-key, expiry-filtered
        ``UPDATE`` (preserving the legacy atomicity pattern and never deleting a
        different song's claim), and an active claim blocks acquisition.  With no
        ``lease_ms`` the call is insert-only (never replaces an existing claim).

        Returns ``True`` on acquisition, ``False`` on contention, on a missing
        song, or when insert-only semantics prevent replacement.
        """
        song_id = self._resolve_song_id(claim.identity.song)
        if song_id is None:
            return False
        target_key = _claim_key(claim.identity.claim_type, song_id)
        value = self._claim_value(song_id, claim.identity.claim_type)
        acquired = False
        with map_persistence_exceptions():
            with self._session.begin_nested():
                existing = self._session.execute(
                    select(_WC.c.key, _WC.c.claimed_at)
                    .where(
                        or_(
                            _WC.c.key == f"claim_{song_id}",
                            _WC.c.key.like(f"claim\\_%\\_{song_id}", escape="\\"),
                        )
                    )
                    .with_for_update()
                ).all()
                if not existing:
                    self._session.execute(
                        insert(_WC).values(
                            worker_id=claim.identity.worker_id,
                            key=target_key,
                            value=value,
                            claimed_at=now_ms,
                        )
                    )
                    acquired = True
                elif lease_ms is not None and int(existing[0].claimed_at) < now_ms - lease_ms:
                    old_key = cast("str", existing[0].key)
                    self._session.execute(
                        update(_WC)
                        .where(_WC.c.key == old_key, _WC.c.claimed_at < now_ms - lease_ms)
                        .values(
                            key=target_key,
                            worker_id=claim.identity.worker_id,
                            value=value,
                            claimed_at=now_ms,
                        )
                    )
                    acquired = True
            self._session.commit()
        return acquired

    def _remove_claim(self, identity: WorkerClaimIdentity) -> bool:
        """Remove exactly one logical claim (exact key + owning worker).

        Ownership-aware and exact-key: returns ``False`` when the claim does not
        exist or is held by a different worker, and never removes another claim.
        """
        song_id = self._resolve_song_id(identity.song)
        if song_id is None:
            return False
        key = _claim_key(identity.claim_type, song_id)
        removed = False
        with map_persistence_exceptions():
            with self._session.begin_nested():
                result = self._session.execute(
                    delete(_WC).where(_WC.c.key == key, _WC.c.worker_id == identity.worker_id)
                )
                removed = int(result.rowcount) > 0  # type: ignore[attr-defined]
            self._session.commit()
        return removed

    def _resolve_stale_workers(self, cutoff_ms: int) -> set[str]:
        """Return claimed workers whose health is stale or absent at *cutoff_ms*."""
        claimed_rows = self._session.execute(select(_WC.c.worker_id).distinct()).all()
        claimed = {cast("str", r[0]) for r in claimed_rows}
        if not claimed:
            return set()
        health_rows = self._session.execute(select(_H.c.worker_id, _H.c.last_seen)).all()
        active = {cast("str", r[0]) for r in health_rows if int(r[1]) >= cutoff_ms}
        return claimed - active

    def _remove_claims(
        self,
        request: ClaimRemovalRequest,
        *,
        resolved_song_ids: Sequence[int] = (),
    ) -> int:
        """Execute a complete claim-removal request; return rows removed.

        Combines explicit worker/song filters with the cleanup policies
        (stale-worker health plus missing/completed/errored song selection) into
        one atomic delete.  Active pending ``reconcile`` claims are preserved
        from song-state cleanup; inactive workers' claims (including reconcile)
        are freed via the stale-worker path.
        """
        target_worker_ids = set(request.worker_ids)
        target_song_ids = set(resolved_song_ids)
        for song_id in self._resolve_song_ids(request.songs):
            target_song_ids.add(song_id)

        with map_persistence_exceptions():
            with self._session.begin_nested():
                if request.stale_workers_before_ms is not None:
                    target_worker_ids |= self._resolve_stale_workers(request.stale_workers_before_ms)

                clean_song_ids: set[int] = set()
                if request.remove_missing_songs or request.remove_completed_songs or request.remove_errored_songs:
                    completed: set[int] = set()
                    errored: set[int] = set()
                    if self._song_state_repo is not None:
                        if request.remove_completed_songs:
                            completed = set(self._song_state_repo.list_songs_in_state(STATE_PROCESSED))
                        if request.remove_errored_songs:
                            errored = set(self._song_state_repo.list_songs_in_state(STATE_ERRORED))
                    for row in self._session.execute(select(_WC.c.key, _WC.c.worker_id)).all():
                        parsed = _parse_claim_key(cast("str", row[0]))
                        if parsed is None:
                            continue
                        song_id, claim_type = parsed
                        if claim_type == "reconcile":
                            continue  # active pending reconcile claims remain
                        if (
                            (request.remove_missing_songs and not self._song_exists(song_id))
                            or (request.remove_completed_songs and song_id in completed)
                            or (request.remove_errored_songs and song_id in errored)
                        ):
                            clean_song_ids.add(song_id)

                conditions: list[ColumnElement[bool]] = []
                if target_worker_ids:
                    conditions.append(_WC.c.worker_id.in_(target_worker_ids))
                all_song_ids = target_song_ids | clean_song_ids
                if all_song_ids:
                    key_conditions = [
                        condition
                        for sid in all_song_ids
                        for condition in (
                            _WC.c.key == f"claim_{sid}",
                            _WC.c.key.like(f"claim\\_%\\_{sid}", escape="\\"),
                        )
                    ]
                    conditions.append(or_(*key_conditions))
                if not conditions:
                    return 0
                result = self._session.execute(delete(_WC).where(or_(*conditions)))
                deleted = int(result.rowcount)  # type: ignore[attr-defined]
            self._session.commit()
            return deleted

    def _list_claim_rows(self) -> list[Row]:
        """Return all private worker-claim storage rows."""
        with map_persistence_exceptions():
            result = self._session.execute(select(_WC))
            return list(result.all())

    def _list_claims(self) -> list[WorkerClaim]:
        """Return all resolvable claims as domain values (orphans quarantined)."""
        with map_persistence_exceptions():
            result = self._session.execute(select(_WC))
            claims: list[WorkerClaim] = []
            for row in result.all():
                claim = self._claim_row_to_domain(row)
                if claim is not None:
                    claims.append(claim)
            return claims

    def _count_claims(self) -> int:
        """Return the number of currently persisted claim rows."""
        with map_persistence_exceptions():
            result = self._session.execute(select(func.count()).select_from(_WC))
            return int(result.scalar_one())

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

    def _delete_all_worker_claims(self) -> None:
        """Delete all rows from ``worker_claims``.

        Exposed only through the maintenance facade (``db.app.maintenance``); it
        is deliberately not part of the routine claims intent surface.
        """
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
