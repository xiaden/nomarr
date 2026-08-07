from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, cast

from nomarr.helpers.exceptions import FacadeMisuseError

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from sqlalchemy.orm import Session, scoped_session

    from nomarr.helpers.dto.navidrome_repo_dto import NdPlayRecord, NdTrackRecord
    from nomarr.helpers.dto.repo_dto import (
        HealthRow,
        LibraryFileRow,
        LockRow,
        MetaRow,
        SessionRow,
        WorkerClaimRow,
    )
    from nomarr.persistence.database.app_repo import AppRepository
    from nomarr.persistence.database.file_state_repo import FileStateRepository
    from nomarr.persistence.database.library_repo import LibraryRepository
    from nomarr.persistence.database.navidrome_repo import NavidromeRepo
    from nomarr.persistence.database.pipeline_repo import PipelineRepository


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
    ``truncate_file_state_edges``) are exposed directly on this facade; legacy
    Navidrome persistence is isolated on ``.legacy_navidrome`` instead of the
    routine top-level API.

    READ/WRITE classification (AR-2): READ methods use SQLAlchemy autobegin
    and need no transaction context; WRITE methods (inserts/updates/deletes/
    upserts/truncates) must be called inside ``transaction()`` and raise
    :class:`FacadeMisuseError` otherwise.

    READ:   get_file_state, get_file_states_for_files, list_files_in_state,
            list_file_docs_in_state, count_files_in_state, get_pipeline_state,
            get_libraries_in_axis_state, get_lock, list_locks, list_claims,
            get_health, count_healthy, list_worker_health, list_migrations,
            list_vram_promises, count_vram_promises, get_worker_restart_policy,
            get_sessions_expiring_before, count_sessions, get_active_sessions,
            get_config_option, get_schema_version, list_config_options,
            get_mapped_file_for_navidrome_track, resolve_file_to_navidrome_track,
            get_top_navidrome_plays
    WRITE:  truncate_file_state_edges, truncate_worker_claims, truncate_health,
            add_file_states, replace_file_states, remove_file_states,
            update_pipeline_axis, add_lock, remove_lock, upsert_lock,
            acquire_lock, add_claim, remove_claim, remove_claims, update_health,
            upsert_health, release_claim, upsert_migration,
            record_migration_started, mark_migration_applied, add_vram_promise,
            promise_vram, remove_vram_promise, release_vram,
            release_all_for_worker, update_worker_restart_policy,
            upsert_worker_restart_policy, insert_session, delete_session,
            delete_sessions_by_ids, update_config_option, remove_config_option,
            upsert_navidrome_track, map_navidrome_track_to_file,
            bulk_upsert_navidrome_tracks, bulk_map_navidrome_tracks,
            record_navidrome_play, delete_navidrome_tracks_for_file,
            remove_pipeline_state
    """

    def __init__(
        self,
        *,
        session: scoped_session[Session],
        app_repo: AppRepository,
        library_repo: LibraryRepository,
        navidrome_repo: NavidromeRepo,
        file_state_repo: FileStateRepository,
        pipeline_repo: PipelineRepository,
    ) -> None:
        """Initialise the app persistence facade.

        All repository parameters are required and provided by the
        Database constructor.
        """
        self._file_state_repo = file_state_repo
        self._app_repo = app_repo
        self._navidrome_repo = navidrome_repo
        self._library_repo = library_repo
        self._pipeline_repo = pipeline_repo
        self._session = session
        self.legacy_navidrome: AppLegacyNavidromeDb = AppLegacyNavidromeDb(
            navidrome_repo=navidrome_repo,
        )

    def transaction(self) -> AbstractContextManager[Session]:
        """Return a ``session.begin()`` context manager for write operations (AR-2).

        Must be entered FIRST, before any write method call. If a read method
        already autobegun a transaction, warn and reuse it instead of ending it:
        committing an active transaction here would make SQLAlchemy raise
        ``InvalidRequestError`` on the next session use when the transaction was
        opened by an enclosing ``transaction()`` (``_trans_ctx_check`` rejects a
        closed-but-still-registered context manager), and an autobegun read
        transaction only needs to be committed by the returned context manager
        at exit. Reusing the active transaction is lossless and safe.
        """
        if cast("Session", self._session).in_transaction():
            warnings.warn(
                "Transaction already active — did you call a read method before entering the context?", stacklevel=2
            )
            active = cast("Session", self._session).get_transaction()
            if active is not None:
                return cast("AbstractContextManager[Session]", active)
        return cast("AbstractContextManager[Session]", self._session.begin())

    def _require_transaction(self, method_name: str) -> None:
        """Raise :class:`FacadeMisuseError` when no transaction is active (AR-2)."""
        if not cast("Session", self._session).in_transaction():
            raise FacadeMisuseError(
                f"{type(self).__name__}.{method_name}() is a write method — call within a transaction() context"
            )

    # ------------------------------------------------------------------
    # Maintenance methods (destructive reset/repair)
    # ------------------------------------------------------------------

    def truncate_file_state_edges(self) -> None:
        """Truncate all file-state assignment edges."""
        self._require_transaction("truncate_file_state_edges")
        self._file_state_repo.truncate_assignments()

    def truncate_worker_claims(self) -> None:
        """Truncate all worker claims."""
        self._require_transaction("truncate_worker_claims")
        self._app_repo.truncate_worker_claims()

    def truncate_health(self) -> None:
        """Truncate all health rows."""
        self._require_transaction("truncate_health")
        self._app_repo.truncate_health()

    # ------------------------------------------------------------------
    # Routine top-level methods already aligned with the DD contract
    # ------------------------------------------------------------------

    def get_file_state(self, file_id: int) -> str | None:
        return self._file_state_repo.get_file_state(file_id)

    def get_file_states_for_files(self, file_ids: list[int]) -> dict[int, set[str]]:
        return self._file_state_repo.get_file_states_for_files(file_ids)

    def list_files_in_state(self, state: str, *, limit: int | None = None) -> list[int]:
        return self._file_state_repo.list_files_in_state(state, limit=limit)

    def list_file_docs_in_state(
        self,
        state: str,
        *,
        limit: int | None = None,
    ) -> list[LibraryFileRow]:
        return self._pipeline_repo.list_file_docs_in_state(state, limit=limit)

    def count_files_in_state(self, state: str) -> int:
        return self._file_state_repo.count_files_in_state(state)

    def add_file_states(self, file_ids: list[int], state: str) -> None:
        self._require_transaction("add_file_states")
        for file_id in file_ids:
            self._file_state_repo.assign_state(file_id, state)

    def replace_file_states(self, file_ids: list[int], state: str) -> None:
        self._require_transaction("replace_file_states")
        self._file_state_repo.remove_states_for_files(file_ids)
        self.add_file_states(file_ids, state)

    def remove_file_states(self, file_ids: list[int]) -> None:
        self._require_transaction("remove_file_states")
        if not file_ids:
            return
        self._file_state_repo.remove_states_for_files(file_ids)

    def get_pipeline_state(self, library_id: int) -> dict[str, str] | None:
        """Return the four pipeline axis values for a library."""
        return self._library_repo.get_pipeline_state(library_id)

    def update_pipeline_axis(self, library_id: int, axis_field: str, axis_value: str) -> None:
        """Update a single pipeline axis field on a library document."""
        self._require_transaction("update_pipeline_axis")
        self._library_repo.update_pipeline_axis(library_id, axis_field, axis_value)

    def get_libraries_in_axis_state(self, axis_field: str, axis_value: str) -> list[int]:
        """Return library ids where the given axis field matches the value."""
        return self._library_repo.get_libraries_in_axis_state(axis_field, axis_value)

    def get_lock(self, resource_id: str) -> LockRow | None:
        return self._app_repo.get_lock(resource_id)

    def add_lock(self, payload: dict) -> str:
        self._require_transaction("add_lock")
        return self._app_repo.insert_lock(payload)

    def list_locks(self) -> list[LockRow]:
        return self._app_repo.list_locks()

    def remove_lock(self, resource_id: str) -> None:
        self._require_transaction("remove_lock")
        self._app_repo.release_lock(resource_id)

    def upsert_lock(self, resource_id: str, payload: dict) -> None:
        self._require_transaction("upsert_lock")
        self._app_repo.upsert_lock(resource_id, payload)

    def acquire_lock(self, resource_id: str, payload: dict) -> bool:
        self._require_transaction("acquire_lock")
        return self._app_repo.acquire_lock(resource_id, payload)

    def add_claim(self, payload: dict) -> int:
        self._require_transaction("add_claim")
        return self._app_repo.insert_worker_claim(payload)

    def remove_claim(self, file_id: int) -> None:
        self._require_transaction("remove_claim")
        self._app_repo.release_claim(file_id)

    def remove_claims(
        self,
        *,
        worker_ids: list[str] | None = None,
        file_ids: list[int] | None = None,
    ) -> int:
        """Delete claims matching the supplied worker ids and/or file ids.

        Args:
            worker_ids: Optional worker ids whose claims should be removed.
            file_ids: Optional file ids whose claims should be removed.

        Returns:
            Total number of claims removed across both filters.

        """
        self._require_transaction("remove_claims")
        removed = 0
        if worker_ids:
            removed += self._app_repo.delete_claims_for_workers(worker_ids)
        if file_ids:
            removed += self._app_repo.delete_claims_for_files(file_ids)
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
        self._require_transaction("update_health")
        self._app_repo.update_health(component_id, fields)

    def upsert_health(self, component_id: str, fields: dict) -> None:
        self._require_transaction("upsert_health")
        self._app_repo.upsert_health(component_id, fields)

    def release_claim(self, file_id: int) -> None:
        """Release the worker claim for one file (alias for remove_claim)."""
        self._require_transaction("release_claim")
        self.remove_claim(file_id)

    def upsert_migration(self, name: str, fields: dict) -> None:
        self._require_transaction("upsert_migration")
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
        self._require_transaction("record_migration_started")
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
        self._require_transaction("mark_migration_applied")
        self.upsert_migration(migration_id, {"status": "applied"})

    def add_vram_promise(self, payload: dict) -> None:
        self._require_transaction("add_vram_promise")
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
        self._require_transaction("promise_vram")
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
        self._require_transaction("remove_vram_promise")
        self._app_repo.delete_vram_promise(promise_id)

    def release_vram(self, *, worker_id: str, model_path: str) -> None:
        """Release the VRAM promise(s) for a worker+model in one atomic transaction."""
        self._require_transaction("release_vram")
        self._app_repo.delete_vram_promise_by_worker_model(worker_id, model_path)

    def release_all_for_worker(self, *, worker_id: str) -> None:
        """Release all VRAM promises held by a worker.

        Preserves the list-then-remove loop semantics of the absorbed
        VRAM-promises adapter (no ``FOR UPDATE`` — the plan does not
        require row-locking for this method).
        """
        self._require_transaction("release_all_for_worker")
        for p in self.list_vram_promises():
            if p.get("worker_id") == worker_id:
                pid = p.get("id")
                if pid:
                    # Call the repo directly: remove_vram_promise is guarded and
                    # re-checks the transaction per call, but the repo commits
                    # internally, ending the session transaction after each row
                    # — so a loop through a guarded public method would raise
                    # FacadeMisuseError on the second promise even inside a
                    # transaction() block.
                    self._app_repo.delete_vram_promise(pid)

    def count_vram_promises(self) -> int:
        return len(self._app_repo.get_vram_promises())

    def get_worker_restart_policy(self, component_id: str) -> dict | None:
        return self._app_repo.get_worker_restart_policy(component_id)

    def update_worker_restart_policy(self, component_id: str, fields: dict) -> None:
        self._require_transaction("update_worker_restart_policy")
        self._app_repo.upsert_worker_restart_policy(component_id, fields)

    def upsert_worker_restart_policy(self, component_id: str, fields: dict) -> None:
        self._require_transaction("upsert_worker_restart_policy")
        self._app_repo.upsert_worker_restart_policy(component_id, fields)

    def insert_session(self, payloads: list[dict]) -> None:
        self._require_transaction("insert_session")
        self._app_repo.insert_session(payloads)

    def delete_session(self, session_id: str) -> None:
        self._require_transaction("delete_session")
        self._app_repo.delete_session(session_id)

    def get_sessions_expiring_before(self, timestamp_ms: int, limit: int) -> list[SessionRow]:
        return self._app_repo.get_sessions_expiring_before(timestamp_ms, limit)

    def count_sessions(self) -> int:
        return self._app_repo.count_sessions()

    def delete_sessions_by_ids(self, session_ids: list[str]) -> None:
        self._require_transaction("delete_sessions_by_ids")
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
        self._require_transaction("update_config_option")
        self._app_repo.upsert_meta(key, payload)

    def remove_config_option(self, key: str) -> None:
        self._require_transaction("remove_config_option")
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
        self._require_transaction("upsert_navidrome_track")
        return self._navidrome_repo.upsert_track(nd_id, title, artist, album, file_path)

    def map_navidrome_track_to_file(self, nd_id: str, file_id: int) -> None:
        self._require_transaction("map_navidrome_track_to_file")
        self._navidrome_repo.map_track_to_file(nd_id, file_id)

    def get_mapped_file_for_navidrome_track(self, nd_id: str) -> int | None:
        return self._navidrome_repo.get_mapped_file(nd_id)

    def resolve_file_to_navidrome_track(self, file_id: int) -> str | None:
        return self._navidrome_repo.resolve_file_to_nd_track(file_id)

    def bulk_upsert_navidrome_tracks(self, nd_ids: list[str]) -> int:
        self._require_transaction("bulk_upsert_navidrome_tracks")
        return self._navidrome_repo.bulk_upsert_tracks(nd_ids)

    def bulk_map_navidrome_tracks(self, mappings: list[dict[str, str]]) -> int:
        self._require_transaction("bulk_map_navidrome_tracks")
        return self._navidrome_repo.bulk_map_tracks(mappings)

    def record_navidrome_play(
        self,
        nd_id: str,
        user_id: str | None,
        played_at: int,
        file_id: int | None = None,
    ) -> int:
        self._require_transaction("record_navidrome_play")
        return self._navidrome_repo.record_play(nd_id, user_id, played_at, file_id)

    def get_top_navidrome_plays(self, user_id: str, top_n: int) -> list[NdPlayRecord]:
        return self._navidrome_repo.get_top_plays(user_id, top_n)

    def delete_navidrome_tracks_for_file(self, file_id: int) -> int:
        self._require_transaction("delete_navidrome_tracks_for_file")
        return self._navidrome_repo.delete_tracks_for_file(file_id)

    def remove_pipeline_state(self, library_id: int) -> None:
        """Reset all pipeline axes to their default not_started values."""
        self._require_transaction("remove_pipeline_state")
        from nomarr.helpers.constants.pipeline_states import PIPELINE_DEFAULTS

        for axis_field, default_value in PIPELINE_DEFAULTS.items():
            self._library_repo.update_pipeline_axis(library_id, axis_field, default_value)
