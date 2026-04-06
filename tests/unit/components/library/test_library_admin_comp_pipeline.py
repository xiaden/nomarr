"""Pipeline-focused tests for ``nomarr.components.library.library_admin_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.components.library.library_admin_comp import _is_scan_running, create_library
from nomarr.persistence.database.library_pipeline_states_aql import PIPELINE_IDLE, PIPELINE_SCANNING


class TestCreateLibraryPipeline:
    """Tests for library creation pipeline side effects."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_create_library_initializes_pipeline_state_after_persisting(self) -> None:
        """Library creation should insert the initial idle pipeline edge after persistence."""
        mock_db = MagicMock()
        mock_db.libraries.create_library.return_value = "libraries/abc123"

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
        ):
            library_id = create_library(
                db=mock_db,
                base_library_root="/configured-music",
                name=None,
                root_path="rock",
            )

        assert library_id == "libraries/abc123"
        assert mock_db.mock_calls.index(
            call.libraries.create_library(
                name="Rock Library",
                root_path="/music/rock",
                is_enabled=True,
                watch_mode="off",
                file_write_mode="full",
                library_auto_write=False,
            )
        ) < mock_db.mock_calls.index(call.library_pipeline_states.transition_state("libraries/abc123", PIPELINE_IDLE))

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_create_library_passes_library_auto_write_to_persistence(self) -> None:
        """Explicit library_auto_write should be forwarded to persistence."""
        mock_db = MagicMock()
        mock_db.libraries.create_library.return_value = "libraries/abc123"

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
        ):
            create_library(
                db=mock_db,
                base_library_root="/configured-music",
                name=None,
                root_path="rock",
                library_auto_write=True,
            )

        mock_db.libraries.create_library.assert_called_once_with(
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
        mock_db.libraries.create_library.return_value = "libraries/abc123"

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
        ):
            create_library(
                db=mock_db,
                base_library_root="/configured-music",
                name=None,
                root_path="rock",
            )

        assert mock_db.mock_calls.index(
            call.library_pipeline_states.transition_state("libraries/abc123", PIPELINE_IDLE)
        ) < mock_db.mock_calls.index(call.library_scans.get_or_create_scan("libraries/abc123"))
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
