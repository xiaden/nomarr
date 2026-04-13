"""Pipeline-focused tests for ``nomarr.components.library.library_admin_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.library_admin_comp import _is_scan_running, create_library
from nomarr.helpers.constants.pipeline_states import PIPELINE_IDLE, PIPELINE_SCANNING


@pytest.fixture(autouse=True)
def pipeline_state_shims(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bridge helper-based production code to the legacy test mock surface."""

    def _transition(db: MagicMock, library_id: str, state: str) -> None:
        db.library_pipeline_states.transition_state(library_id, state)

    def _get_scanning_ids(db: MagicMock) -> set[str]:
        return set(db.library_pipeline_states.get_libraries_in_state(PIPELINE_SCANNING))

    monkeypatch.setattr("nomarr.components.library.library_admin_comp.transition_pipeline_state", _transition)
    monkeypatch.setattr("nomarr.components.library.library_admin_comp.get_scanning_library_ids", _get_scanning_ids)
    monkeypatch.setattr(
        "nomarr.components.library.library_admin_comp.ensure_scan_state",
        lambda db, library_id: db.library_scans.get_or_create_scan(library_id),
    )


class TestCreateLibraryPipeline:
    """Tests for library creation pipeline side effects."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_create_library_initializes_pipeline_state_after_persisting(self) -> None:
        """Library creation should insert the initial idle pipeline edge after persistence."""
        mock_db = MagicMock()

        with (
            patch(
                "nomarr.components.library.library_admin_comp.get_base_library_root",
                return_value="/music",
            ),
            patch(
                "nomarr.components.library.library_admin_comp.normalize_library_root",
                return_value="/music/rock",
            ),
            patch("nomarr.components.library.library_admin_comp.ensure_no_overlapping_library_root"),
            patch(
                "nomarr.components.library.library_admin_comp._resolve_library_name",
                return_value="Rock Library",
            ),
            patch(
                "nomarr.components.library.library_admin_comp.create_library_record",
                return_value="libraries/abc123",
            ) as create_record,
        ):
            library_id = create_library(
                db=mock_db,
                base_library_root="/configured-music",
                name=None,
                root_path="rock",
            )

        assert library_id == "libraries/abc123"
        create_record.assert_called_once_with(
            mock_db,
            name="Rock Library",
            root_path="/music/rock",
            is_enabled=True,
            watch_mode="off",
            file_write_mode="full",
            library_auto_write=False,
        )
        mock_db.library_pipeline_states.transition_state.assert_called_once_with("libraries/abc123", PIPELINE_IDLE)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_create_library_passes_library_auto_write_to_persistence(self) -> None:
        """Explicit library_auto_write should be forwarded to persistence."""
        mock_db = MagicMock()

        with (
            patch(
                "nomarr.components.library.library_admin_comp.get_base_library_root",
                return_value="/music",
            ),
            patch(
                "nomarr.components.library.library_admin_comp.normalize_library_root",
                return_value="/music/rock",
            ),
            patch("nomarr.components.library.library_admin_comp.ensure_no_overlapping_library_root"),
            patch(
                "nomarr.components.library.library_admin_comp._resolve_library_name",
                return_value="Rock Library",
            ),
            patch(
                "nomarr.components.library.library_admin_comp.create_library_record",
                return_value="libraries/abc123",
            ) as create_record,
        ):
            create_library(
                db=mock_db,
                base_library_root="/configured-music",
                name=None,
                root_path="rock",
                library_auto_write=True,
            )

        create_record.assert_called_once_with(
            mock_db,
            name="Rock Library",
            root_path="/music/rock",
            is_enabled=True,
            watch_mode="off",
            file_write_mode="full",
            library_auto_write=True,
        )
        mock_db.library_pipeline_states.transition_state.assert_called_once_with(
            "libraries/abc123",
            PIPELINE_IDLE,
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_create_library_initializes_scan_document_after_pipeline_transition(self) -> None:
        """Library creation should seed the scan doc for the new library."""
        mock_db = MagicMock()

        with (
            patch(
                "nomarr.components.library.library_admin_comp.get_base_library_root",
                return_value="/music",
            ),
            patch(
                "nomarr.components.library.library_admin_comp.normalize_library_root",
                return_value="/music/rock",
            ),
            patch("nomarr.components.library.library_admin_comp.ensure_no_overlapping_library_root"),
            patch(
                "nomarr.components.library.library_admin_comp._resolve_library_name",
                return_value="Rock Library",
            ),
            patch(
                "nomarr.components.library.library_admin_comp.create_library_record",
                return_value="libraries/abc123",
            ),
        ):
            create_library(
                db=mock_db,
                base_library_root="/configured-music",
                name=None,
                root_path="rock",
            )

        mock_db.library_pipeline_states.transition_state.assert_called_once_with("libraries/abc123", PIPELINE_IDLE)
        mock_db.library_scans.get_or_create_scan.assert_called_once_with("libraries/abc123")


class TestIsScanRunning:
    """Tests for pipeline-backed scan detection."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_true_when_pipeline_has_scanning_library(self) -> None:
        """A non-empty scanning pipeline result should report an active scan."""
        mock_db = MagicMock()
        mock_db.library_pipeline_states.get_libraries_in_state.return_value = ["libraries/lib1"]

        assert _is_scan_running(mock_db) is True

        mock_db.library_pipeline_states.get_libraries_in_state.assert_called_once_with(PIPELINE_SCANNING)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_false_when_pipeline_has_no_scanning_libraries(self) -> None:
        """An empty scanning pipeline result should report no active scan."""
        mock_db = MagicMock()
        mock_db.library_pipeline_states.get_libraries_in_state.return_value = []

        assert _is_scan_running(mock_db) is False

        mock_db.library_pipeline_states.get_libraries_in_state.assert_called_once_with(PIPELINE_SCANNING)
