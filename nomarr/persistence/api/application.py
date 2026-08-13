from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, scoped_session

    from nomarr.helpers.dto.navidrome_repo_dto import NdPlayRecord, NdTrackRecord
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
    from nomarr.persistence.database.navidrome_repo import NavidromeRepo
    from nomarr.persistence.database.pipeline_repo import PipelineRepository
    from nomarr.persistence.database.song_state_repo import SongStateRepository


class AppLegacyNavidromeDb:
    """Legacy-only Navidrome persistence surface.

    These plugin-era mapping/play methods are intentionally isolated from the
    routine ``AppDb`` contract. Canonical app callers should continue to use
    the normalized ``AppDb`` routine methods; legacy compatibility access, if
    needed, stays confined to ``db.app.legacy_navidrome``.
    """

    def __init__(self, *, navidrome_repo: NavidromeRepo) -> None:
        self._navidrome_repo = navidrome_repo

    def get_nd_track(self, track_id: str) -> NdTrackRecord | None:
        return self._navidrome_repo.get_track(track_id)

    def list_nd_track_keys(self) -> list[str]:
        return self._navidrome_repo.list_nd_track_keys()


class AppDb:
    """Persistence sub-facade for app-state, locks, claims, config, and admin helpers.

    Routine methods expose the normalized app-domain intent surface. Destructive
    maintenance operations (``truncate_health``, ``truncate_worker_claims``,
    ``truncate_song_state_edges``) are exposed directly on this facade; legacy
    Navidrome persistence is isolated on ``.legacy_navidrome`` instead of the
    routine top-level API.
    """

    def __init__(
        self,
        *,
        session: scoped_session[Session],
        app_repo: AppRepository,
        library_repo: LibraryRepository,
        navidrome_repo: NavidromeRepo,
        song_state_repo: SongStateRepository,
        pipeline_repo: PipelineRepository,
    ) -> None:
        """Initialise the app persistence facade.

        All repository parameters are required and provided by the
        Database constructor.
        """
        self._song_state_repo = song_state_repo
        self._app_repo = app_repo
        self._navidrome_repo = navidrome_repo
        self._library_repo = library_repo
        self._pipeline_repo = pipeline_repo
        self._session = session
        self.legacy_navidrome: AppLegacyNavidromeDb = AppLegacyNavidromeDb(
            navidrome_repo=navidrome_repo,
        )

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

    def get_song_state(self, song_id: int) -> str | None:
        return self._song_state_repo.get_song_state(song_id)

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
        self._song_state_repo.remove_states_for_songs(song_ids)
        self.add_song_states(song_ids, state)

    def remove_song_states(self, song_ids: list[int]) -> None:
        if not song_ids:
            return
        self._song_state_repo.remove_states_for_songs(song_ids)

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
        return self._app_repo.insert_lock(payload)

    def list_locks(self) -> list[LockRow]:
        return self._app_repo.list_locks()

    def remove_lock(self, resource_id: str) -> None:
        self._app_repo.release_lock(resource_id)

    def upsert_lock(self, resource_id: str, payload: dict) -> None:
        self._app_repo.upsert_lock(resource_id, payload)

    def acquire_lock(self, resource_id: str, payload: dict) -> bool:
        return self._app_repo.acquire_lock(resource_id, payload)

    def add_claim(self, payload: dict) -> int:
        return self._app_repo.insert_worker_claim(payload)

    def remove_claim(self, song_id: int) -> None:
        self._app_repo.release_claim(song_id)

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

    def release_claim(self, song_id: int) -> None:
        """Release the worker claim for one song (alias for remove_claim)."""
        self.remove_claim(song_id)

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

    # ------------------------------------------------------------------
    # Navidrome methods
    # ------------------------------------------------------------------

    def upsert_navidrome_track(
        self,
        nd_id: str,
        title: str | None,
        artist: str | None,
        album: str | None,
        file_path: str | None,
    ) -> NdTrackRecord:
        return self._navidrome_repo.upsert_track(nd_id, title, artist, album, file_path)

    def map_navidrome_track_to_song(self, nd_id: str, song_id: int) -> None:
        self._navidrome_repo.map_track_to_file(nd_id, song_id)

    def get_mapped_file_for_navidrome_track(self, nd_id: str) -> int | None:
        return self._navidrome_repo.get_mapped_file(nd_id)

    def resolve_song_to_navidrome_track(self, song_id: int) -> str | None:
        return self._navidrome_repo.resolve_file_to_nd_track(song_id)

    def bulk_upsert_navidrome_tracks(self, nd_ids: list[str]) -> int:
        return self._navidrome_repo.bulk_upsert_tracks(nd_ids)

    def bulk_map_navidrome_tracks(self, mappings: list[dict[str, str]]) -> int:
        return self._navidrome_repo.bulk_map_tracks(mappings)

    def record_navidrome_play(
        self,
        nd_id: str,
        user_id: str | None,
        played_at: int,
        song_id: int | None = None,
    ) -> int:
        return self._navidrome_repo.record_play(nd_id, user_id, played_at, song_id)

    def get_top_navidrome_plays(self, user_id: str, top_n: int) -> list[NdPlayRecord]:
        return self._navidrome_repo.get_top_plays(user_id, top_n)

    def delete_navidrome_tracks_for_song(self, song_id: int) -> int:
        return self._navidrome_repo.delete_tracks_for_file(song_id)

    def remove_pipeline_state(self, library_id: int) -> None:
        """Delete all pipeline-state rows for the library.

        After this, ``get_pipeline_state`` returns ``None`` and callers fall
        back to ``PIPELINE_DEFAULTS``.
        """
        self._pipeline_repo.delete_pipeline_state(library_id)
