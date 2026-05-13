# mypy: disable-error-code=func-returns-value
"""Unit tests for ``AppDb`` delegation."""

from __future__ import annotations

from unittest.mock import MagicMock, sentinel

import pytest

from nomarr.persistence.api.application import AppDb


def _make_app_db() -> tuple[AppDb, MagicMock, MagicMock, MagicMock, MagicMock]:
    file_states = MagicMock()
    scan = MagicMock()
    app = MagicMock()
    navidrome = MagicMock()
    raw_db = MagicMock()
    db = AppDb(db=raw_db, file_states=file_states, scan=scan, app=app, navidrome=navidrome)
    return db, file_states, scan, app, navidrome


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
def test_transition_file_states_delegates_to_file_states() -> None:
    db, file_states, _, _, _ = _make_app_db()
    file_ids = ["library_files/1", "library_files/2"]
    file_states.transition_file_states.return_value = sentinel.result

    result = db.transition_file_states(file_ids, "queued", "processing")

    assert result is sentinel.result
    file_states.transition_file_states.assert_called_once_with(file_ids, "queued", "processing")


@pytest.mark.unit
def test_add_file_state_edge_delegates_to_file_states() -> None:
    db, file_states, _, _, _ = _make_app_db()
    file_states.add_file_state_edge.return_value = sentinel.result

    result = db.add_file_state_edge("library_files/1", "queued")

    assert result is sentinel.result
    file_states.add_file_state_edge.assert_called_once_with("library_files/1", "queued")


@pytest.mark.unit
def test_delete_file_state_edges_delegates_to_file_states() -> None:
    db, file_states, _, _, _ = _make_app_db()
    file_ids = ["library_files/1", "library_files/2"]
    file_states.delete_file_state_edges.return_value = sentinel.result

    result = db.delete_file_state_edges(file_ids)

    assert result is sentinel.result
    file_states.delete_file_state_edges.assert_called_once_with(file_ids)


@pytest.mark.unit
def test_count_files_in_state_delegates_to_file_states() -> None:
    db, file_states, _, _, _ = _make_app_db()
    file_states.count_files_in_state.return_value = sentinel.result

    result = db.count_files_in_state("queued")

    assert result is sentinel.result
    file_states.count_files_in_state.assert_called_once_with("queued")


@pytest.mark.unit
def test_get_scan_record_delegates_to_scan() -> None:
    db, _, scan, _, _ = _make_app_db()
    scan.get_scan_record.return_value = sentinel.result

    result = db.get_scan_record("libraries/1")

    assert result is sentinel.result
    scan.get_scan_record.assert_called_once_with("libraries/1")


@pytest.mark.unit
def test_add_scan_record_delegates_to_scan() -> None:
    db, _, scan, _, _ = _make_app_db()
    payload = {"library_id": "libraries/1"}
    scan.add_scan_record.return_value = sentinel.result

    result = db.add_scan_record(payload)

    assert result is sentinel.result
    scan.add_scan_record.assert_called_once_with(payload)


@pytest.mark.unit
def test_update_scan_record_delegates_to_scan() -> None:
    db, _, scan, _, _ = _make_app_db()
    fields = {"status": "done"}
    scan.update_scan_record.return_value = sentinel.result

    result = db.update_scan_record("library_scans/1", fields)

    assert result is sentinel.result
    scan.update_scan_record.assert_called_once_with("library_scans/1", fields)


@pytest.mark.unit
def test_delete_scan_record_delegates_to_scan() -> None:
    db, _, scan, _, _ = _make_app_db()
    scan.delete_scan_record.return_value = sentinel.result

    result = db.delete_scan_record("library_scans/1")

    assert result is sentinel.result
    scan.delete_scan_record.assert_called_once_with("library_scans/1")


@pytest.mark.unit
def test_insert_lock_delegates_to_app() -> None:
    db, _, _, app, _ = _make_app_db()
    payload = {"resource_id": "scan:1"}
    app.insert_lock.return_value = sentinel.result

    result = db.insert_lock(payload)

    assert result is sentinel.result
    app.insert_lock.assert_called_once_with(payload)


@pytest.mark.unit
def test_upsert_lock_delegates_to_app() -> None:
    db, _, _, app, _ = _make_app_db()
    payload = {"owner": "worker-1"}
    app.upsert_lock.return_value = sentinel.result

    result = db.upsert_lock("scan:1", payload)

    assert result is sentinel.result
    app.upsert_lock.assert_called_once_with("scan:1", payload)


@pytest.mark.unit
def test_release_lock_delegates_to_app() -> None:
    db, _, _, app, _ = _make_app_db()
    app.release_lock.return_value = sentinel.result

    result = db.release_lock("scan:1")

    assert result is sentinel.result
    app.release_lock.assert_called_once_with("scan:1")


@pytest.mark.unit
def test_get_lock_delegates_to_app() -> None:
    db, _, _, app, _ = _make_app_db()
    app.get_lock.return_value = sentinel.result

    result = db.get_lock("scan:1")

    assert result is sentinel.result
    app.get_lock.assert_called_once_with("scan:1")


@pytest.mark.unit
def test_insert_worker_claim_delegates_to_app() -> None:
    db, _, _, app, _ = _make_app_db()
    payload = {"file_id": "library_files/1"}
    app.insert_worker_claim.return_value = sentinel.result

    result = db.insert_worker_claim(payload)

    assert result is sentinel.result
    app.insert_worker_claim.assert_called_once_with(payload)


@pytest.mark.unit
def test_release_claim_delegates_to_app() -> None:
    db, _, _, app, _ = _make_app_db()
    app.release_claim.return_value = sentinel.result

    result = db.release_claim("library_files/1")

    assert result is sentinel.result
    app.release_claim.assert_called_once_with("library_files/1")


