from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

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


class AppMaintenanceDb:
    """Maintenance-only companion surface for application persistence.

    Wired as ``AppDb.maintenance`` by Part A. Destructive, reset, repair,
    and diagnostics-only operations belong here, not on the routine top-level
    ``AppDb`` surface. Parts C/E add new maintenance methods here and clean
    up any remaining top-level shims.
    """

    def __init__(
        self,
        *,
        session: AsyncSession,
        app_repo: AppRepository,
        file_state_repo: FileStateRepository,
    ) -> None:
        self._app_repo = app_repo
        self._file_state_repo = file_state_repo

    async def truncate_file_state_edges(self) -> None:
        await self._file_state_repo.truncate_assignments()

    async def truncate_pipeline_states(self) -> None:
        """No-op — pipeline state is now stored as fields on library documents."""

    async def truncate_pipeline_state_edges(self) -> None:
        """No-op — pipeline state edges no longer exist."""

    async def truncate_worker_claims(self) -> None:
        await self._app_repo.truncate_worker_claims()

    async def delete_all_worker_claims(self) -> None:
        # Legacy name shim — canonical method is truncate_worker_claims. Do not add new callers.
        await self.truncate_worker_claims()

    async def truncate_health(self) -> None:
        await self._app_repo.truncate_health()

    async def list_collections(self) -> list[str]:
        return []


class AppLegacyNavidromeDb:
    """Legacy-only Navidrome persistence surface.

    These plugin-era mapping/play methods are intentionally isolated from the
    routine ``AppDb`` contract. Canonical app callers should continue to use
    the normalized ``AppDb`` routine methods; legacy compatibility access, if
    needed, stays confined to ``db.app.legacy_navidrome``.
    """

    def __init__(self, *, navidrome_repo: NavidromeRepo) -> None:
        self._navidrome_repo = navidrome_repo

    async def get_nd_track(self, track_id: str) -> NdTrackRecord | None:
        return await self._navidrome_repo.get_track(track_id)

    async def list_nd_track_keys(self) -> list[str]:
        return await self._navidrome_repo.list_nd_track_keys()


