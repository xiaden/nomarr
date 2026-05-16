# mypy: disable-error-code=func-returns-value
"""Unit tests for ``AppDb`` delegation."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch, sentinel

import pytest

from nomarr.persistence.api.application import AppDb, AppMaintenanceDb


def _make_app_db() -> tuple[AppDb, MagicMock, MagicMock, MagicMock, MagicMock]:
    file_states = MagicMock()
    scan = MagicMock()
    app = MagicMock()
    navidrome = MagicMock()
    raw_db = MagicMock()
    db = AppDb(db=raw_db, file_states=file_states, scan=scan, app=app, navidrome=navidrome)
    return db, file_states, scan, app, navidrome


def _make_app_maintenance_db() -> tuple[AppMaintenanceDb, MagicMock, MagicMock]:
    raw_db = MagicMock()
    app = MagicMock()
    db = AppMaintenanceDb(db=raw_db, app=app)
    return db, raw_db, app


@pytest.mark.unit
def test_get_file_state_delegates_to_file_states() -> None:
    db, file_states, _, _, _ = _make_app_db()
    file_states.get_file_state.return_value = sentinel.result

    result = db.get_file_state("library_files/1")

    assert result is sentinel.result
    file_states.get_file_state.assert_called_once_with("library_files/1")


@pytest.mark.unit
def test_list_files_in_state_delegates_to_file_states() -> None:
    db, file_states, _, _, _ = _make_app_db()
    file_states.list_files_in_state.return_value = sentinel.result

    result = db.list_files_in_state("queued", limit=12)

    assert result is sentinel.result
    file_states.list_files_in_state.assert_called_once_with("queued", limit=12)


@pytest.mark.unit
def test_count_files_in_state_delegates_to_file_states() -> None:
    db, file_states, _, _, _ = _make_app_db()
    file_states.count_files_in_state.return_value = sentinel.result

    result = db.count_files_in_state("queued")

    assert result is sentinel.result
    file_states.count_files_in_state.assert_called_once_with("queued")


@pytest.mark.unit
def test_get_lock_delegates_to_app() -> None:
    db, _, _, app, _ = _make_app_db()
    app.get_lock.return_value = sentinel.result

    result = db.get_lock("scan:1")

    assert result is sentinel.result
    app.get_lock.assert_called_once_with("scan:1")


@pytest.mark.unit
def test_get_health_delegates_to_app() -> None:
    db, _, _, app, _ = _make_app_db()
    app.get_health.return_value = sentinel.result

    result = db.get_health("ml-worker")

    assert result is sentinel.result
    app.get_health.assert_called_once_with("ml-worker")


@pytest.mark.unit
def test_list_worker_health_delegates_to_app() -> None:
    db, _, _, app, _ = _make_app_db()
    app.list_worker_health.return_value = sentinel.result

    result = db.list_worker_health()

    assert result is sentinel.result
    app.list_worker_health.assert_called_once_with()


@pytest.mark.unit
def test_update_health_delegates_to_app() -> None:
    db, _, _, app, _ = _make_app_db()
    fields = {"status": "healthy", "heartbeat_ms": 1234}
    app.update_health.return_value = None

    result = db.update_health("ml-worker", fields)

    assert result is None
    app.update_health.assert_called_once_with("ml-worker", fields)


@pytest.mark.unit
def test_count_healthy_delegates_to_app() -> None:
    db, _, _, app, _ = _make_app_db()
    app.count_healthy.return_value = sentinel.result

    result = db.count_healthy()

    assert result is sentinel.result
    app.count_healthy.assert_called_once_with()


@pytest.mark.unit
def test_count_vram_promises_delegates_to_app() -> None:
    db, _, _, app, _ = _make_app_db()
    app.count_vram_promises.return_value = sentinel.result

    result = db.count_vram_promises()

    assert result is sentinel.result
    app.count_vram_promises.assert_called_once_with()


@pytest.mark.unit
def test_legacy_navidrome_surface_get_nd_track_delegates_to_navidrome() -> None:
    db, _, _, _, navidrome = _make_app_db()
    navidrome.get_nd_track.return_value = sentinel.result

    result = db.legacy_navidrome.get_nd_track("navidrome_tracks/1")

    assert result is sentinel.result
    navidrome.get_nd_track.assert_called_once_with("navidrome_tracks/1")


@pytest.mark.unit
def test_legacy_navidrome_surface_upsert_nd_track_delegates_to_navidrome() -> None:
    db, _, _, _, navidrome = _make_app_db()
    payload = {"media_file_id": "123"}
    navidrome.upsert_nd_track.return_value = sentinel.result

    result = db.legacy_navidrome.upsert_nd_track(payload)

    assert result is sentinel.result
    navidrome.upsert_nd_track.assert_called_once_with(payload)


@pytest.mark.unit
def test_legacy_navidrome_surface_delete_tracks_for_file_delegates_to_navidrome() -> None:
    db, _, _, _, navidrome = _make_app_db()
    navidrome.delete_nd_tracks_for_file.return_value = sentinel.result

    result = db.legacy_navidrome.delete_nd_tracks_for_file("library_files/1")

    assert result is sentinel.result
    navidrome.delete_nd_tracks_for_file.assert_called_once_with("library_files/1")


@pytest.mark.unit
def test_app_db_does_not_expose_top_level_navidrome_methods() -> None:
    db, _, _, _, _ = _make_app_db()

    assert hasattr(db, "legacy_navidrome")
    assert not hasattr(db, "get_nd_track")
    assert not hasattr(db, "upsert_nd_track")
    assert not hasattr(db, "delete_nd_tracks_for_file")


@pytest.mark.unit
def test_truncate_file_state_edges_delegates_to_app() -> None:
    db, _, app = _make_app_maintenance_db()
    app.truncate_file_state_edges.return_value = sentinel.result

    result = db.truncate_file_state_edges()

    assert result is sentinel.result
    app.truncate_file_state_edges.assert_called_once_with()


@pytest.mark.unit
def test_truncate_scan_records_delegates_to_app() -> None:
    db, _, app = _make_app_maintenance_db()
    app.truncate_scan_records.return_value = sentinel.result

    result = db.truncate_scan_records()

    assert result is sentinel.result
    app.truncate_scan_records.assert_called_once_with()


@pytest.mark.unit
def test_truncate_library_scan_edges_delegates_to_app() -> None:
    db, _, app = _make_app_maintenance_db()
    app.truncate_library_scan_edges.return_value = sentinel.result

    result = db.truncate_library_scan_edges()

    assert result is sentinel.result
    app.truncate_library_scan_edges.assert_called_once_with()


@pytest.mark.unit
def test_truncate_pipeline_states_delegates_to_app() -> None:
    db, _, app = _make_app_maintenance_db()
    app.truncate_pipeline_states.return_value = sentinel.result

    result = db.truncate_pipeline_states()

    assert result is sentinel.result
    app.truncate_pipeline_states.assert_called_once_with()


@pytest.mark.unit
def test_truncate_pipeline_state_edges_delegates_to_app() -> None:
    db, _, app = _make_app_maintenance_db()
    app.truncate_pipeline_state_edges.return_value = sentinel.result

    result = db.truncate_pipeline_state_edges()

    assert result is sentinel.result
    app.truncate_pipeline_state_edges.assert_called_once_with()


@pytest.mark.unit
def test_truncate_worker_claims_delegates_to_app() -> None:
    db, _, app = _make_app_maintenance_db()
    app.delete_all_worker_claims.return_value = sentinel.result

    result = db.truncate_worker_claims()

    assert result is sentinel.result
    app.delete_all_worker_claims.assert_called_once_with()


@pytest.mark.unit
def test_delete_all_worker_claims_delegates_to_app() -> None:
    db, _, app = _make_app_maintenance_db()
    app.delete_all_worker_claims.return_value = sentinel.result

    result = db.delete_all_worker_claims()

    assert result is sentinel.result
    app.delete_all_worker_claims.assert_called_once_with()


@pytest.mark.unit
def test_truncate_health_delegates_to_app() -> None:
    db, _, app = _make_app_maintenance_db()
    app.truncate_health.return_value = sentinel.result

    result = db.truncate_health()

    assert result is sentinel.result
    app.truncate_health.assert_called_once_with()


@pytest.mark.unit
def test_list_collections_delegates_to_app() -> None:
    db, raw_db, _ = _make_app_maintenance_db()
    raw_db.collections.return_value = [{"name": "foo"}, {"name": "bar"}]

    result = db.list_collections()

    assert result == ["foo", "bar"]
    raw_db.collections.assert_called_once_with()


@pytest.mark.unit
def test_exposes_app_maintenance_surface() -> None:
    db, _, _, _, _ = _make_app_db()

    assert isinstance(db.maintenance, AppMaintenanceDb)
    assert hasattr(db.maintenance, "truncate_worker_claims")
    assert not hasattr(db, "truncate_worker_claims")
    assert not hasattr(db, "delete_all_worker_claims")
    assert not hasattr(db, "get_state_edges_for_files")
    assert not hasattr(db, "delete_scan_records_for_library")
    assert not hasattr(db, "count_pipeline_states")
    assert not hasattr(db, "acquire_lock")
    assert not hasattr(db, "claim_file")
    assert not hasattr(db, "steal_claim")
    assert not hasattr(db, "list_libraries_in_pipeline_state")
    assert not hasattr(db, "count_calibration_states")


@pytest.mark.unit
def test_add_file_states_delegates_each_file_to_file_states() -> None:
    db, file_states, _, _, _ = _make_app_db()
    file_ids = ["library_files/1", "library_files/2"]

    result = db.add_file_states(file_ids, "queued")

    assert result is None
    assert file_states.add_file_state_edge.call_args_list == [
        call("library_files/1", "queued"),
        call("library_files/2", "queued"),
    ]


@pytest.mark.unit
def test_replace_file_states_routes_via_remove_then_add() -> None:
    db, _, _, _, _ = _make_app_db()
    file_ids = ["library_files/1", "library_files/2"]

    with (
        patch.object(db, "remove_file_states", return_value=None) as remove_states,
        patch.object(db, "add_file_states", return_value=None) as add_states,
    ):
        result = db.replace_file_states(file_ids, "processing")

    assert result is None
    remove_states.assert_called_once_with(file_ids)
    add_states.assert_called_once_with(file_ids, "processing")


@pytest.mark.unit
def test_remove_file_states_skips_empty_batches() -> None:
    db, file_states, _, _, _ = _make_app_db()

    result = db.remove_file_states([])

    assert result is None
    file_states.delete_file_state_edges.assert_not_called()


@pytest.mark.unit
def test_get_scan_delegates_to_scan() -> None:
    db, _, scan, _, _ = _make_app_db()
    scan.get_scan_record.return_value = sentinel.result

    result = db.get_scan("libraries/1")

    assert result is sentinel.result
    scan.get_scan_record.assert_called_once_with("libraries/1")


@pytest.mark.unit
def test_add_scan_creates_record_and_links_library() -> None:
    db, _, scan, app, _ = _make_app_db()
    payload = {"status": "running"}
    scan.add_scan_record.return_value = "library_scans/1"

    result = db.add_scan("libraries/1", payload)

    assert result is None
    scan.add_scan_record.assert_called_once_with({"status": "running", "library_id": "libraries/1"})
    app.upsert_library_scan_edge.assert_called_once_with("libraries/1", "library_scans/1")


@pytest.mark.unit
def test_update_scan_updates_existing_scan_and_relinks_library() -> None:
    db, _, scan, app, _ = _make_app_db()
    scan.get_scan_record.return_value = {"_id": "library_scans/1"}

    result = db.update_scan("libraries/1", {"status": "done"})

    assert result is None
    scan.update_scan_record.assert_called_once_with("library_scans/1", {"status": "done"})
    app.upsert_library_scan_edge.assert_called_once_with("libraries/1", "library_scans/1")


@pytest.mark.unit
def test_update_scan_adds_when_no_existing_scan_is_found() -> None:
    db, _, scan, _, _ = _make_app_db()
    scan.get_scan_record.return_value = None

    with patch.object(db, "add_scan", return_value=None) as add_scan:
        result = db.update_scan("libraries/1", {"status": "queued"})

    assert result is None
    add_scan.assert_called_once_with("libraries/1", {"status": "queued"})


@pytest.mark.unit
def test_remove_scan_deletes_record_and_edge() -> None:
    db, _, scan, app, _ = _make_app_db()
    scan.get_scan_record.return_value = {"_id": "library_scans/1"}

    result = db.remove_scan("libraries/1")

    assert result is None
    scan._delete_scan_record.assert_called_once_with("library_scans/1")
    app.delete_library_scan_edge.assert_called_once_with("libraries/1")


@pytest.mark.unit
def test_get_pipeline_state_returns_state_value_from_doc() -> None:
    db, _, _, app, _ = _make_app_db()
    app.get_pipeline_state_doc.return_value = {"state": "running"}

    result = db.get_pipeline_state("libraries/1")

    assert result == "running"
    app.get_pipeline_state_doc.assert_called_once_with("libraries/1")


@pytest.mark.unit
def test_add_lock_delegates_to_insert_lock() -> None:
    db, _, _, app, _ = _make_app_db()
    payload = {"resource_id": "scan:1"}
    app.insert_lock.return_value = sentinel.result

    result = db.add_lock(payload)

    assert result is sentinel.result
    app.insert_lock.assert_called_once_with(payload)


@pytest.mark.unit
def test_remove_lock_delegates_to_release_lock() -> None:
    db, _, _, app, _ = _make_app_db()
    app.release_lock.return_value = sentinel.result

    result = db.remove_lock("scan:1")

    assert result is sentinel.result
    app.release_lock.assert_called_once_with("scan:1")


@pytest.mark.unit
def test_add_claim_delegates_to_insert_worker_claim() -> None:
    db, _, _, app, _ = _make_app_db()
    payload = {"file_id": "library_files/1"}
    app.insert_worker_claim.return_value = "worker_claims/claim_1"

    result = db.add_claim(payload)

    assert result == "worker_claims/claim_1"
    app.insert_worker_claim.assert_called_once_with(payload)


@pytest.mark.unit
def test_remove_claims_combines_worker_and_file_removals() -> None:
    db, _, _, app, _ = _make_app_db()
    app.delete_claims_for_workers.return_value = 2
    app.delete_claims_for_files.return_value = 3

    result = db.remove_claims(worker_ids=["worker-1"], file_ids=["library_files/1"])

    assert result == 5
    app.delete_claims_for_workers.assert_called_once_with(["worker-1"])
    app.delete_claims_for_files.assert_called_once_with(["library_files/1"])


@pytest.mark.unit
def test_get_config_option_delegates_to_meta() -> None:
    db, _, _, app, _ = _make_app_db()
    app.get_meta.return_value = sentinel.result

    result = db.get_config_option("config_scan_interval")

    assert result is sentinel.result
    app.get_meta.assert_called_once_with("config_scan_interval")


@pytest.mark.unit
def test_list_config_options_loads_documents_for_matching_keys() -> None:
    db, _, _, app, _ = _make_app_db()
    app.list_meta_keys_by_prefix.return_value = ["config_a", "config_b"]
    app.get_meta.side_effect = [{"key": "config_a", "value": 1}, {"key": "config_b", "value": 2}]

    result = db.list_config_options("config_")

    assert result == [{"key": "config_a", "value": 1}, {"key": "config_b", "value": 2}]
    app.list_meta_keys_by_prefix.assert_called_once_with("config_")
    assert app.get_meta.call_args_list == [call("config_a"), call("config_b")]


@pytest.mark.unit
def test_update_config_option_delegates_to_upsert_meta() -> None:
    db, _, _, app, _ = _make_app_db()
    payload = {"key": "config_a", "value": 1}
    app.upsert_meta.return_value = sentinel.result

    result = db.update_config_option("config_a", payload)

    assert result is sentinel.result
    app.upsert_meta.assert_called_once_with("config_a", payload)


@pytest.mark.unit
def test_remove_config_option_delegates_to_delete_meta() -> None:
    db, _, _, app, _ = _make_app_db()
    app.delete_meta.return_value = sentinel.result

    result = db.remove_config_option("config_a")

    assert result is sentinel.result
    app.delete_meta.assert_called_once_with("config_a")


@pytest.mark.unit
def test_add_vram_promise_delegates_to_upsert_vram_promise() -> None:
    db, _, _, app, _ = _make_app_db()
    payload = {"worker_id": "worker-1", "promised_mb": 512}
    app.upsert_vram_promise.return_value = sentinel.result

    result = db.add_vram_promise(payload)

    assert result is sentinel.result
    app.upsert_vram_promise.assert_called_once_with(payload)


@pytest.mark.unit
def test_list_vram_promises_delegates_to_get_vram_promises() -> None:
    db, _, _, app, _ = _make_app_db()
    app.get_vram_promises.return_value = sentinel.result

    result = db.list_vram_promises()

    assert result is sentinel.result
    app.get_vram_promises.assert_called_once_with()


@pytest.mark.unit
def test_remove_vram_promise_delegates_to_delete_vram_promise() -> None:
    db, _, _, app, _ = _make_app_db()
    app.delete_vram_promise.return_value = sentinel.result

    result = db.remove_vram_promise("vram_promises/1")

    assert result is sentinel.result
    app.delete_vram_promise.assert_called_once_with("vram_promises/1")


@pytest.mark.unit
def test_remove_pipeline_state_delegates_to_delete_doc_and_edges() -> None:
    db, _, _, app, _ = _make_app_db()

    result = db.remove_pipeline_state("libraries/1")

    assert result is None
    app.delete_pipeline_state.assert_called_once_with("libraries/1")
    app.delete_pipeline_state_edges_for_library.assert_called_once_with("libraries/1")


@pytest.mark.unit
def test_exposes_legacy_navidrome_surface() -> None:
    db, _, _, _, _ = _make_app_db()

    assert hasattr(db, "legacy_navidrome")
    assert hasattr(db.legacy_navidrome, "get_nd_track")
