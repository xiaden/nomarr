from __future__ import annotations

from arango.exceptions import AQLQueryExecuteError

from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.database.app_aql import AppAqlOperations
from nomarr.persistence.database.file_states_aql import FileStatesAqlOperations
from nomarr.persistence.database.navidrome_aql import NavidromeAqlOperations
from nomarr.persistence.database.scan_aql import ScanAqlOperations


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
        db: SafeDatabase,
        app: AppAqlOperations,
    ) -> None:
        self._db = db
        self._app = app

    def truncate_file_state_edges(self) -> None:
        return self._app.truncate_file_state_edges()

    def truncate_scan_records(self) -> None:
        return self._app.truncate_scan_records()

    def truncate_library_scan_edges(self) -> None:
        return self._app.truncate_library_scan_edges()

    def truncate_pipeline_states(self) -> None:
        return self._app.truncate_pipeline_states()

    def truncate_pipeline_state_edges(self) -> None:
        return self._app.truncate_pipeline_state_edges()

    def truncate_worker_claims(self) -> None:
        return self._app.delete_all_worker_claims()

    def delete_all_worker_claims(self) -> None:
        # Legacy name shim — canonical method is truncate_worker_claims. Do not add new callers.
        return self.truncate_worker_claims()

    def truncate_health(self) -> None:
        return self._app.truncate_health()

    def list_collections(self) -> list[str]:
        return [c["name"] for c in self._db.collections()]


