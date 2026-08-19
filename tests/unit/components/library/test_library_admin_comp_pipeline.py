"""Pipeline-focused tests for ``nomarr.components.library.library_admin_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.library_admin_comp import _is_scan_running, create_library


class TestCreateLibraryPipeline:
    """Tests for library creation pipeline side effects."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_create_library_initializes_pipeline_state_after_persisting(self) -> None:
        """Library creation should persist the supported library fields."""
        mock_db = MagicMock()
        mock_db.library.get_scan.return_value = None

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

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_create_library_passes_library_auto_write_to_persistence(self) -> None:
        """Explicit library_auto_write should be forwarded to persistence."""
        mock_db = MagicMock()
        mock_db.library.get_scan.return_value = None

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

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_create_library_does_not_create_scan_document(self) -> None:
        """Library creation leaves scan state deferred until scan setup."""
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

        mock_db.library.add_scan.assert_not_called()


class TestIsScanRunning:
    """Tests for _is_scan_running helper."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_true_when_libraries_are_scanning(self) -> None:
        """Should return True when there are scanning libraries."""
        mock_db = MagicMock()

        with patch(
            "nomarr.components.library.library_admin_comp.get_libraries_in_axis_state",
            return_value=["libraries/abc123"],
        ):
            result = _is_scan_running(mock_db)

        assert result is True

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_false_when_no_libraries_are_scanning(self) -> None:
        """Should return False when there are no scanning libraries."""
        mock_db = MagicMock()

        with patch(
            "nomarr.components.library.library_admin_comp.get_libraries_in_axis_state",
            return_value=[],
        ):
            result = _is_scan_running(mock_db)

        assert result is False