@pytest.mark.unit
def test_aggregate_worker_claims_delegates_to_app() -> None:
    db, _, _, app, _ = _make_app_db()
    app.aggregate_worker_claims.return_value = sentinel.result

    result = db.aggregate_worker_claims()

    assert result is sentinel.result
    app.aggregate_worker_claims.assert_called_once_with()


@pytest.mark.unit
def test_count_worker_claims_delegates_to_app() -> None:
    db, _, _, app, _ = _make_app_db()
    app.count_worker_claims.return_value = sentinel.result

    result = db.count_worker_claims()

    assert result is sentinel.result
    app.count_worker_claims.assert_called_once_with()


@pytest.mark.unit
def test_delete_all_worker_claims_delegates_to_app() -> None:
    db, _, _, app, _ = _make_app_db()
    app.delete_all_worker_claims.return_value = sentinel.result

    result = db.delete_all_worker_claims()

    assert result is sentinel.result
    app.delete_all_worker_claims.assert_called_once_with()


@pytest.mark.unit
def test_get_health_delegates_to_app() -> None:
    db, _, _, app, _ = _make_app_db()
    app.get_health.return_value = sentinel.result

    result = db.get_health("ml-worker")

    assert result is sentinel.result
    app.get_health.assert_called_once_with("ml-worker")


@pytest.mark.unit
def test_count_healthy_delegates_to_app() -> None:
    db, _, _, app, _ = _make_app_db()
    app.count_healthy.return_value = sentinel.result

    result = db.count_healthy()

    assert result is sentinel.result
    app.count_healthy.assert_called_once_with()


@pytest.mark.unit
def test_get_meta_delegates_to_app() -> None:
    db, _, _, app, _ = _make_app_db()
    app.get_meta.return_value = sentinel.result

    result = db.get_meta("version")

    assert result is sentinel.result
    app.get_meta.assert_called_once_with("version")


@pytest.mark.unit
def test_upsert_meta_delegates_to_app() -> None:
    db, _, _, app, _ = _make_app_db()
    payload = {"value": "1.0.0"}
    app.upsert_meta.return_value = sentinel.result

    result = db.upsert_meta("version", payload)

    assert result is sentinel.result
    app.upsert_meta.assert_called_once_with("version", payload)


@pytest.mark.unit
def test_delete_meta_delegates_to_app() -> None:
    db, _, _, app, _ = _make_app_db()
    app.delete_meta.return_value = sentinel.result

    result = db.delete_meta("version")

    assert result is sentinel.result
    app.delete_meta.assert_called_once_with("version")


@pytest.mark.unit
def test_upsert_vram_promise_delegates_to_app() -> None:
    db, _, _, app, _ = _make_app_db()
    payload = {"device": "cuda:0"}
    app.upsert_vram_promise.return_value = sentinel.result

    result = db.upsert_vram_promise(payload)

    assert result is sentinel.result
    app.upsert_vram_promise.assert_called_once_with(payload)


@pytest.mark.unit
def test_get_vram_promises_delegates_to_app() -> None:
    db, _, _, app, _ = _make_app_db()
    app.get_vram_promises.return_value = sentinel.result

    result = db.get_vram_promises()

    assert result is sentinel.result
    app.get_vram_promises.assert_called_once_with()


@pytest.mark.unit
def test_delete_vram_promise_delegates_to_app() -> None:
    db, _, _, app, _ = _make_app_db()
    app.delete_vram_promise.return_value = sentinel.result

    result = db.delete_vram_promise("vram_promises/1")

    assert result is sentinel.result
    app.delete_vram_promise.assert_called_once_with("vram_promises/1")


@pytest.mark.unit
def test_count_vram_promises_delegates_to_app() -> None:
    db, _, _, app, _ = _make_app_db()
    app.count_vram_promises.return_value = sentinel.result

    result = db.count_vram_promises()

    assert result is sentinel.result
    app.count_vram_promises.assert_called_once_with()


@pytest.mark.unit
def test_get_nd_track_delegates_to_navidrome() -> None:
    db, _, _, _, navidrome = _make_app_db()
    navidrome.get_nd_track.return_value = sentinel.result

    result = db.get_nd_track("navidrome_tracks/1")

    assert result is sentinel.result
    navidrome.get_nd_track.assert_called_once_with("navidrome_tracks/1")


@pytest.mark.unit
def test_upsert_nd_track_delegates_to_navidrome() -> None:
    db, _, _, _, navidrome = _make_app_db()
    payload = {"media_file_id": "123"}
    navidrome.upsert_nd_track.return_value = sentinel.result

    result = db.upsert_nd_track(payload)

    assert result is sentinel.result
    navidrome.upsert_nd_track.assert_called_once_with(payload)


@pytest.mark.unit
def test_delete_nd_tracks_for_file_delegates_to_navidrome() -> None:
    db, _, _, _, navidrome = _make_app_db()
    navidrome.delete_nd_tracks_for_file.return_value = sentinel.result

    result = db.delete_nd_tracks_for_file("library_files/1")

    assert result is sentinel.result
    navidrome.delete_nd_tracks_for_file.assert_called_once_with("library_files/1")


@pytest.mark.unit
def test_list_collections_delegates_to_wrapped_database() -> None:
    db, _, _, _, _ = _make_app_db()
    db._db.collections.return_value = [{"name": "libraries"}, {"name": "library_files"}]

    result = db.list_collections()

    assert result == ["libraries", "library_files"]
    db._db.collections.assert_called_once_with()
