from __future__ import annotations

from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.database.app_aql import AppAqlOperations
from nomarr.persistence.database.file_states_aql import FileStatesAqlOperations
from nomarr.persistence.database.navidrome_aql import NavidromeAqlOperations
from nomarr.persistence.database.scan_aql import ScanAqlOperations


class AppDb:
    """Persistence sub-facade for application-state, scan, lock, and Navidrome operations."""

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

    def get_file_state(self, file_id: str) -> str | None:
        return self._file_states.get_file_state(file_id)

    def list_files_in_state(self, state: str, *, limit: int | None = None) -> list[str]:
        return self._file_states.list_files_in_state(state, limit=limit)

    def list_file_docs_in_state(self, state: str, *, limit: int | None = None) -> list[dict]:
        return self._app.list_file_docs_in_state(state, limit=limit)

    def get_state_edges_for_files(self, file_ids: list[str]) -> list[dict]:
        return self._app.get_state_edges_for_files(file_ids)

    def transition_file_states(self, file_ids: list[str], from_state: str, to_state: str) -> None:
        return self._file_states.transition_file_states(file_ids, from_state, to_state)

    def add_file_state_edge(self, file_id: str, state: str) -> None:
        return self._file_states.add_file_state_edge(file_id, state)

    def delete_file_state_edges(self, file_ids: list[str]) -> None:
        return self._file_states.delete_file_state_edges(file_ids)

    def count_files_in_state(self, state: str) -> int:
        return self._file_states.count_files_in_state(state)

    def get_scan_record(self, library_id: str) -> dict | None:
        return self._scan.get_scan_record(library_id)

    def add_scan_record(self, payload: dict) -> str:
        return self._scan.add_scan_record(payload)

    def update_scan_record(self, scan_id: str, fields: dict) -> None:
        return self._scan.update_scan_record(scan_id, fields)

    def delete_scan_record(self, scan_id: str) -> None:
        return self._scan.delete_scan_record(scan_id)

    def upsert_library_scan_edge(self, library_id: str, scan_id: str) -> None:
        return self._app.upsert_library_scan_edge(library_id, scan_id)

    def delete_library_scan_edge(self, library_id: str) -> None:
        return self._app.delete_library_scan_edge(library_id)

    def delete_scan_records_for_library(self, library_key: str) -> int:
        return self._app.delete_scan_records_for_library(library_key)

    def upsert_pipeline_state(self, library_id: str, state: str) -> None:
        return self._app.upsert_pipeline_state(library_id, state)

    def get_pipeline_state_doc(self, library_id: str) -> dict | None:
        return self._app.get_pipeline_state_doc(library_id)

    def update_pipeline_state(self, library_id: str, state: str) -> None:
        return self._app.update_pipeline_state(library_id, state)

    def delete_pipeline_state(self, library_id: str) -> int:
        return self._app.delete_pipeline_state(library_id)

    def count_pipeline_states(self) -> int:
        return self._app.count_pipeline_states()

    def list_libraries_in_pipeline_state(self, state: str) -> list[dict]:
        return self._app.list_libraries_in_pipeline_state(state)

    def delete_pipeline_state_edges_for_library(self, library_id: str) -> None:
        return self._app.delete_pipeline_state_edges_for_library(library_id)

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

    def insert_lock(self, payload: dict) -> str:
        return self._app.insert_lock(payload)

    def upsert_lock(self, resource_id: str, payload: dict) -> None:
        return self._app.upsert_lock(resource_id, payload)

    def release_lock(self, resource_id: str) -> None:
        return self._app.release_lock(resource_id)

    def get_lock(self, resource_id: str) -> dict | None:
        return self._app.get_lock(resource_id)

    def acquire_lock(self, resource_id: str, payload: dict) -> bool:
        return self._app.acquire_lock(resource_id, payload)

    def list_locks(self) -> list[dict]:
        return self._app.list_locks()

    def insert_worker_claim(self, payload: dict) -> None:
        return self._app.insert_worker_claim(payload)

    def claim_file(self, file_id: str, worker_id: str, payload: dict) -> None:
        return self._app.claim_file(file_id, worker_id, payload)

    def release_claim(self, file_id: str) -> None:
        return self._app.release_claim(file_id)

    def delete_claims_for_workers(self, worker_ids: list[str]) -> int:
        return self._app.delete_claims_for_workers(worker_ids)

    def delete_claims_for_files(self, file_ids: list[str]) -> int:
        return self._app.delete_claims_for_files(file_ids)

    def steal_claim(self, payload: dict, now: int, lease_ms: int) -> bool:
        return self._app.steal_claim(payload, now, lease_ms)

    def list_claims(self) -> list[dict]:
        return self._app.list_claims()

    def aggregate_worker_claims(self) -> list[dict]:
        return self._app.aggregate_worker_claims()

    def count_worker_claims(self) -> int:
        return self._app.count_worker_claims()

    def count_claims(self) -> int:
        return self._app.count_claims()

    def delete_all_worker_claims(self) -> None:
        return self._app.delete_all_worker_claims()

    def get_health(self, component_id: str) -> dict | None:
        return self._app.get_health(component_id)

    def count_healthy(self) -> int:
        return self._app.count_healthy()

    def list_worker_health(self) -> list[dict]:
        return self._app.list_worker_health()

    def truncate_health(self) -> None:
        return self._app.truncate_health()

    def upsert_health(self, component_id: str, fields: dict) -> None:
        return self._app.upsert_health(component_id, fields)

    def update_health(self, component_id: str, fields: dict) -> None:
        return self._app.update_health(component_id, fields)

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

    def count_calibration_states(self) -> int:
        return self._app.count_calibration_states()

    def get_meta(self, key: str) -> dict | None:
        return self._app.get_meta(key)

    def upsert_meta(self, key: str, payload: dict) -> None:
        return self._app.upsert_meta(key, payload)

    def delete_meta(self, key: str) -> None:
        return self._app.delete_meta(key)

    def list_meta_keys_by_prefix(self, prefix: str) -> list[str]:
        return self._app.list_meta_keys_by_prefix(prefix)

    def upsert_migration(self, name: str, fields: dict) -> None:
        return self._app.upsert_migration(name, fields)

    def list_migrations(self) -> list[dict]:
        return self._app.list_migrations()

    def upsert_vram_promise(self, payload: dict) -> None:
        return self._app.upsert_vram_promise(payload)

    def get_vram_promises(self) -> list[dict]:
        return self._app.get_vram_promises()

    def delete_vram_promise(self, promise_id: str) -> None:
        return self._app.delete_vram_promise(promise_id)

    def count_vram_promises(self) -> int:
        return self._app.count_vram_promises()

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

    def upsert_nd_playcount(self, user_id: str, nd_id: str, playcount: int, last_played: int) -> None:
        return self._navidrome.upsert_nd_playcount(user_id, nd_id, playcount, last_played)

    def increment_nd_play(self, user_id: str, nd_id: str, timestamp_ms: int) -> None:
        return self._navidrome.increment_nd_play(user_id, nd_id, timestamp_ms)

    def bulk_upsert_nd_plays(self, user_id: str, plays: list[dict]) -> int:
        return self._navidrome.bulk_upsert_nd_plays(user_id, plays)

    def get_top_nd_plays(self, user_id: str, top_n: int) -> list[dict]:
        return self._navidrome.get_top_nd_plays(user_id, top_n)

    def get_nd_id_edge(self, track_id: str) -> dict | None:
        return self._navidrome.get_nd_id_edge(track_id)

    def list_collections(self) -> list[str]:
        return list(self._db.collections())
