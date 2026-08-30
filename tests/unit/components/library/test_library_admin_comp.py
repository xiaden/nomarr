"""Tests for ``nomarr.components.library.library_admin_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.library_admin_comp import create_library, delete_library
from nomarr.helpers.dataclasses.library_dataclass import Library


@pytest.fixture(autouse=True)
def pipeline_state_shims(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests focused on admin behavior while production code uses helper seams."""
    # No shims needed - pipeline state is now handled via PIPELINE_DEFAULTS passed to create_library_record


class TestCreateLibrary:
    """Tests for ``create_library``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_passes_file_write_mode_to_db(self) -> None:
        """Explicit file_write_mode should be forwarded to persistence."""
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
                return_value="libraries/1",
            ) as create_record,
        ):
            result = create_library(
                db=mock_db,
                base_library_root="/configured-music",
                name=None,
                root_path="rock",
                file_write_mode="minimal",
            )

        assert result == "libraries/1"
        create_record.assert_called_once_with(
            mock_db,
            name="Rock Library",
            root_path="/music/rock",
            is_enabled=True,
            watch_mode="off",
            file_write_mode="minimal",
            library_auto_write=False,
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_default_file_write_mode_is_full(self) -> None:
        """Default file_write_mode should remain ``full`` when omitted."""
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
                return_value="libraries/1",
            ) as create_record,
        ):
            result = create_library(
                db=mock_db,
                base_library_root="/configured-music",
                name=None,
                root_path="rock",
            )

        assert result == "libraries/1"
        create_record.assert_called_once_with(
            mock_db,
            name="Rock Library",
            root_path="/music/rock",
            is_enabled=True,
            watch_mode="off",
            file_write_mode="full",
            library_auto_write=False,
        )


class TestDeleteLibrary:
    """Tests for ``delete_library``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_false_when_library_not_found(self) -> None:
        """Missing libraries should short-circuit without any deletion."""
        mock_db = MagicMock()
        library = Library(name="Missing", root_path="/missing")

        with patch(
            "nomarr.components.library.library_admin_comp.get_library_record",
            return_value=None,
        ) as get_library_record_mock:
            result = delete_library(mock_db, library)

        assert result is False
        get_library_record_mock.assert_called_once_with(mock_db, library)
        mock_db.library.delete_library.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_deletes_library_and_returns_true(self) -> None:
        """Existing libraries should delegate cascade to db.library.remove_library and return True."""
        mock_db = MagicMock()
        library = Library(name="Main Library", root_path="/music")

        with patch(
            "nomarr.components.library.library_admin_comp.get_library_record",
            return_value=library,
        ) as get_library_record_mock:
            result = delete_library(mock_db, library)

        assert result is True
        get_library_record_mock.assert_called_once_with(mock_db, library)
        mock_db.library.remove_library.assert_called_once_with(library)
