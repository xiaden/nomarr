"""App-state persistence sub-facade (``AppDb``).

Groups application-state, lock/claim, session, health, migration/config, and
VRAM-promise persistence into a single intent facade wired as ``db.app``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, scoped_session

    from nomarr.helpers.dto.repo_dto import (
        HealthRow,
        LockRow,
        MetaRow,
        SessionRow,
        SongRow,
        WorkerClaimRow,
    )
    from nomarr.persistence.database.app_repo import AppRepository
    from nomarr.persistence.database.library_repo import LibraryRepository
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
        library_repo: LibraryRepository,
        song_state_repo: SongStateRepository,
        pipeline_repo: PipelineRepository,
    ) -> None:
        """Initialise the app persistence facade.

        All repository parameters are required and provided by the
        Database constructor.
        """
        self._song_state_repo = song_state_repo
        self._app_repo = app_repo
        self._library_repo = library_repo
        self._pipeline_repo = pipeline_repo
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

    def get_song_states(self, song_id: int) -> set[str]:
        return self._song_state_repo.get_song_states(song_id)

    def get_song_states_for_songs(self, song_ids: list[int]) -> dict[int, set[str]]:
        return self._song_state_repo.get_song_states_for_songs(song_ids)

    def list_songs_in_state(self, state: str, *, limit: int | None = None) -> list[int]:
        return self._song_state_repo.list_songs_in_state(state, limit=limit)

    def list_song_docs_in_state(
        self,
        state: str,
        *,
        limit: int | None = None,
    ) -> list[SongRow]:
        return self._pipeline_repo.list_song_docs_in_state(state, limit=limit)

    def count_songs_in_state(self, state: str) -> int:
        return self._song_state_repo.count_songs_in_state(state)

    def add_song_states(self, song_ids: list[int], state: str) -> None:
        for song_id in song_ids:
            self._song_state_repo.assign_state(song_id, state)

    def replace_song_states(self, song_ids: list[int], state: str) -> None:
        self._song_state_repo.replace_state_for_songs(song_ids, state)

    def remove_song_states(self, song_ids: list[int]) -> None:
        if not song_ids:
            return
        self._song_state_repo.remove_states_for_songs(song_ids)

    def remove_song_state(self, song_ids: list[int], state: str) -> None:
        """Remove one state pole without disturbing other song axes."""
        self._song_state_repo.remove_state_for_songs(song_ids, state)

    def get_pipeline_state(self, library_id: int) -> dict[str, str] | None:
        """Return the four pipeline axis values for a library."""
        return self._library_repo.get_pipeline_state(library_id)

    def get_libraries_in_axis_state(self, axis_field: str, axis_value: str) -> list[int]:
        """Return library ids where the given axis field matches the value."""
        return self._library_repo.get_libraries_in_axis_state(axis_field, axis_value)

    def upsert_pipeline_state(
        self,
        library_id: int,
        state_key: str,
        state_data: dict,
    ) -> None:
        """Insert-or-update one pipeline-state row for a library axis key.

        Single-row repo write (repo-internal short transaction) onto the
        ``pipeline_states`` table — the row-backed replacement for the
        removed libraries-columns state-write path.
        """
        self._pipeline_repo.upsert_pipeline_state(library_id, state_key, state_data)

    def get_lock(self, resource_id: str) -> LockRow | None:
        return self._app_repo.get_lock(resource_id)

    def add_lock(self, payload: dict) -> str:
        """Add a lock using its resource key and JSON ownership payload."""
        resource_id = payload.get("document_reference") or payload.get("resource_id")
        if not isinstance(resource_id, str):
            raise ValueError("lock payload must include a resource identifier")
        return self._app_repo.insert_lock({"key": resource_id, "value": payload})

    def list_locks(self) -> list[LockRow]:
        return self._app_repo.list_locks()

    def remove_lock(self, resource_id: str) -> None:
        self._app_repo.release_lock(resource_id)

    def upsert_lock(self, resource_id: str, payload: dict) -> None:
        self._app_repo.upsert_lock(resource_id, payload)

    def acquire_lock(self, resource_id: str, payload: dict) -> bool:
        return self._app_repo.acquire_lock(resource_id, payload)

    def claim_song(
        self,
        song_id: int,
        worker_id: str,
        *,
        claim_type: str | None = None,
        claimed_at: int = 0,
    ) -> int:
        """Claim a song for a worker without exposing storage payloads."""
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

    def remove_claim(self, worker_id: str, song_id: int, claim_type: str = "process") -> None:
        self._app_repo.release_claim(worker_id, song_id, claim_type)

    def remove_claim_by_song(self, song_id: int, claim_type: str = "process") -> None:
        """Remove a song claim regardless of its current worker owner."""
        self._app_repo.release_claim_by_song(song_id, claim_type)

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
            Total number of claims removed across both filters.

        """
        removed = 0
        if worker_ids:
            removed += self._app_repo.delete_claims_for_workers(worker_ids)
        if song_ids:
            removed += self._app_repo.delete_claims_for_songs(song_ids)
        return removed

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

    def release_claim(self, worker_id: str, song_id: int, claim_type: str = "process") -> None:
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

    def release_all_for_worker(self, *, worker_id: str) -> None:
        """Release all VRAM promises held by a worker.

        Preserves the list-then-remove loop semantics of the absorbed
        VRAM-promises adapter (no ``FOR UPDATE`` — the plan does not
        require row-locking for this method).
        """
        for p in self.list_vram_promises():
            if p.get("worker_id") == worker_id:
                pid = p.get("id")
                if pid:
                    # Call the repo directly rather than remove_vram_promise
                    # (which commits internally and would be redundant here).
                    self._app_repo.delete_vram_promise(pid)

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

    def get_config_option(self, key: str) -> MetaRow | None:
        return self._app_repo.get_meta(key)

    def get_schema_version(self) -> str | None:
        """Get the schema version (stored as key='version' in meta)."""
        row = self._app_repo.get_meta("version")
        if row is None:
            return None
        value = row["value"]
        return str(value) if value is not None else None

    def list_config_options(self, prefix: str | None = None) -> list[MetaRow]:
        keys = self._app_repo.list_meta_keys_by_prefix(prefix or "")
        results: list[MetaRow] = []
        for key in keys:
            row = self._app_repo.get_meta(key)
            if row is not None:
                results.append(row)
        return results

    def update_config_option(self, key: str, payload: dict) -> None:
        self._app_repo.upsert_meta(key, payload)

    def remove_config_option(self, key: str) -> None:
        self._app_repo.delete_meta(key)

    def remove_pipeline_state(self, library_id: int) -> None:
        """Delete all pipeline-state rows for the library.

        After this, ``get_pipeline_state`` returns ``None`` and callers fall
        back to ``PIPELINE_DEFAULTS``.
        """
        self._pipeline_repo.delete_pipeline_state(library_id)