class AppDb:
    """Persistence sub-facade for app-state, locks, claims, config, and admin helpers.

    Routine methods expose the normalized app-domain intent surface. Destructive
    maintenance operations live on ``.maintenance`` and legacy Navidrome
    persistence is isolated on ``.legacy_navidrome`` instead of the routine
    top-level API.
    """

    def __init__(
        self,
        *,
        session: AsyncSession,
        app_repo: AppRepository,
        library_repo: LibraryRepository,
        navidrome_repo: NavidromeRepo,
        file_state_repo: FileStateRepository,
        pipeline_repo: PipelineRepository,
    ) -> None:
        self._file_state_repo = file_state_repo
        self._app_repo = app_repo
        self._navidrome_repo = navidrome_repo
        self._library_repo = library_repo
        self._pipeline_repo = pipeline_repo
        self.maintenance: AppMaintenanceDb = AppMaintenanceDb(
            session=session,
            app_repo=app_repo,
            file_state_repo=file_state_repo,
        )
        self.legacy_navidrome: AppLegacyNavidromeDb = AppLegacyNavidromeDb(
            navidrome_repo=navidrome_repo,
        )

    # ------------------------------------------------------------------
    # Routine top-level methods already aligned with the DD contract
    # ------------------------------------------------------------------

    async def get_file_state(self, file_id: int) -> str | None:
        return await self._file_state_repo.get_file_state(file_id)

    async def get_file_states_for_files(self, file_ids: list[int]) -> dict[int, set[str]]:
        return await self._file_state_repo.get_file_states_for_files(file_ids)

    async def list_files_in_state(self, state: str, *, limit: int | None = None) -> list[int]:
        return await self._file_state_repo.list_files_in_state(state, limit=limit)

    async def list_file_docs_in_state(
        self,
        state: str,
        *,
        limit: int | None = None,
    ) -> list[LibraryFileRow]:
        return await self._pipeline_repo.list_file_docs_in_state(state, limit=limit)

    async def count_files_in_state(self, state: str) -> int:
        return await self._file_state_repo.count_files_in_state(state)

    async def add_file_states(self, file_ids: list[int], state: str) -> None:
        for file_id in file_ids:
            await self._file_state_repo.assign_state(file_id, state)

    async def replace_file_states(self, file_ids: list[int], state: str) -> None:
        await self._file_state_repo.remove_states_for_files(file_ids)
        await self.add_file_states(file_ids, state)

    async def remove_file_states(self, file_ids: list[int]) -> None:
        if not file_ids:
            return
        await self._file_state_repo.remove_states_for_files(file_ids)

    async def get_pipeline_state(self, library_id: int) -> dict[str, str] | None:
        """Return the four pipeline axis values for a library."""
        return await self._library_repo.get_pipeline_state(library_id)

    async def update_pipeline_axis(self, library_id: int, axis_field: str, axis_value: str) -> None:
        """Update a single pipeline axis field on a library document."""
        await self._library_repo.update_pipeline_axis(library_id, axis_field, axis_value)

    async def get_libraries_in_axis_state(self, axis_field: str, axis_value: str) -> list[int]:
        """Return library ids where the given axis field matches the value."""
        return await self._library_repo.get_libraries_in_axis_state(axis_field, axis_value)

    async def get_lock(self, resource_id: str) -> LockRow | None:
        return await self._app_repo.get_lock(resource_id)

    async def add_lock(self, payload: dict) -> str:
        return await self._app_repo.insert_lock(payload)

    async def list_locks(self) -> list[LockRow]:
        return await self._app_repo.list_locks()

    async def remove_lock(self, resource_id: str) -> None:
        await self._app_repo.release_lock(resource_id)

    async def upsert_lock(self, resource_id: str, payload: dict) -> None:
        await self._app_repo.upsert_lock(resource_id, payload)

    async def acquire_lock(self, resource_id: str, payload: dict) -> bool:
        return await self._app_repo.acquire_lock(resource_id, payload)

    async def add_claim(self, payload: dict) -> int:
        return await self._app_repo.insert_worker_claim(payload)

    async def remove_claim(self, file_id: int) -> None:
        await self._app_repo.release_claim(file_id)

    async def remove_claims(
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
        removed = 0
        if worker_ids:
            removed += await self._app_repo.delete_claims_for_workers(worker_ids)
        if file_ids:
            removed += await self._app_repo.delete_claims_for_files(file_ids)
        return removed

    async def list_claims(self) -> list[WorkerClaimRow]:
        return await self._app_repo.list_claims()

    async def get_health(self, component_id: str) -> HealthRow | None:
        return await self._app_repo.get_health(component_id)

    async def count_healthy(self) -> int:
        return await self._app_repo.count_healthy()

    async def list_worker_health(self) -> list[HealthRow]:
        return await self._app_repo.list_worker_health()

    async def update_health(self, component_id: str, fields: dict) -> None:
        await self._app_repo.update_health(component_id, fields)

    async def upsert_health(self, component_id: str, fields: dict) -> None:
        await self._app_repo.upsert_health(component_id, fields)

    async def release_claim(self, file_id: int) -> None:
        """Release the worker claim for one file (alias for remove_claim)."""
        await self.remove_claim(file_id)

    async def upsert_migration(self, name: str, fields: dict) -> None:
        await self._app_repo.upsert_migration(name, fields)

    async def list_migrations(self) -> list[dict]:
        return await self._app_repo.list_migrations()

    async def add_vram_promise(self, payload: dict) -> None:
        await self._app_repo.upsert_vram_promise(payload)

    async def list_vram_promises(self) -> list[dict]:
        return await self._app_repo.get_vram_promises()

    async def remove_vram_promise(self, promise_id: int) -> None:
        await self._app_repo.delete_vram_promise(promise_id)

    async def count_vram_promises(self) -> int:
        return len(await self._app_repo.get_vram_promises())

    async def get_worker_restart_policy(self, component_id: str) -> dict | None:
        return await self._app_repo.get_worker_restart_policy(component_id)

    async def update_worker_restart_policy(self, component_id: str, fields: dict) -> None:
        await self._app_repo.upsert_worker_restart_policy(component_id, fields)

    async def upsert_worker_restart_policy(self, component_id: str, fields: dict) -> None:
        await self._app_repo.upsert_worker_restart_policy(component_id, fields)

    async def insert_session(self, payloads: list[dict]) -> None:
        await self._app_repo.insert_session(payloads)

    async def delete_session(self, session_id: str) -> None:
        await self._app_repo.delete_session(session_id)

    async def get_sessions_expiring_before(self, timestamp_ms: int, limit: int) -> list[SessionRow]:
        return await self._app_repo.get_sessions_expiring_before(timestamp_ms, limit)

    async def count_sessions(self) -> int:
        return await self._app_repo.count_sessions()

    async def delete_sessions_by_ids(self, session_ids: list[str]) -> None:
        await self._app_repo.delete_sessions_by_ids(session_ids)

    async def get_active_sessions(self, not_before_ms: int, limit: int) -> list[SessionRow]:
        return await self._app_repo.get_active_sessions(not_before_ms, limit)

    async def get_config_option(self, key: str) -> MetaRow | None:
        return await self._app_repo.get_meta(key)

    async def get_schema_version(self) -> str | None:
        """Get the schema version (stored as key='version' in meta)."""
        row = await self._app_repo.get_meta("version")
        if row is None:
            return None
        value = row["value"]
        return str(value) if value is not None else None

    async def list_config_options(self, prefix: str | None = None) -> list[MetaRow]:
        keys = await self._app_repo.list_meta_keys_by_prefix(prefix or "")
        results: list[MetaRow] = []
        for key in keys:
            row = await self._app_repo.get_meta(key)
            if row is not None:
                results.append(row)
        return results

    async def update_config_option(self, key: str, payload: dict) -> None:
        await self._app_repo.upsert_meta(key, payload)

    async def remove_config_option(self, key: str) -> None:
        await self._app_repo.delete_meta(key)

    # ------------------------------------------------------------------
    # Navidrome methods
    # ------------------------------------------------------------------

    async def upsert_navidrome_track(
        self,
        nd_id: str,
        title: str | None,
        artist: str | None,
        album: str | None,
        file_path: str | None,
    ) -> NdTrackRecord:
        return await self._navidrome_repo.upsert_track(nd_id, title, artist, album, file_path)

    async def map_navidrome_track_to_file(self, nd_id: str, file_id: int) -> None:
        await self._navidrome_repo.map_track_to_file(nd_id, file_id)

    async def get_mapped_file_for_navidrome_track(self, nd_id: str) -> int | None:
        return await self._navidrome_repo.get_mapped_file(nd_id)

    async def resolve_file_to_navidrome_track(self, file_id: int) -> str | None:
        return await self._navidrome_repo.resolve_file_to_nd_track(file_id)

    async def bulk_upsert_navidrome_tracks(self, nd_ids: list[str]) -> int:
        return await self._navidrome_repo.bulk_upsert_tracks(nd_ids)

    async def bulk_map_navidrome_tracks(self, mappings: list[dict[str, str]]) -> int:
        return await self._navidrome_repo.bulk_map_tracks(mappings)

    async def record_navidrome_play(
        self,
        nd_id: str,
        user_id: str | None,
        played_at: int,
        file_id: int | None = None,
    ) -> int:
        return await self._navidrome_repo.record_play(nd_id, user_id, played_at, file_id)

    async def get_top_navidrome_plays(self, user_id: str, top_n: int) -> list[NdPlayRecord]:
        return await self._navidrome_repo.get_top_plays(user_id, top_n)

    async def delete_navidrome_tracks_for_file(self, file_id: int) -> int:
        return await self._navidrome_repo.delete_tracks_for_file(file_id)

    async def list_collections(self) -> list[str]:
        """Return all collection/table names (empty list for PostgreSQL)."""
        return await self.maintenance.list_collections()

    async def clear_file_state_links(self) -> None:
        """Remove all file-state assignment records."""
        await self.maintenance.truncate_file_state_edges()

    async def clear_pipeline_state_links(self) -> None:
        """Remove all pipeline-state link records."""
        await self.maintenance.truncate_pipeline_state_edges()

    async def update_pipeline_state(self, library_id: int, state: str) -> None:
        """Legacy single-value pipeline state update. DEPRECATED — use update_pipeline_axis."""
        msg = "update_pipeline_state is deprecated — use update_pipeline_axis"
        raise NotImplementedError(msg)

    async def remove_pipeline_state(self, library_id: int) -> None:
        """Reset all pipeline axes to their default not_started values."""
        from nomarr.helpers.constants.pipeline_states import PIPELINE_DEFAULTS

        for axis_field, default_value in PIPELINE_DEFAULTS.items():
            await self._library_repo.update_pipeline_axis(library_id, axis_field, default_value)
