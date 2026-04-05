"""Tests for ``nomarr.components.library.library_admin_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.library_admin_comp import create_library


class TestCreateLibrary:
    """Tests for ``create_library``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_passes_file_write_mode_to_db(self) -> None:
        """Explicit file_write_mode should be forwarded to persistence."""
        mock_db = MagicMock()
        mock_db.libraries.create_library.return_value = "libraries/1"

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
            result = create_library(
                db=mock_db,
                base_library_root="/configured-music",
                name=None,
                root_path="rock",
                file_write_mode="minimal",
            )

        assert result == "libraries/1"
        mock_db.libraries.create_library.assert_called_once_with(
            name="Rock Library",
            root_path="/music/rock",
            is_enabled=True,
            watch_mode="off",
            file_write_mode="minimal",
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_default_file_write_mode_is_full(self) -> None:
        """Default file_write_mode should remain ``full`` when omitted."""
        mock_db = MagicMock()
        mock_db.libraries.create_library.return_value = "libraries/1"

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
            result = create_library(
                db=mock_db,
                base_library_root="/configured-music",
                name=None,
                root_path="rock",
            )

        assert result == "libraries/1"
        mock_db.libraries.create_library.assert_called_once_with(
            name="Rock Library",
            root_path="/music/rock",
            is_enabled=True,
            watch_mode="off",
            file_write_mode="full",
        )
