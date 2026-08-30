"""Tests for ``nomarr.components.library.update_library_metadata_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.update_library_metadata_comp import (
    UpdateLibraryMetadataComp,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.exceptions import DuplicateEntityError


class TestUpdateLibraryMetadataComp:
    """Tests for ``UpdateLibraryMetadataComp``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_update_duplicate_name_is_value_error(self) -> None:
        """Database name collisions are exposed as a client-facing validation error."""
        mock_db = MagicMock()
        component = UpdateLibraryMetadataComp(mock_db)
        library = Library(name="Current", root_path="/music/current")

        with (
            patch(
                "nomarr.components.library.update_library_metadata_comp.update_library_record",
                side_effect=DuplicateEntityError("duplicate"),
            ),
            pytest.raises(ValueError, match="Library name already exists: Existing"),
        ):
            component.update(library, name="Existing")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_update_forwards_library_auto_write_true(self) -> None:
        """Forward explicit ``library_auto_write=True`` to persistence."""
        mock_db = MagicMock()
        component = UpdateLibraryMetadataComp(mock_db)

        with patch("nomarr.components.library.update_library_metadata_comp.update_library_record") as update_record:
            component.update(1, library_auto_write=True)

        update_record.assert_called_once_with(
            mock_db,
            1,
            name=None,
            is_enabled=None,
            watch_mode=None,
            file_write_mode=None,
            library_auto_write=True,
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_update_forwards_library_auto_write_none_when_omitted(self) -> None:
        """Forward ``library_auto_write=None`` when the caller omits it."""
        mock_db = MagicMock()
        component = UpdateLibraryMetadataComp(mock_db)

        with patch("nomarr.components.library.update_library_metadata_comp.update_library_record") as update_record:
            component.update(1)

        update_record.assert_called_once_with(
            mock_db,
            1,
            name=None,
            is_enabled=None,
            watch_mode=None,
            file_write_mode=None,
            library_auto_write=None,
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_update_forwards_file_write_mode(self) -> None:
        """Forward explicit ``file_write_mode`` to persistence."""
        mock_db = MagicMock()
        component = UpdateLibraryMetadataComp(mock_db)

        with patch("nomarr.components.library.update_library_metadata_comp.update_library_record") as update_record:
            component.update(1, file_write_mode="minimal")

        update_record.assert_called_once_with(
            mock_db,
            1,
            name=None,
            is_enabled=None,
            watch_mode=None,
            file_write_mode="minimal",
            library_auto_write=None,
        )
