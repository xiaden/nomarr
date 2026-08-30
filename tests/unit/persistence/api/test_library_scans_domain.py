"""Persistence facade tests for the domain ``LibraryScansDb`` surface.

These use repository doubles (``MagicMock``) — no real database — and prove the
hard domain boundary (ADR-032/041/043) for scan lifecycle intents:

- a ``Library`` natural ``(name, root_path)`` key is resolved to a storage
  library id *internally* and that id never crosses the facade boundary;
- storage ``LibraryScanRow`` values are mapped to domain ``LibraryScan``
  before returning — the generated scan ``id`` and ``library_id`` FK are
  dropped;
- stale-scan writes are rejected (``update_current_scan`` returning ``False``);
- ``start_scan`` returns a ``LibraryScan`` (not a generated id); ``add_scan``
  (the old row/dict-payload escape) is gone.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.library_domain_dataclasses import LibraryScan
from nomarr.helpers.dto.repo_dto import LibraryRow, LibraryScanRow
from nomarr.persistence.api.library_scans import LibraryScansDb


def _library_row(**overrides: object) -> LibraryRow:
    base = {
        "id": 7,
        "name": "main",
        "path": "/music",
        "library_type": "music",
        "auto_tag": 0,
        "auto_curate": 0,
        "watch_mode": "off",
        "file_write_mode": "full",
        "created_at": 100,
        "updated_at": 200,
    }
    return LibraryRow(**{**base, **overrides})


def _scan_row(**overrides: object) -> LibraryScanRow:
    base = {
        "id": 41,
        "library_id": 7,
        "scan_type": "full",
        "status": "in_progress",
        "started_at": 1000,
        "heartbeat_at": 2000,
        "finished_at": None,
        "files_found": 5,
        "files_processed": 2,
        "error": None,
    }
    return LibraryScanRow(**{**base, **overrides})


def _make_scans(
    *,
    scan_repo: MagicMock | None = None,
    library_repo: MagicMock | None = None,
) -> tuple[LibraryScansDb, MagicMock, MagicMock]:
    scan_repo = scan_repo or MagicMock()
    library_repo = library_repo or MagicMock()
    scans = LibraryScansDb(
        session=MagicMock(),
        scan_repo=scan_repo,
        library_repo=library_repo,
    )
    return scans, scan_repo, library_repo


def _main_library() -> Library:
    return Library(
        name="main",
        root_path="/music",
        is_enabled=True,
        watch_mode="off",
        file_write_mode="full",
        library_auto_write=False,
        created_at=100,
        updated_at=200,
    )


# ── row → domain mapping (internal FK resolution, no id leaks) ─────────────


@pytest.mark.unit
def test_get_scan_resolves_natural_key_and_maps_domain() -> None:
    scans, scan_repo, library_repo = _make_scans()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    scan_repo.get_scan_record = MagicMock(return_value=_scan_row())

    result = scans.get_scan(_main_library())

    assert isinstance(result, LibraryScan)
    assert result.scan_type == "full"
    assert result.status == "in_progress"
    assert result.started_at == 1000
    assert result.heartbeat_at == 2000
    assert result.files_processed == 2
    assert result.files_found == 5
    assert not hasattr(result, "id")  # generated scan id never crosses
    library_repo.get_library_by_natural_key.assert_called_once_with("main", "/music")
    scan_repo.get_scan_record.assert_called_once_with(7)  # resolved id internal


@pytest.mark.unit
def test_get_scan_returns_none_when_no_record() -> None:
    scans, scan_repo, library_repo = _make_scans()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    scan_repo.get_scan_record = MagicMock(return_value=None)

    assert scans.get_scan(_main_library()) is None


@pytest.mark.unit
def test_get_latest_successful_scan_maps_domain() -> None:
    scans, scan_repo, library_repo = _make_scans()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    scan_repo.get_latest_successful_scan = MagicMock(return_value=_scan_row(status="completed", finished_at=9000))

    result = scans.get_latest_successful_scan(_main_library())

    assert isinstance(result, LibraryScan)
    assert result.status == "completed"
    assert result.finished_at == 9000
    scan_repo.get_latest_successful_scan.assert_called_once_with(7)


@pytest.mark.unit
def test_scan_raises_when_library_unknown() -> None:
    scans, _, library_repo = _make_scans()
    library_repo.get_library_by_natural_key = MagicMock(return_value=None)

    with pytest.raises(LookupError):
        scans.get_scan(_main_library())


# ── start_scan (returns domain, not generated id) ──────────────────────────


@pytest.mark.unit
def test_start_scan_creates_in_progress_record_and_returns_domain() -> None:
    scans, scan_repo, library_repo = _make_scans()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    scan_repo.create_scan = MagicMock(return_value=41)
    scan_repo.get_scan_record = MagicMock(return_value=_scan_row())

    result = scans.start_scan(_main_library(), "quick", 1500)

    payload = scan_repo.create_scan.call_args[0][0]
    assert payload["library_id"] == 7  # resolved internally
    assert payload["scan_type"] == "quick"
    assert payload["status"] == "in_progress"
    assert payload["started_at"] == 1500
    assert payload["heartbeat_at"] == 1500
    assert isinstance(result, LibraryScan)
    assert result.scan_type == "full"  # persisted row returned
    assert result.started_at == 1000
    assert not hasattr(result, "id")


# ── record_scan_progress / complete_scan (typed writes, stale rejection) ───


@pytest.mark.unit
def test_record_scan_progress_builds_fields_and_returns_updated() -> None:
    scans, scan_repo, library_repo = _make_scans()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    scan_repo.get_scan_record = MagicMock(
        return_value=_scan_row(
            files_processed=3,
            files_found=5,
            heartbeat_at=3000,
            status="scanning",
        )
    )
    scan_repo.update_current_scan = MagicMock(return_value=True)

    result = scans.record_scan_progress(
        _main_library(),
        heartbeat_at=3000,
        status="scanning",
        progress=3,
        total=5,
    )

    scan_repo.update_current_scan.assert_called_once_with(
        7,
        41,
        {"heartbeat_at": 3000, "status": "scanning", "files_processed": 3, "files_found": 5},
    )
    assert isinstance(result, LibraryScan)
    assert result.files_processed == 3
    assert result.files_found == 5
    assert not hasattr(result, "id")


@pytest.mark.unit
def test_record_scan_progress_raises_when_no_scan() -> None:
    scans, scan_repo, library_repo = _make_scans()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    scan_repo.get_scan_record = MagicMock(return_value=None)

    with pytest.raises(ValueError, match="no scan exists"):
        scans.record_scan_progress(_main_library(), heartbeat_at=3000)


@pytest.mark.unit
def test_record_scan_progress_rejects_stale_write() -> None:
    scans, scan_repo, library_repo = _make_scans()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    scan_repo.get_scan_record = MagicMock(return_value=_scan_row())
    scan_repo.update_current_scan = MagicMock(return_value=False)

    with pytest.raises(ValueError, match="no longer current"):
        scans.record_scan_progress(_main_library(), heartbeat_at=3000)


@pytest.mark.unit
def test_complete_scan_marks_completed_and_returns_domain() -> None:
    scans, scan_repo, library_repo = _make_scans()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    scan_repo.get_scan_record = MagicMock(return_value=_scan_row(status="completed", finished_at=9000))
    scan_repo.update_current_scan = MagicMock(return_value=True)

    result = scans.complete_scan(_main_library(), 9000)

    scan_repo.update_current_scan.assert_called_once_with(7, 41, {"status": "completed", "finished_at": 9000})
    assert isinstance(result, LibraryScan)
    assert result.status == "completed"
    assert result.finished_at == 9000


@pytest.mark.unit
def test_complete_scan_rejects_stale_write() -> None:
    scans, scan_repo, library_repo = _make_scans()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    scan_repo.get_scan_record = MagicMock(return_value=_scan_row())
    scan_repo.update_current_scan = MagicMock(return_value=False)

    with pytest.raises(ValueError, match="no longer current"):
        scans.complete_scan(_main_library(), 9000)


# ── remove_scan (no id, no payload leaks) ──────────────────────────────────


@pytest.mark.unit
def test_remove_scan_deletes_by_resolved_id() -> None:
    scans, scan_repo, library_repo = _make_scans()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    scan_repo.get_scan_record = MagicMock(return_value=_scan_row())

    scans.remove_scan(_main_library())

    scan_repo.delete_scan_record.assert_called_once_with(41)


@pytest.mark.unit
def test_remove_scan_is_noop_when_no_record() -> None:
    scans, scan_repo, library_repo = _make_scans()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    scan_repo.get_scan_record = MagicMock(return_value=None)

    scans.remove_scan(_main_library())

    scan_repo.delete_scan_record.assert_not_called()


@pytest.mark.unit
def test_public_scan_methods_do_not_accept_storage_identifiers() -> None:
    scans, _, _ = _make_scans()

    with pytest.raises((AttributeError, TypeError)):
        scans.get_scan(cast("Library", 7))
    with pytest.raises((AttributeError, TypeError)):
        scans.remove_scan(cast("Library", 7))


@pytest.mark.unit
def test_facade_has_no_row_or_legacy_update_operations() -> None:
    assert not hasattr(LibraryScansDb, "add_scan")
    assert not hasattr(LibraryScansDb, "update_scan")