class AppLegacyNavidromeDb:
    """Legacy-only Navidrome persistence surface.

    These plugin-era mapping/play methods are intentionally isolated from the
    routine ``AppDb`` contract. Canonical app callers should continue to use
    the normalized ``AppDb`` routine methods; legacy compatibility access, if
    needed, stays confined to ``db.app.legacy_navidrome``.
    """

    def __init__(self, *, navidrome: NavidromeAqlOperations) -> None:
        self._navidrome = navidrome

    def get_nd_track(self, track_id: str) -> dict | None:
        return self._navidrome.get_nd_track(track_id)

    def upsert_nd_track(self, payload: dict) -> None:
        return self._navidrome.upsert_nd_track(payload)

    def delete_nd_tracks_for_file(self, file_id: str) -> None:
        return self._navidrome.delete_nd_tracks_for_file(file_id)

    def list_nd_track_keys(self) -> list[str]:
        return self._navidrome.list_nd_track_keys()

    def bulk_upsert_nd_tracks(self, nd_ids: list[str]) -> int:
        return self._navidrome.bulk_upsert_nd_tracks(nd_ids)

    def delete_nd_tracks_cascade(self, nd_ids: list[str]) -> int:
        return self._navidrome.delete_nd_tracks_cascade(nd_ids)

    def ensure_nd_file_link(self, nd_id: str, file_id: str) -> None:
        return self._navidrome.ensure_nd_file_link(nd_id, file_id)

    def bulk_ensure_nd_file_links(self, mappings: list[dict]) -> int:
        return self._navidrome.bulk_ensure_nd_file_links(mappings)

    def resolve_nd_track_to_file(self, nd_id: str) -> str | None:
        return self._navidrome.resolve_nd_track_to_file(nd_id)

    def resolve_file_to_nd_track(self, file_id: str) -> str | None:
        return self._navidrome.resolve_file_to_nd_track(file_id)

    def bulk_resolve_nd_tracks_to_files(self, nd_ids: list[str]) -> dict[str, str]:
        return self._navidrome.bulk_resolve_nd_tracks_to_files(nd_ids)

    def bulk_resolve_files_to_nd_ids(self, file_ids: list[str]) -> dict[str, str]:
        return self._navidrome.bulk_resolve_files_to_nd_ids(file_ids)

    def upsert_nd_playcount(
        self,
        user_id: str,
        nd_id: str,
        playcount: int,
        last_played: int,
    ) -> None:
        return self._navidrome.upsert_nd_playcount(user_id, nd_id, playcount, last_played)

    def increment_nd_play(self, user_id: str, nd_id: str, timestamp_ms: int) -> None:
        return self._navidrome.increment_nd_play(user_id, nd_id, timestamp_ms)

    def bulk_upsert_nd_plays(self, user_id: str, plays: list[dict]) -> int:
        return self._navidrome.bulk_upsert_nd_plays(user_id, plays)

    def get_top_nd_plays(self, user_id: str, top_n: int) -> list[dict]:
        return self._navidrome.get_top_nd_plays(user_id, top_n)

    def get_nd_id_edge(self, track_id: str) -> dict | None:
        return self._navidrome.get_nd_id_edge(track_id)


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
        db: SafeDatabase,
        file_states: FileStatesAqlOperations,
        scan: ScanAqlOperations,
        app: AppAqlOperations,
        navidrome: NavidromeAqlOperations,
    ) -> None:
        self._db = db
        self._file_states = file_states
        self._scan = scan
        self._app = app
        self._navidrome = navidrome
        self.maintenance: AppMaintenanceDb = AppMaintenanceDb(
            db=db,
            app=app,
        )
        self.legacy_navidrome: AppLegacyNavidromeDb = AppLegacyNavidromeDb(
            navidrome=navidrome,
        )

    # ------------------------------------------------------------------
    # Routine top-level methods already aligned with the DD contract
    # ------------------------------------------------------------------

    def get_file_state(self, file_id: str) -> str | None:
        return self._file_states.get_file_state(file_id)

    def list_files_in_state(self, state: str, *, limit: int | None = None) -> list[str]:
        return self._file_states.list_files_in_state(state, limit=limit)

    def list_file_docs_in_state(
        self,
        state: str,
        *,
        limit: int | None = None,
    ) -> list[dict]:
        return self._app.list_file_docs_in_state(state, limit=limit)

    def count_files_in_state(self, state: str) -> int:
        return self._file_states.count_files_in_state(state)

    def add_file_states(self, file_ids: list[str], state: str) -> None:
        for file_id in file_ids:
            self._file_states.add_file_state_edge(file_id, state)

    def replace_file_states(self, file_ids: list[str], state: str) -> None:
        self.remove_file_states(file_ids)
        self.add_file_states(file_ids, state)

    def remove_file_states(self, file_ids: list[str]) -> None:
        if not file_ids:
            return
        self._file_states.delete_file_state_edges(file_ids)

    def get_scan(self, library_id: str) -> dict | None:
        return self._scan.get_scan_record(library_id)

    def add_scan(self, library_id: str, payload: dict) -> None:
        scan_payload = dict(payload)
        scan_payload.setdefault("library_id", library_id)
        scan_id = self._scan.add_scan_record(scan_payload)
        self._app.upsert_library_scan_edge(library_id, scan_id)

    def update_scan(self, library_id: str, fields: dict) -> None:
        existing_scan = self.get_scan(library_id)
        scan_id = existing_scan.get("_id") if isinstance(existing_scan, dict) else None
        if isinstance(scan_id, str) and scan_id:
            self._scan.update_scan_record(scan_id, fields)
            self._app.upsert_library_scan_edge(library_id, scan_id)
            return
        self.add_scan(library_id, fields)

    def remove_scan(self, library_id: str) -> None:
        existing_scan = self.get_scan(library_id)
        scan_id = existing_scan.get("_id") if isinstance(existing_scan, dict) else None
        if isinstance(scan_id, str) and scan_id:
            self._scan._delete_scan_record(scan_id)
        self._app.delete_library_scan_edge(library_id)

    def get_pipeline_state(self, library_id: str) -> str | None:
        doc = self._app.get_pipeline_state_doc(library_id)
        if not isinstance(doc, dict):
            return None
        state = doc.get("state")
        return state if isinstance(state, str) else None

    def get_lock(self, resource_id: str) -> dict | None:
        return self._app.get_lock(resource_id)

    def add_lock(self, payload: dict) -> str:
        return self._app.insert_lock(payload)

    def list_locks(self) -> list[dict]:
        return self._app.list_locks()

    def remove_lock(self, resource_id: str) -> None:
        return self._app.release_lock(resource_id)

    def add_claim(self, payload: dict) -> str:
        return self._app.insert_worker_claim(payload)

    def remove_claim(self, file_id: str) -> None:
        return self._app.release_claim(file_id)

    def remove_claims(
        self,
        *,
        worker_ids: list[str] | None = None,
        file_ids: list[str] | None = None,
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
            removed += self._app.delete_claims_for_workers(worker_ids)
        if file_ids:
            removed += self._app.delete_claims_for_files(file_ids)
        return removed

    def list_claims(self) -> list[dict]:
        return self._app.list_claims()

    def count_claims(self) -> int:
        return self._app.count_claims()

    def get_health(self, component_id: str) -> dict | None:
        return self._app.get_health(component_id)

    def count_healthy(self) -> int:
        return self._app.count_healthy()

    def list_worker_health(self) -> list[dict]:
        return self._app.list_worker_health()

    def update_health(self, component_id: str, fields: dict) -> None:
        return self._app.update_health(component_id, fields)

    def release_claim(self, file_id: str) -> None:
        """Release the worker claim for one file (alias for remove_claim)."""
        return self.remove_claim(file_id)

    def list_collections(self) -> list[str]:
        """Return all ArangoDB collection names."""
        return self.maintenance.list_collections()

    def clear_file_state_links(self) -> None:
        """Remove all file-state assignment records."""
        return self.maintenance.truncate_file_state_edges()

    def clear_library_scan_links(self) -> None:
        """Remove all library-scan link records."""
        return self.maintenance.truncate_library_scan_edges()

    def clear_pipeline_state_links(self) -> None:
        """Remove all pipeline-state link records."""
        return self.maintenance.truncate_pipeline_state_edges()

    def clear_scans(self) -> None:
        """Remove all scan records."""
        return self.maintenance.truncate_scan_records()

    def get_config_option(self, key: str) -> dict | None:
        try:
            return self._app.get_meta(key)
        except AQLQueryExecuteError as exc:
            # ERR 1203: collection or view not found — database is not yet
            # initialised. Semantically equivalent to "no value stored".
            if exc.error_code == 1203:
                return None
            raise

    def get_schema_version(self) -> str | None:
        """Get the schema version (stored as ``_key='version'`` in meta)."""
        try:
            return self._app.get_schema_version()
        except AQLQueryExecuteError as exc:
            if exc.error_code == 1203:
                return None
            raise

    def list_config_options(self, prefix: str | None = None) -> list[dict]:
        keys = self._app.list_meta_keys_by_prefix(prefix or "")
        docs: list[dict] = []
        for key in keys:
            doc = self._app.get_meta(key)
            if isinstance(doc, dict):
                docs.append(doc)
        return docs

    def update_config_option(self, key: str, payload: dict) -> None:
        return self._app.upsert_meta(key, payload)

    def remove_config_option(self, key: str) -> None:
        return self._app.delete_meta(key)

    def list_migrations(self) -> list[dict]:
        return self._app.list_migrations()

    def add_vram_promise(self, payload: dict) -> None:
        return self._app.upsert_vram_promise(payload)

    def list_vram_promises(self) -> list[dict]:
        return self._app.get_vram_promises()

    def remove_vram_promise(self, promise_id: str) -> None:
        return self._app.delete_vram_promise(promise_id)

    def count_vram_promises(self) -> int:
        return self._app.count_vram_promises()

    def update_pipeline_state(self, library_id: str, state: str) -> None:
        return self._app.update_pipeline_state(library_id, state)

    def remove_pipeline_state(self, library_id: str) -> None:
        self._app.delete_pipeline_state(library_id)
        self._app.delete_pipeline_state_edges_for_library(library_id)

    def insert_session(self, payload: list[dict]) -> None:
        return self._app.insert_session(payload)

    def delete_session(self, session_id: str) -> None:
        return self._app.delete_session(session_id)

    def get_sessions_expiring_before(self, timestamp_ms: int, limit: int) -> list[dict]:
        return self._app.get_sessions_expiring_before(timestamp_ms, limit)

    def count_sessions(self) -> int:
        return self._app.count_sessions()

    def delete_sessions_by_ids(self, ids: list[str]) -> None:
        return self._app.delete_sessions_by_ids(ids)

    def get_active_sessions(self, not_before_ms: int, limit: int) -> list[dict]:
        return self._app.get_active_sessions(not_before_ms, limit)

    def get_worker_restart_policy(self, component_id: str) -> dict | None:
        return self._app.get_worker_restart_policy(component_id)

    def update_worker_restart_policy(self, component_id: str, fields: dict) -> None:
        return self._app.update_worker_restart_policy(component_id, fields)

    def upsert_worker_restart_policy(self, component_id: str, fields: dict) -> None:
        return self._app.upsert_worker_restart_policy(component_id, fields)

    def upsert_migration(self, name: str, fields: dict) -> None:
        return self._app.upsert_migration(name, fields)
