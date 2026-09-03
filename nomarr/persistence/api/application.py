"""App-state persistence sub-facade (``AppDb``).

Groups application-state, lock/claim, session, health, migration/config, and
VRAM-promise persistence into a single intent facade wired as ``db.app``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers import time_helper
from nomarr.helpers.dataclasses.app_dataclasses import (
    CapacityEstimate,
    ConfigOption,
    GpuResourceSnapshot,
    LockEntry,
    ModelVramLimit,
    VramPromise,
    WorkerRestartPolicy,
)
from nomarr.helpers.dataclasses.session_dataclass import AuthSession
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dto.health_dto import WorkerHealth
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, scoped_session

    from nomarr.helpers.dataclasses.worker_claim_dataclass import (
        ClaimRemovalRequest,
        WorkerClaim,
        WorkerClaimIdentity,
    )
    from nomarr.helpers.dto.repo_dto import SessionRow
    from nomarr.persistence.database.app_repo import AppRepository
    from nomarr.persistence.database.pipeline_repo import PipelineRepository
    from nomarr.persistence.database.song_state_repo import SongStateRepository


def _session_row_to_domain(row: SessionRow) -> AuthSession:
    """Map a repository session row to the domain session object."""
    return AuthSession(
        token=row["id"],
        data=row["data"],
        expires_at=row["expires_at"] / 1000.0,
    )


class AppMaintenanceDb:
    """Destructive whole-table resets for ``db.app.maintenance``.

    All-claims deletion is an explicit maintenance act and is therefore kept out
    of the routine claims intent surface on ``AppDb``.  Sibling destructive
    resets that predate the maintenance split (``truncate_health``,
    ``truncate_song_state_edges``) remain directly on ``AppDb``.
    """

    def __init__(self, app_repo: AppRepository) -> None:
        self._app_repo = app_repo

    def delete_all_worker_claims(self) -> None:
        """Delete every worker-claim row (all-claims maintenance reset)."""
        self._app_repo._delete_all_worker_claims()


class AppDb:
    """Persistence sub-facade for app-state, locks, claims, config, and admin helpers.

    Routine methods expose the normalized app-domain intent surface. The claims
    intent surface is the five canonical methods (``add_claim``, ``remove_claim``,
    ``remove_claims``, ``list_claims``, ``count_claims``) plus the destructive
    all-claims reset under ``maintenance.delete_all_worker_claims``.  Sibling
    destructive resets (``truncate_health``, ``truncate_song_state_edges``)
    remain directly on this facade.
    """

    def __init__(
        self,
        *,
        session: scoped_session[Session],
        app_repo: AppRepository,
        song_state_repo: SongStateRepository,
        pipeline_repo: PipelineRepository,
    ) -> None:
        """Initialise the app persistence facade.

        All repository parameters are required and provided by the
        Database constructor.
        """
        self._song_state_repo = song_state_repo
        # Overlaps the concurrent persistence-facade split: song-state reads
        # need the pipeline repository internally, while callers remain
        # unaware of either repository or table.
        self._pipeline_repo = pipeline_repo
        self._app_repo = app_repo
        self._session = session
        self.maintenance = AppMaintenanceDb(app_repo)

    # ------------------------------------------------------------------
    # Maintenance methods (destructive reset/repair)
    # ------------------------------------------------------------------

    def truncate_song_state_edges(self) -> None:
        """Truncate all song-state assignments."""
        self._song_state_repo.truncate_assignments()

    def truncate_health(self) -> None:
        """Truncate all health rows."""
        self._app_repo.truncate_health()

    # ------------------------------------------------------------------
    # Routine top-level methods already aligned with the DD contract
    # ------------------------------------------------------------------

    def song_state_membership(self, song_id: int) -> set[str]:
        """Return every processing-state membership for one song.

        The empty set means that no state has been assigned.  State names are
        the domain vocabulary; callers never handle state-table identifiers.
        """
        return set(self._song_state_repo.get_song_states(song_id))

    def song_state_memberships(self, song_ids: list[int]) -> dict[int, set[str]]:
        """Return state memberships, including empty sets for unknown songs."""
        unique_song_ids = list(dict.fromkeys(song_ids))
        memberships = self._song_state_repo.get_song_states_for_songs(unique_song_ids)
        return {song_id: set(memberships.get(song_id, set())) for song_id in unique_song_ids}

    def song_ids_with_state(self, state: str, *, limit: int | None = None) -> list[int]:
        """Return song identifiers currently in the requested state."""
        return self._song_state_repo.list_songs_in_state(state, limit=limit)

    def songs_with_state(
        self,
        state: str,
        *,
        limit: int | None = None,
        library_id: int | None = None,
        order_by_activity: bool = False,
    ) -> list[Song]:
        """Return domain songs currently in a state, optionally scoped/sorted."""
        query_kwargs: dict[str, Any] = {"limit": limit}
        if library_id is not None:
            query_kwargs["library_id"] = library_id
        if order_by_activity:
            query_kwargs["order_by_activity"] = True
        rows = self._pipeline_repo.list_song_docs_in_state(state, **query_kwargs)
        return [Song.from_row(row) for row in rows]

    def count_songs_with_state(self, state: str) -> int:
        """Count songs currently in the requested state."""
        return self._song_state_repo.count_songs_in_state(state)

    def transition_song_states(self, song_ids: list[int], from_state: str, to_state: str) -> None:
        """Move songs between two poles while preserving all other axes."""
        self._song_state_repo.transition_state_for_songs(song_ids, from_state, to_state)

    def initialize_song_states(self, song_ids: list[int]) -> None:
        """Ensure new songs have the canonical initial state membership."""
        self._song_state_repo.initialize_song_states(song_ids)

    def clear_song_states(self, song_ids: list[int]) -> int:
        """Remove all memberships for explicitly requested songs.

        This is an explicit cleanup intent, not a routine state transition.
        The returned count is useful to maintenance callers and hides the
        assignment-row representation.
        """
        return self._song_state_repo.remove_states_for_songs(list(dict.fromkeys(song_ids)))

    def set_song_state(self, song_ids: list[int], state: str) -> None:
        """Set one state axis without exposing assignment primitives."""
        self._song_state_repo.set_state_for_songs(song_ids, state)

    def remove_song_state(self, song_ids: list[int], state: str) -> None:
        """Remove one named state without disturbing the other axes."""
        self._song_state_repo.remove_state_for_songs(list(dict.fromkeys(song_ids)), state)

    @staticmethod
    def _lock_key(lock_type: str, resource_id: str) -> str:
        """Build the repository key for a logical lock identity."""
        if not lock_type or not resource_id:
            raise ValueError("lock type and resource ID are required")
        return f"{lock_type}:{resource_id}"

    @classmethod
    def _lock_payload(cls, lock: LockEntry) -> dict[str, Any]:
        """Serialize a domain lock for the internal repository boundary."""
        return {
            "key": cls._lock_key(lock.lock_type, lock.resource_id),
            "value": {
                "lock_type": lock.lock_type,
                "resource_id": lock.resource_id,
                "holder": lock.holder,
                "expires_at": lock.expires_at,
                "acquired_at": lock.acquired_at,
                "status": lock.status,
            },
        }

    @staticmethod
    def _lock_from_row(row: Any) -> LockEntry:
        """Map an internal repository row to the lock domain object."""
        key = str(row["key"])
        value = row["value"]
        if not isinstance(value, dict):
            raise ValueError("persisted lock value must be an object")
        lock_type, separator, resource_id = key.partition(":")
        if not separator or not lock_type or not resource_id:
            raise ValueError("persisted lock key must contain a lock type and resource ID")
        return LockEntry(
            # The repository key is the authoritative logical identity.  Do not
            # allow a stale JSON payload to change which lock was read.
            lock_type=lock_type,
            resource_id=resource_id,
            holder=str(value.get("holder", "")),
            expires_at=float(value.get("expires_at", 0.0)),
            acquired_at=float(value.get("acquired_at", 0.0)),
            status=str(value.get("status", "active")),
        )

    def get_lock(self, lock_type: str, resource_id: str) -> LockEntry | None:
        """Return lock state by its logical type and resource identity."""
        row = self._app_repo.get_lock(self._lock_key(lock_type, resource_id))
        return self._lock_from_row(row) if row is not None else None

    def add_lock(self, lock: LockEntry) -> None:
        """Create a lock from a domain lock value."""
        self._app_repo.insert_lock(self._lock_payload(lock))

    def list_locks(self) -> list[LockEntry]:
        """Return all locks as domain values."""
        return [self._lock_from_row(row) for row in self._app_repo.list_locks()]

    def remove_lock(self, lock_type: str, resource_id: str) -> None:
        """Remove a lock by its logical identity."""
        self._app_repo.release_lock(self._lock_key(lock_type, resource_id))

    def upsert_lock(self, lock: LockEntry) -> None:
        """Replace lock state for a logical lock identity."""
        payload = self._lock_payload(lock)
        self._app_repo.upsert_lock(payload["key"], {"value": payload["value"]})

    def acquire_lock(self, lock: LockEntry) -> bool:
        """Atomically create a lock, returning false when already present."""
        payload = self._lock_payload(lock)
        return self._app_repo.acquire_lock(payload["key"], {"value": payload["value"]})

    def add_claim(
        self,
        claim: WorkerClaim,
        *,
        now_ms: int | None = None,
        lease_ms: int | None = None,
    ) -> bool:
        """Acquire a claim on a song, atomically.

        Enforces a single active claim per song across typed and untyped claims.
        With ``lease_ms`` set, an expired claim is replaced (steal); without it
        the call is insert-only.  Returns ``True`` when the claim was acquired
        and ``False`` on contention (an active claim already exists) or when the
        song cannot be resolved.
        """
        return self._app_repo._acquire_claim(
            claim,
            now_ms=now_ms if now_ms is not None else time_helper.now_ms().value,
            lease_ms=lease_ms,
        )

    def remove_claim(self, identity: WorkerClaimIdentity) -> bool:
        """Remove exactly one logical claim held by ``identity.worker_id``.

        Ownership-aware and exact-key: returns ``False`` when the claim does not
        exist or is held by a different worker.
        """
        return self._app_repo._remove_claim(identity)

    def remove_claims(self, request: ClaimRemovalRequest) -> int:
        """Remove claims matching an explicit worker/song or cleanup request.

        Combines explicit filters with the cleanup policies (stale workers,
        missing/completed/errored songs) in one atomic delete; returns the number
        of claim rows removed.  Active pending reconcile claims are preserved
        from song-state cleanup.
        """
        return self._app_repo._remove_claims(request)

    def list_claims(self) -> list[WorkerClaim]:
        """Return every resolvable claim as a domain value (orphans quarantined)."""
        return self._app_repo._list_claims()

    def count_claims(self) -> int:
        """Return the number of currently persisted claim rows."""
        return self._app_repo._count_claims()

    def get_health(self, worker_id: str) -> WorkerHealth | None:
        """Return the current health status for a worker or component."""
        row = cast("dict[str, Any] | None", self._app_repo.get_health(worker_id))
        return (
            WorkerHealth(worker_id=row["worker_id"], status=row["status"], last_seen=row["last_seen"]) if row else None
        )

    def count_healthy(self) -> int:
        """Return the number of workers currently reporting healthy."""
        return self._app_repo.count_healthy()

    def list_worker_health(self) -> list[WorkerHealth]:
        """Return health status for every monitored worker or component."""
        return [
            WorkerHealth(worker_id=row["worker_id"], status=row["status"], last_seen=row["last_seen"])
            for row in cast("list[dict[str, Any]]", self._app_repo.list_worker_health())
        ]

    def update_health(self, worker_id: str, *, status: str, last_seen: int) -> None:
        """Record a worker heartbeat, creating its status record if needed."""
        self._app_repo.update_health(worker_id, {"status": status, "last_seen": last_seen})

    def upsert_health(self, worker_id: str, *, status: str, last_seen: int) -> None:
        """Create or replace a worker's health status."""
        self._app_repo.upsert_health(worker_id, {"status": status, "last_seen": last_seen})

    def upsert_migration(self, name: str, fields: dict) -> None:
        self._app_repo.upsert_migration(name, fields)

    def list_migrations(self) -> list[dict]:
        return self._app_repo.list_migrations()

    def record_migration_started(
        self,
        migration_id: str,
        *,
        filename: str,
        checksum: str | None = None,
    ) -> None:
        """Record that a migration has started."""
        self.upsert_migration(
            migration_id,
            {
                "filename": filename,
                "checksum": checksum,
                "status": "running",
            },
        )

    def mark_migration_applied(self, migration_id: str) -> None:
        """Mark a migration as successfully applied."""
        self.upsert_migration(migration_id, {"status": "applied"})

    def promise_vram(
        self,
        *,
        worker_id: str,
        pid: int,
        model_path: str,
        promised_mb: float,
        total_mb: float,
        used_mb: float,
    ) -> None:
        """Record a VRAM promise from a worker (plain insert, id autoincrements)."""
        self._app_repo.insert_vram_promise(
            worker_id=worker_id,
            pid=pid,
            model_path=model_path,
            promised_mb=promised_mb,
            total_mb=total_mb,
            used_mb=used_mb,
        )

    def list_vram_promises(self) -> list[VramPromise]:
        """Return active reservations as domain values.

        The persistence-generated row id and storage row shape remain inside
        the repository; callers address reservations by worker and model.
        """
        return self._app_repo.get_vram_promises()

    def release_vram(self, *, worker_id: str, model_path: str) -> int:
        """Release reservations for a worker/model pair.

        Returns the number of reservations released. The pair is the domain
        identity; persistence-generated row identifiers are never required.
        """
        return self._app_repo.delete_vram_promise_by_worker_model(worker_id, model_path)

    def release_all_for_worker(self, *, worker_id: str) -> int:
        """Release all promises for *worker_id* in one database operation.

        The repository executes one ``DELETE ... WHERE worker_id = ...``
        statement in its transaction. Under PostgreSQL's default READ
        COMMITTED isolation, the statement removes promises visible when the
        DELETE starts; a promise committed after that statement snapshot is a
        new promise and may be handled by a later release.

        Returns:
            Number of promise rows removed by the DELETE statement.
        """
        return self._app_repo.delete_vram_promises_by_worker(worker_id)

    def count_vram_promises(self) -> int:
        """Return the number of active VRAM reservations."""
        return self._app_repo.count_vram_promises()

    def get_worker_restart_policy(self, component_id: str) -> WorkerRestartPolicy | None:
        """Return restart state for a worker component."""
        fields = self._app_repo.get_worker_restart_policy(component_id)
        if fields is None:
            return None
        return WorkerRestartPolicy(
            restart_count=int(fields.get("restart_count", 0)),
            last_restart_wall_ms=fields.get("last_restart_wall_ms"),
            failed_at_wall_ms=fields.get("failed_at_wall_ms"),
            failure_reason=fields.get("failure_reason"),
            updated_at_wall_ms=fields.get("updated_at_wall_ms"),
        )

    def record_worker_restart(self, component_id: str) -> WorkerRestartPolicy:
        """Record one restart attempt atomically and return the resulting policy."""
        fields = self._app_repo.increment_worker_restart_policy(component_id, timestamp_wall_ms=now_ms().value)
        return WorkerRestartPolicy(
            restart_count=int(fields.get("restart_count", 0)),
            last_restart_wall_ms=fields.get("last_restart_wall_ms"),
            failed_at_wall_ms=fields.get("failed_at_wall_ms"),
            failure_reason=fields.get("failure_reason"),
            updated_at_wall_ms=fields.get("updated_at_wall_ms"),
        )

    def reset_worker_restart_count(self, component_id: str) -> None:
        """Clear restart history after a worker has recovered successfully."""
        existing = self.get_worker_restart_policy(component_id)
        if existing is None or existing.restart_count == 0:
            return
        timestamp = now_ms().value
        self._store_worker_restart_policy(
            component_id,
            WorkerRestartPolicy(updated_at_wall_ms=timestamp),
        )

    def mark_worker_restart_failed(self, component_id: str, reason: str) -> WorkerRestartPolicy:
        """Record that a worker exceeded restart limits."""
        existing = self.get_worker_restart_policy(component_id)
        timestamp = now_ms().value
        policy = WorkerRestartPolicy(
            restart_count=existing.restart_count if existing else 0,
            last_restart_wall_ms=existing.last_restart_wall_ms if existing else None,
            failed_at_wall_ms=timestamp,
            failure_reason=reason,
            updated_at_wall_ms=timestamp,
        )
        self._store_worker_restart_policy(component_id, policy)
        return policy

    def _store_worker_restart_policy(self, component_id: str, policy: WorkerRestartPolicy) -> None:
        """Persist a domain policy without exposing its storage representation."""
        self._app_repo.upsert_worker_restart_policy(
            component_id,
            {
                "restart_count": policy.restart_count,
                "last_restart_wall_ms": policy.last_restart_wall_ms,
                "failed_at_wall_ms": policy.failed_at_wall_ms,
                "failure_reason": policy.failure_reason,
                "updated_at_wall_ms": policy.updated_at_wall_ms,
            },
        )

    def save_session(self, session: AuthSession) -> None:
        """Persist an authenticated session."""
        self._app_repo.insert_session(
            [
                {
                    "id": session.token,
                    "data": session.data,
                    "expires_at": int(session.expires_at * 1000),
                }
            ]
        )

    def delete_session(self, session_token: str) -> None:
        """Remove an authenticated session by its natural token key."""
        self._app_repo.delete_session(session_token)

    def find_expired_sessions(self, now: float) -> list[AuthSession]:
        """Return sessions whose domain expiry is before ``now``."""
        rows = self._app_repo.get_sessions_expiring_before(int(now * 1000))
        return [_session_row_to_domain(row) for row in rows]

    def delete_sessions(self, sessions: list[AuthSession]) -> None:
        """Remove authenticated sessions without exposing storage identifiers."""
        self._app_repo.delete_sessions_by_ids([session.token for session in sessions])

    def find_active_sessions(self, now: float) -> list[AuthSession]:
        """Return sessions that have not expired at ``now``."""
        rows = self._app_repo.get_active_sessions(int(now * 1000))
        return [_session_row_to_domain(row) for row in rows]

    # ------------------------------------------------------------------
    # User configuration intents
    # ------------------------------------------------------------------

    @staticmethod
    def _config_storage_key(key: str) -> str:
        """Build the physical storage identity for a user-configuration key.

        Callers address configuration by its bare configuration-domain key
        (e.g. ``"scan_interval"``); the ``config_`` storage prefix is an
        internal detail owned by this facade, mirroring the lock/claim key
        encodings below.
        """
        return f"config_{key}"

    def get_config_option(self, key: str) -> ConfigOption | None:
        """Return a user configuration value by its configuration identity."""
        return self._app_repo.get_config_option(self._config_storage_key(key))

    def list_config_options(self) -> list[ConfigOption]:
        """Return every user configuration value.

        Only ``config_*`` keys are returned; the caller does not supply the
        physical ``config_`` prefix.
        """
        return self._app_repo.list_config_options()

    def set_config_option(self, key: str, value: Any) -> None:
        """Set a user configuration value from a scalar/domain value.

        A storage-shaped ``{"value": ...}`` payload is rejected: configuration
        writes take the configuration value directly, never a storage payload.
        """
        if isinstance(value, dict):
            raise ValueError("configuration value must be a scalar/domain value, not a storage payload")
        self._app_repo.set_config_option(self._config_storage_key(key), value)

    def remove_config_option(self, key: str) -> None:
        """Remove a user configuration value by its configuration identity."""
        self._app_repo.remove_config_option(self._config_storage_key(key))

    # ------------------------------------------------------------------
    # Schema version
    # ------------------------------------------------------------------

    def get_schema_version(self) -> str | None:
        """Return the schema version, or ``None`` when not set."""
        return self._app_repo.get_schema_version()

    def set_schema_version(self, version: str) -> None:
        """Persist the schema version."""
        self._app_repo.set_schema_version(version)

    # ------------------------------------------------------------------
    # API key / admin credentials
    # ------------------------------------------------------------------

    def get_api_key(self) -> str | None:
        """Return the stored API key, or ``None`` when not set."""
        return self._app_repo.get_api_key()

    def set_api_key(self, value: str) -> None:
        """Persist the API key. Key generation stays with the key service."""
        self._app_repo.set_api_key(value)

    def get_admin_password_hash(self) -> str | None:
        """Return the stored admin password hash, or ``None`` when not set."""
        return self._app_repo.get_admin_password_hash()

    def set_admin_password_hash(self, value: str) -> None:
        """Persist the admin password hash. Hashing stays with the key service."""
        self._app_repo.set_admin_password_hash(value)

    # ------------------------------------------------------------------
    # Calibration bookkeeping
    # ------------------------------------------------------------------

    def get_calibration_version(self) -> str | None:
        """Return the calibration version hash, or ``None`` when not set."""
        return self._app_repo.get_calibration_version()

    def set_calibration_version(self, version_hash: str) -> None:
        """Persist the calibration version hash."""
        self._app_repo.set_calibration_version(version_hash)

    def get_calibration_last_run(self) -> int | None:
        """Return the calibration last-run timestamp (ms), or ``None`` when not set."""
        return self._app_repo.get_calibration_last_run()

    def set_calibration_last_run(self, timestamp_ms: str) -> None:
        """Persist the calibration last-run timestamp as a string (read back as int)."""
        self._app_repo.set_calibration_last_run(timestamp_ms)

    def clear_calibration_metadata(self) -> int:
        """Atomically clear calibration bookkeeping values; return how many were removed."""
        return self._app_repo.clear_calibration_metadata()

    # ------------------------------------------------------------------
    # Model VRAM limits
    # ------------------------------------------------------------------

    def get_model_vram_limit(self, model_path: str) -> int | None:
        """Return a model's VRAM limit in bytes, or ``None`` when not measured."""
        return self._app_repo.get_model_vram_limit(model_path)

    def set_model_vram_limit(self, model_path: str, limit_bytes: int) -> None:
        """Persist a model's VRAM limit in bytes."""
        self._app_repo.set_model_vram_limit(model_path, limit_bytes)

    def list_model_vram_limits(self) -> list[ModelVramLimit]:
        """Return every stored per-model VRAM limit as a domain value."""
        return self._app_repo.list_model_vram_limits()

    def clear_model_vram_limits(self) -> int:
        """Atomically clear all stored VRAM limits; return how many were removed."""
        return self._app_repo.clear_model_vram_limits()

    # ------------------------------------------------------------------
    # Capacity estimates
    # ------------------------------------------------------------------

    def get_capacity_estimate(self, model_set_hash: str) -> CapacityEstimate | None:
        """Return the stored capacity estimate for a model set, or ``None``."""
        return self._app_repo.get_capacity_estimate(model_set_hash)

    def set_capacity_estimate(self, estimate: CapacityEstimate) -> None:
        """Persist a capacity estimate for its model set."""
        self._app_repo.set_capacity_estimate(estimate)

    def remove_capacity_estimate(self, model_set_hash: str) -> None:
        """Remove the stored capacity estimate for a model set."""
        self._app_repo.remove_capacity_estimate(model_set_hash)

    # ------------------------------------------------------------------
    # GPU resource snapshots
    # ------------------------------------------------------------------

    def get_gpu_resource_snapshot(self) -> GpuResourceSnapshot | None:
        """Return the stored GPU resource snapshot, or ``None`` when absent."""
        return self._app_repo.get_gpu_resource_snapshot()

    def set_gpu_resource_snapshot(self, snapshot: GpuResourceSnapshot) -> None:
        """Persist a GPU resource snapshot."""
        self._app_repo.set_gpu_resource_snapshot(snapshot)

    # ------------------------------------------------------------------
    # Worker-system enabled state
    # ------------------------------------------------------------------

    def get_worker_system_enabled(self) -> bool | None:
        """Return whether the worker system is enabled, or ``None`` when not set."""
        return self._app_repo.get_worker_system_enabled()

    def set_worker_system_enabled(self, enabled: bool) -> None:
        """Persist the worker-system enabled state as a boolean."""
        self._app_repo.set_worker_system_enabled(enabled)
