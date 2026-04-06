"""Pipeline-focused tests for ``nomarr.components.library.library_admin_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.components.library.library_admin_comp import create_library
from nomarr.persistence.database.library_pipeline_states_aql import PIPELINE_IDLE


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
