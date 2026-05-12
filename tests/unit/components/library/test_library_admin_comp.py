"""Tests for ``nomarr.components.library.library_admin_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

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
        """Missing libraries should short-circuit without any deletion."""
        mock_db = MagicMock()

        with patch(
            "nomarr.components.library.library_admin_comp.get_library_record",
            return_value=None,
        ) as get_library_record_mock:
            result = delete_library(mock_db, "libraries/missing")

        assert result is False
        get_library_record_mock.assert_called_once_with(mock_db, "libraries/missing")
        mock_db.library.delete_library.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_deletes_library_and_returns_true(self) -> None:
        """Existing libraries should delete all associated data and return True."""
        mock_db = MagicMock()
        library = {"name": "Main Library"}
        mock_db.library.list_library_files.return_value = [
            {"_id": "library_files/1"},
            {"_id": "library_files/2"},
        ]
        mock_db.ml.list_registered_vector_collection_names.side_effect = [
            ["vectors__1", "vectors__shared"],
            ["vectors__1", "vectors__shared"],
        ]

        with (
            patch(
                "nomarr.components.library.library_admin_comp.get_library_record",
                return_value=library,
            ) as get_library_record_mock,
            patch("nomarr.components.library.library_admin_comp.cleanup_orphaned_tags") as cleanup_mock,
            patch(
                "nomarr.components.ml.inference.ml_output_stream_store_comp.delete_output_streams"
            ) as delete_streams_mock,
        ):
            result = delete_library(mock_db, "libraries/1")

        assert result is True
        get_library_record_mock.assert_called_once_with(mock_db, "libraries/1")
        mock_db.library.list_library_files.assert_called_once_with("libraries/1")
        delete_streams_mock.assert_has_calls(
            [
                call(mock_db, "library_files/1"),
                call(mock_db, "library_files/2"),
            ]
        )
        mock_db.ml.delete_vectors_for_file.assert_has_calls(
            [
                call("vectors__1", "library_files/1"),
                call("vectors__shared", "library_files/1"),
                call("vectors__1", "library_files/2"),
                call("vectors__shared", "library_files/2"),
            ]
        )
        mock_db.library.delete_song_tag_edges_for_file.assert_has_calls(
            [call("library_files/1"), call("library_files/2")]
        )
        mock_db.app.release_claim.assert_has_calls([call("library_files/1"), call("library_files/2")])
        mock_db.app.delete_file_state_edges.assert_called_once_with(["library_files/1", "library_files/2"])
        cleanup_mock.assert_called_once_with(mock_db)
        mock_db.ml.truncate_vector_collection.assert_called_once_with("vectors__1")
        mock_db.library.delete_all_file_links_for_library.assert_called_once_with("libraries/1")
        mock_db.library.delete_all_folder_links_for_library.assert_called_once_with("libraries/1")
        mock_db.app.delete_library_scan_edge.assert_called_once_with("libraries/1")
        mock_db.app.delete_pipeline_state_edges_for_library.assert_called_once_with("libraries/1")
        mock_db.library.delete_files_for_library.assert_called_once_with("1")
        mock_db.library.delete_folders_for_library.assert_called_once_with("1")
        mock_db.app.delete_scan_records_for_library.assert_called_once_with("1")
        mock_db.app.delete_pipeline_state.assert_called_once_with("libraries/1")
        mock_db.library.delete_library.assert_called_once_with("libraries/1")
