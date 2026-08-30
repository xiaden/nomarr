"""Spec-first contract tests for the library domain boundary.

Covers the P1-S4 domain values: the frozen natural-key ``Library`` dataclass
(the ``(name, root_path)`` identity, absence of storage attributes), the typed
``LibraryUpdate`` command, ``LibraryPipelineState`` defaults/axis validation,
and the no-ID ``LibraryFolder`` / ``LibraryScan`` value objects. These tests
are spec-first: they must pass now that the domain values exist and later
phases (P2+) must keep them green while migrating callers.
"""

from __future__ import annotations

import pytest

from nomarr.helpers.constants.pipeline_states import (
    CAL_AXIS,
    ML_AXIS,
    PIPELINE_AXIS_FIELDS,
    PIPELINE_DEFAULTS,
    SCAN_AXIS,
    WRITE_AXIS,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.library_domain_dataclasses import (
    LibraryFolder,
    LibraryPipelineState,
    LibraryScan,
    LibraryUpdate,
)

STORAGE_ATTRS = ("id", "path", "library_type", "auto_tag", "auto_curate", "_id", "_key", "_rev")


# ── Library natural-key contract ────────────────────────────────────────────


@pytest.mark.unit
def test_library_natural_identity_is_name_root_path() -> None:
    lib = Library(name="Main", root_path="/music")
    assert lib.name == "Main"
    assert lib.root_path == "/music"


@pytest.mark.unit
def test_library_has_no_storage_attributes() -> None:
    lib = Library(name="Main", root_path="/music")
    for attr in STORAGE_ATTRS:
        assert not hasattr(lib, attr), f"Library must not expose storage attribute {attr!r}"


@pytest.mark.unit
def test_library_is_frozen_and_slotted() -> None:
    lib = Library(name="Main", root_path="/music")
    with pytest.raises(AttributeError):
        lib.name = "Other"  # type: ignore[misc]
    assert not hasattr(lib, "__dict__")


@pytest.mark.unit
def test_library_timestamps_optional_only_pre_persistence() -> None:
    lib = Library(name="Main", root_path="/music")
    assert lib.created_at is None
    assert lib.updated_at is None
    persisted = Library(name="Main", root_path="/music", created_at=1000, updated_at=1001)
    assert persisted.created_at == 1000
    assert persisted.updated_at == 1001


# ── LibraryUpdate typed command ─────────────────────────────────────────────


@pytest.mark.unit
def test_library_update_defaults_all_optional() -> None:
    update = LibraryUpdate()
    assert update.watch_mode is None
    assert update.file_write_mode is None
    assert update.library_auto_write is None
    assert update.updated_at is None


@pytest.mark.unit
def test_library_update_rejects_invalid_watch_mode() -> None:
    with pytest.raises(ValueError):
        LibraryUpdate(watch_mode="bogus")  # type: ignore[arg-type]


@pytest.mark.unit
def test_library_update_rejects_invalid_file_write_mode() -> None:
    with pytest.raises(ValueError):
        LibraryUpdate(file_write_mode="bogus")  # type: ignore[arg-type]


@pytest.mark.unit
def test_library_update_accepts_valid_watch_and_write_modes() -> None:
    for mode in ("off", "event", "poll"):
        assert LibraryUpdate(watch_mode=mode).watch_mode == mode  # type: ignore[arg-type]
    for mode in ("none", "minimal", "full"):
        assert LibraryUpdate(file_write_mode=mode).file_write_mode == mode  # type: ignore[arg-type]


@pytest.mark.unit
def test_library_update_has_no_storage_attributes() -> None:
    update = LibraryUpdate(name="Renamed")
    for attr in STORAGE_ATTRS:
        assert not hasattr(update, attr), f"LibraryUpdate must not expose storage attribute {attr!r}"


# ── LibraryPipelineState ────────────────────────────────────────────────────


@pytest.mark.unit
def test_library_pipeline_state_defaults_match_pipeline_defaults() -> None:
    state = LibraryPipelineState.defaults()
    mapping = state.to_state_mapping()
    for axis in PIPELINE_AXIS_FIELDS:
        assert mapping[axis] == PIPELINE_DEFAULTS[axis]


@pytest.mark.unit
def test_library_pipeline_state_axis_keys_match_pipeline_axis_fields() -> None:
    assert set(LibraryPipelineState.defaults().to_state_mapping().keys()) == set(PIPELINE_AXIS_FIELDS)


@pytest.mark.unit
def test_library_pipeline_state_rejects_invalid_axis_value() -> None:
    with pytest.raises(ValueError):
        LibraryPipelineState(scan_state="not-a-scan-state")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        LibraryPipelineState(ml_state="not-a-ml-state")  # type: ignore[arg-type]


@pytest.mark.unit
def test_library_pipeline_state_accepts_each_axis_pole() -> None:
    state = LibraryPipelineState(
        scan_state=SCAN_AXIS[1],
        ml_state=ML_AXIS[1],
        calibration_state=CAL_AXIS[1],
        tag_write_state=WRITE_AXIS[1],
    )
    assert state.scan_state == SCAN_AXIS[1]
    assert state.ml_state == ML_AXIS[1]


# ── LibraryFolder ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_library_folder_has_no_folder_id() -> None:
    folder = LibraryFolder(path="Album")
    assert not hasattr(folder, "id")
    assert not hasattr(folder, "parent_id")
    assert folder.path == "Album"


@pytest.mark.unit
def test_library_folder_uses_parent_path_not_parent_id() -> None:
    folder = LibraryFolder(path="A/B", parent_path="A", mtime=5, file_count=3)
    assert folder.parent_path == "A"
    assert not hasattr(folder, "parent_id")


@pytest.mark.unit
def test_library_folder_rejects_blank_path() -> None:
    with pytest.raises(ValueError):
        LibraryFolder(path="  ")


@pytest.mark.unit
def test_library_folder_is_frozen_and_slotted() -> None:
    folder = LibraryFolder(path="Album")
    with pytest.raises(AttributeError):
        folder.path = "Other"  # type: ignore[misc]
    assert not hasattr(folder, "__dict__")


# ── LibraryScan ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_library_scan_has_no_scan_row_id() -> None:
    scan = LibraryScan(scan_type="quick", status="in_progress", started_at=1000)
    assert not hasattr(scan, "id")
    assert scan.scan_type == "quick"
    assert scan.started_at == 1000


@pytest.mark.unit
def test_library_scan_rejects_blank_scan_type() -> None:
    with pytest.raises(ValueError):
        LibraryScan(scan_type="")


@pytest.mark.unit
def test_library_scan_is_frozen_and_slotted() -> None:
    scan = LibraryScan(scan_type="quick")
    with pytest.raises(AttributeError):
        scan.scan_type = "full"  # type: ignore[misc]
    assert not hasattr(scan, "__dict__")
