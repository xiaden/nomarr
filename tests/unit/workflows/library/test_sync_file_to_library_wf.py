"""Regression tests for the slow path of ``sync_file_to_library``.

Covers the bounded existing caller journey after ``upsert_library_song`` moved
to the typed ``SongUpsertInput`` facade contract (TASK-song-upsert-uses-
storage-row-contract-A). The workflow must remain behaviorally equivalent:

- the slow path upserts and ignores the semantic ``SongIdentity`` result,
- it rereads the row by natural path through its existing read-side projection,
- an absent reread logs a warning and returns without crashing,
- the only integer handle reaching the tag/entity adapter is the read-side
  row-mirror id (never anything derived from the upsert result), and
- exceptions are caught and logged as before.

The read-side row mirror and integer tag APIs are explicitly NOT migrated here.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
)
from nomarr.workflows.library.sync_file_to_library_wf import sync_file_to_library

WF = "nomarr.workflows.library.sync_file_to_library_wf"


def _library() -> Library:
    return Library(name="Rock Library", root_path="/music")


def _metadata() -> dict:
    return {"duration": 223.5, "all_tags": {"artist": "x"}, "nom_tags": {}}


class TestSyncFileToLibrarySlowPath:
    """Slow path (no ``file_id``): path-based upsert then reread + tag sync."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_upserts_ignores_semantic_result_and_feeds_reread_int_to_tag_adapter(self) -> None:
        """The upsert's semantic identity is ignored; the reread row-mirror int
        is the only id forwarded to the tag/entity adapter."""
        mock_db = MagicMock()
        library = _library()
        identity = SongIdentity(
            library=LibraryIdentity(name=library.name, root_path=library.root_path),
            normalized_path="song.mp3",
        )
        stat = SimpleNamespace(st_size=1234, st_mtime=5.678)
        row = {"id": 77, "path": "/music/song.mp3", "normalized_path": "song.mp3"}

        with (
            patch(f"{WF}.os.stat", return_value=stat),
            patch(f"{WF}.build_library_path_from_input") as mock_build_path,
            patch(f"{WF}.upsert_library_song", return_value=identity) as mock_upsert,
            patch(f"{WF}.get_library_song", return_value=row) as mock_reread,
            patch(f"{WF}._sync_tags_and_entities") as mock_tags,
        ):
            mock_build_path.return_value.is_valid.return_value = True
            result = sync_file_to_library(
                mock_db,
                "/music/song.mp3",
                _metadata(),
                namespace="nom",
                tagged_version="v1",
                library=library,
            )

        assert result is None
        # Upsert happened; its semantic identity was not bound (no crash, no
        # use of the value).
        mock_upsert.assert_called_once()
        assert isinstance(mock_upsert.return_value, SongIdentity)
        # Reread by natural path, then tag/entity adapter receives only the
        # read-side row-mirror integer id.
        mock_reread.assert_called_once_with(mock_db, "/music/song.mp3", library)
        assert mock_tags.call_count == 1
        file_id_arg = mock_tags.call_args.args[1]
        assert file_id_arg == 77
        assert isinstance(file_id_arg, int)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_upsert_receives_application_metadata(self) -> None:
        """The upsert receives the natural Library + stat-derived metadata."""
        mock_db = MagicMock()
        library = _library()
        stat = SimpleNamespace(st_size=1234, st_mtime=5.678)

        with (
            patch(f"{WF}.os.stat", return_value=stat),
            patch(f"{WF}.build_library_path_from_input") as mock_build_path,
            patch(f"{WF}.upsert_library_song") as mock_upsert,
            patch(f"{WF}.get_library_song", return_value={"id": 77}),
            patch(f"{WF}._sync_tags_and_entities"),
        ):
            mock_build_path.return_value.is_valid.return_value = True
            mock_build_path.return_value.relative = "song.mp3"
            mock_build_path.return_value.absolute = "/music/song.mp3"
            sync_file_to_library(
                mock_db,
                "/music/song.mp3",
                _metadata(),
                namespace="nom",
                tagged_version=None,
                library=library,
            )

        mock_upsert.assert_called_once()
        kwargs = mock_upsert.call_args.kwargs
        assert kwargs["library"] is library
        assert kwargs["file_size"] == 1234
        assert kwargs["modified_time"] == int(5.678 * 1000)
        assert kwargs["duration_seconds"] == 223.5

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_reread_absent_logs_warning_and_returns_without_crash(self, caplog) -> None:
        """An absent reread after a successful upsert logs + returns early."""
        mock_db = MagicMock()
        library = _library()
        stat = SimpleNamespace(st_size=1234, st_mtime=5.678)

        with (
            patch(f"{WF}.os.stat", return_value=stat),
            patch(f"{WF}.build_library_path_from_input") as mock_build_path,
            patch(f"{WF}.upsert_library_song"),
            patch(f"{WF}.get_library_song", return_value=None),
            patch(f"{WF}._sync_tags_and_entities") as mock_tags,
            caplog.at_level("WARNING", logger="nomarr.workflows.library.sync_file_to_library_wf"),
        ):
            mock_build_path.return_value.is_valid.return_value = True
            result = sync_file_to_library(
                mock_db,
                "/music/song.mp3",
                _metadata(),
                namespace="nom",
                tagged_version="v1",
                library=library,
            )

        assert result is None
        mock_tags.assert_not_called()
        assert any("File record not found after upsert" in rec.message for rec in caplog.records)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_exception_after_upsert_is_caught_and_logged(self, caplog) -> None:
        """A failure surfaced through the facade is caught + logged, not raised."""
        mock_db = MagicMock()
        library = _library()
        stat = SimpleNamespace(st_size=1234, st_mtime=5.678)

        with (
            patch(f"{WF}.os.stat", return_value=stat),
            patch(f"{WF}.build_library_path_from_input") as mock_build_path,
            patch(f"{WF}.upsert_library_song") as mock_upsert,
            patch(f"{WF}.get_library_song") as mock_reread,
            patch(f"{WF}._sync_tags_and_entities") as mock_tags,
            caplog.at_level("WARNING", logger="nomarr.workflows.library.sync_file_to_library_wf"),
        ):
            mock_build_path.return_value.is_valid.return_value = True
            # A state-init exception inside the facade surfaces as RuntimeError
            # through add_song_to_library; the workflow must catch + log it.
            mock_upsert.side_effect = RuntimeError("state init failed")
            result = sync_file_to_library(
                mock_db,
                "/music/song.mp3",
                _metadata(),
                namespace="nom",
                tagged_version="v1",
                library=library,
            )

        assert result is None
        mock_reread.assert_not_called()
        mock_tags.assert_not_called()
        assert any("Failed to sync" in rec.message for rec in caplog.records)
