"""Tests for ``nomarr.components.library.library_admin_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.library_admin_comp import create_library, delete_library


@pytest.fixture(autouse=True)
def pipeline_state_shims(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests focused on admin behavior while production code uses helper seams."""

    def _transition(db: MagicMock, library_id: str, state: str) -> None:
        db.library_pipeline_states.transition_state(library_id, state)

    monkeypatch.setattr("nomarr.components.library.library_admin_comp.transition_pipeline_state", _transition)


class TestCreateLibrary:
    """Tests for ``create_library``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_passes_file_write_mode_to_db(self) -> None:
        """Explicit file_write_mode should be forwarded to persistence."""
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
        mock_db.library_pipeline_states.transition_state.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_default_file_write_mode_is_full(self) -> None:
        """Default file_write_mode should remain ``full`` when omitted."""
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
        mock_db.library_pipeline_states.transition_state.assert_called_once()


class TestDeleteLibrary:
    """Tests for ``delete_library``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_false_when_library_not_found(self) -> None:
        """Missing libraries should short-circuit without cascading delete."""
        mock_db = MagicMock()

        with (
            patch(
                "nomarr.components.library.library_admin_comp.get_library_record",
                return_value=None,
            ) as get_library_record_mock,
            patch(
                "nomarr.components.library.library_admin_comp.normalize_library_id",
                return_value="libraries/normalized",
            ) as normalize_library_id_mock,
        ):
            result = delete_library(mock_db, "libraries/missing")

        assert result is False
        get_library_record_mock.assert_called_once_with(mock_db, "libraries/missing")
        normalize_library_id_mock.assert_not_called()
        mock_db.libraries.cascade.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_deletes_library_and_returns_true(self) -> None:
        """Existing libraries should cascade delete their normalized id."""
        mock_db = MagicMock()
        library = {"name": "Main Library"}

        with (
            patch(
                "nomarr.components.library.library_admin_comp.get_library_record",
                return_value=library,
            ) as get_library_record_mock,
            patch(
                "nomarr.components.library.library_admin_comp.normalize_library_id",
                return_value="libraries/normalized",
            ) as normalize_library_id_mock,
        ):
            result = delete_library(mock_db, "libraries/1")

        assert result is True
        get_library_record_mock.assert_called_once_with(mock_db, "libraries/1")
        normalize_library_id_mock.assert_called_once_with("libraries/1")
        mock_db.libraries.cascade.assert_called_once_with(["libraries/normalized"])
