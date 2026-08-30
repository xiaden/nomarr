"""App-state persistence sub-facade (``AppDb``).

Groups application-state, lock/claim, session, health, migration/config, and
VRAM-promise persistence into a single intent facade wired as ``db.app``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.helpers.dataclasses.app_dataclasses import ConfigOption, LockEntry
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, scoped_session

    from nomarr.helpers.dto.repo_dto import (
        HealthRow,
        SessionRow,
        WorkerClaimRow,
    )
    from nomarr.persistence.database.app_repo import AppRepository
    from nomarr.persistence.database.pipeline_repo import PipelineRepository
    from nomarr.persistence.database.song_state_repo import SongStateRepository


class AppDb:
    """Persistence sub-facade for app-state, locks, claims, config, and admin helpers.

    Routine methods expose the normalized app-domain intent surface. Destructive
    maintenance operations (``truncate_health``, ``truncate_worker_claims``,
    ``truncate_song_state_edges``) are exposed directly on this facade.
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

    # ------------------------------------------------------------------
    # Maintenance methods (destructive reset/repair)
    # ------------------------------------------------------------------

    def truncate_song_state_edges(self) -> None:
        """Truncate all song-state assignments."""
        self._song_state_repo.truncate_assignments()

    def truncate_worker_claims(self) -> None:
        """Truncate all worker claims."""
        self._app_repo.truncate_worker_claims()

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

    def get_lock(self, resource_id: str) -> LockEntry | None:
        row = self._app_repo.get_lock(resource_id)
        return LockEntry(key=row["key"], value=row["value"]) if row is not None else None

    def add_lock(self, payload: dict) -> str:
        """Add a lock using its resource key and JSON ownership payload."""
        resource_id = payload.get("document_reference") or payload.get("resource_id")
        if not isinstance(resource_id, str):
            raise ValueError("lock payload must include a resource identifier")
        return self._app_repo.insert_lock({"key": resource_id, "value": payload})

    def list_locks(self) -> list[LockEntry]:
        return [LockEntry(key=row["key"], value=row["value"]) for row in self._app_repo.list_locks()]

    def remove_lock(self, resource_id: str) -> None:
        self._app_repo.release_lock(resource_id)

    def upsert_lock(self, resource_id: str, payload: dict) -> None:
        self._app_repo.upsert_lock(resource_id, {"value": payload})

    def acquire_lock(self, resource_id: str, payload: dict) -> bool:
        return self._app_repo.acquire_lock(resource_id, {"value": payload})

    def claim_song(
        self,
        song_id: int,
        worker_id: str,
        *,
        claim_type: str | None = None,
        claimed_at: int | None = None,
    ) -> int:
        """Claim a song for a worker without exposing storage payloads."""
        if claimed_at is None:
            claimed_at = now_ms().value
        key = f"claim_{claim_type}_{song_id}" if claim_type else f"claim_{song_id}"
        payload = {
            "key": key,
            "worker_id": worker_id,
            "file_id": song_id,
            "claimed_at": claimed_at,
        }
        if claim_type is not None:
            payload["claim_type"] = claim_type
        return self._app_repo.insert_worker_claim(payload)

    def remove_claim(self, worker_id: str, song_id: int, claim_type: str | None = None) -> None:
        self._app_repo.release_claim(worker_id, song_id, claim_type)

    def remove_claim_by_song(self, song_id: int, claim_type: str | None = None) -> None:
        """Remove a song claim regardless of its current worker owner."""
        self._app_repo.release_claim_by_song(song_id, claim_type)

    def steal_claim(
        self,
        song_id: int,
        worker_id: str,
        *,
        claim_type: str | None = None,
        claimed_at: int,
        now: int,
        lease_ms: int,
    ) -> bool:
        """Atomically claim a song when its current claim has expired."""
        key = f"claim_{claim_type}_{song_id}" if claim_type else f"claim_{song_id}"
        payload: dict[str, object] = {
            "key": key,
            "worker_id": worker_id,
            "value": {"file_id": song_id, **({"claim_type": claim_type} if claim_type is not None else {})},
            "claimed_at": claimed_at,
        }
        return self._app_repo.steal_claim(payload, now, lease_ms)

    def remove_claims(
        self,
        *,
        worker_ids: list[str] | None = None,
        song_ids: list[int] | None = None,
    ) -> int:
        """Delete claims matching the supplied worker ids and/or song ids.

        Args:
            worker_ids: Optional worker ids whose claims should be removed.
            song_ids: Optional song ids whose claims should be removed.

        Returns:
            Total number of unique claims removed across both filters.

        """
        return self._app_repo.delete_claims(worker_ids=worker_ids, song_ids=song_ids)

    def list_claims(self) -> list[WorkerClaimRow]:
        return self._app_repo.list_claims()

    def get_health(self, component_id: str) -> HealthRow | None:
        return self._app_repo.get_health(component_id)

    def count_healthy(self) -> int:
        return self._app_repo.count_healthy()

    def list_worker_health(self) -> list[HealthRow]:
        return self._app_repo.list_worker_health()

    def update_health(self, component_id: str, fields: dict) -> None:
        self._app_repo.update_health(component_id, fields)

    def upsert_health(self, component_id: str, fields: dict) -> None:
        self._app_repo.upsert_health(component_id, fields)

    def release_claim(self, worker_id: str, song_id: int, claim_type: str | None = None) -> None:
        """Release one worker's claim for a song."""
        self.remove_claim(worker_id, song_id, claim_type)

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

    def add_vram_promise(self, payload: dict) -> None:
        self._app_repo.upsert_vram_promise(payload)

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
        self._app_repo.upsert_vram_promise(
            {
                "worker_id": worker_id,
                "pid": pid,
                "model_path": model_path,
                "promised_mb": promised_mb,
                "total_mb": total_mb,
                "used_mb": used_mb,
            }
        )

    def list_vram_promises(self) -> list[dict]:
        return self._app_repo.get_vram_promises()

    def remove_vram_promise(self, promise_id: int) -> None:
        self._app_repo.delete_vram_promise(promise_id)

    def release_vram(self, *, worker_id: str, model_path: str) -> None:
        """Release the VRAM promise(s) for a worker+model."""
        self._app_repo.delete_vram_promise_by_worker_model(worker_id, model_path)

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
        return len(self._app_repo.get_vram_promises())

    def get_worker_restart_policy(self, component_id: str) -> dict | None:
        return self._app_repo.get_worker_restart_policy(component_id)

    def update_worker_restart_policy(self, component_id: str, fields: dict) -> None:
        self._app_repo.upsert_worker_restart_policy(component_id, fields)

    def upsert_worker_restart_policy(self, component_id: str, fields: dict) -> None:
        self._app_repo.upsert_worker_restart_policy(component_id, fields)

    def insert_session(self, payloads: list[dict]) -> None:
        self._app_repo.insert_session(payloads)

    def delete_session(self, session_id: str) -> None:
        self._app_repo.delete_session(session_id)

    def get_sessions_expiring_before(self, timestamp_ms: int, limit: int) -> list[SessionRow]:
        return self._app_repo.get_sessions_expiring_before(timestamp_ms, limit)

    def count_sessions(self) -> int:
        return self._app_repo.count_sessions()

    def delete_sessions_by_ids(self, session_ids: list[str]) -> None:
        self._app_repo.delete_sessions_by_ids(session_ids)

    def get_active_sessions(self, not_before_ms: int, limit: int) -> list[SessionRow]:
        return self._app_repo.get_active_sessions(not_before_ms, limit)

    def get_config_option(self, key: str) -> ConfigOption | None:
        row = self._app_repo.get_meta(key)
        return ConfigOption(key=row["key"], value=row["value"]) if row is not None else None

    def get_schema_version(self) -> str | None:
        """Get the schema version (stored as key='version' in meta)."""
        option = self.get_config_option("version")
        if option is None:
            return None
        value = option.value
        return str(value) if value is not None else None

    def list_config_options(self, prefix: str | None = None) -> list[ConfigOption]:
        keys = self._app_repo.list_meta_keys_by_prefix(prefix or "")
        results: list[ConfigOption] = []
        for key in keys:
            row = self._app_repo.get_meta(key)
            if row is not None:
                results.append(ConfigOption(key=row["key"], value=row["value"]))
        return results

    def update_config_option(self, key: str, payload: dict) -> None:
        self._app_repo.upsert_meta(key, payload)

    def remove_config_option(self, key: str) -> None:
        self._app_repo.delete_meta(key)
