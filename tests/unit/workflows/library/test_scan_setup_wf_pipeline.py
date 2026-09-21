"""Persistence-owned admission tests for scan setup."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.exceptions import DuplicateEntityError, LibraryOperationConflict
from nomarr.workflows.library.scan_setup_wf import scan_setup_workflow


def _make_library() -> Library:
    return Library(name="Main Library", root_path="/music")


@pytest.mark.unit
@pytest.mark.mocked
def test_scan_setup_admits_before_creating_scan_row() -> None:
    mock_db = MagicMock()
    library = _make_library()
    with (
        patch("nomarr.workflows.library.scan_setup_wf.check_interrupted_scan", return_value=(False, None)),
        patch("nomarr.workflows.library.scan_setup_wf.mark_scan_started") as mock_start,
    ):
        assert scan_setup_workflow(mock_db, library, scan_type="quick") == library

    mock_db.library.regions.admit_scan.assert_called_once_with(library)
    mock_start.assert_called_once_with(mock_db, library, "quick")


@pytest.mark.unit
@pytest.mark.mocked
def test_scan_setup_preserves_typed_write_conflict_without_side_effects() -> None:
    mock_db = MagicMock()
    library = _make_library()
    mock_db.library.regions.admit_scan.side_effect = LibraryOperationConflict(
        "scan", scan_state="not_scanned", tag_write_state="writing"
    )
    with (
        patch("nomarr.workflows.library.scan_setup_wf.mark_scan_started") as mock_start,
        pytest.raises(LibraryOperationConflict) as exc_info,
    ):
        scan_setup_workflow(mock_db, library, scan_type="quick")
    mock_start.assert_not_called()
    assert exc_info.value.tag_write_state == "writing"


@pytest.mark.unit
@pytest.mark.mocked
def test_scan_setup_does_not_reconstruct_admission_after_unique_scan_race() -> None:
    mock_db = MagicMock()
    library = _make_library()
    with (
        patch("nomarr.workflows.library.scan_setup_wf.check_interrupted_scan", return_value=(False, None)),
        patch(
            "nomarr.workflows.library.scan_setup_wf.mark_scan_started",
            side_effect=DuplicateEntityError("active scan already exists"),
        ) as mock_start,
        pytest.raises(DuplicateEntityError),
    ):
        scan_setup_workflow(mock_db, library, scan_type="quick")
    mock_db.library.regions.admit_scan.assert_called_once_with(library)
    mock_start.assert_called_once()
