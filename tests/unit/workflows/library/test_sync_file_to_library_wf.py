"""Regression tests for ``sync_file_to_library``.

Covers the bounded caller journey after the workflow moved to the typed
``SongUpsertInput``/``SongIdentity`` contract. The workflow must remain
behaviorally equivalent:

- the slow path upserts and forwards the semantic ``SongIdentity`` result,
- the fast path forwards a caller-supplied ``SongIdentity`` without upserting,
- exceptions are caught and logged as before.

No generated integer id, row mirror, or resolver crosses the workflow.
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


def _identity() -> SongIdentity:
    library = _library()
    return SongIdentity(
        library=LibraryIdentity(
            library_uuid=library.library_uuid or "00000000-0000-0000-0000-000000000000",
            name=library.name,
            root_path=library.root_path,
        ),
        normalized_path="song.mp3",
    )


def _metadata() -> dict:
    return {"duration": 223.5, "all_tags": {"artist": "x"}, "nom_tags": {}}


class TestSyncFileToLibrarySlowPath:
    """Slow path (no ``song``): path-based upsert then locator-addressed sync."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_forwards_upsert_identity_to_tag_adapter(self) -> None:
        """The upsert's semantic identity is the only locator forwarded."""
        mock_db = MagicMock()
        library = _library()
        identity = _identity()
        stat = SimpleNamespace(st_size=1234, st_mtime=5.678)

        with (
            patch(f"{WF}.os.stat", return_value=stat),
            patch(f"{WF}.build_library_path_from_input") as mock_build_path,
            patch(f"{WF}.upsert_library_song", return_value=identity) as mock_upsert,
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
        mock_upsert.assert_called_once()
        assert mock_tags.call_count == 1
        assert mock_tags.call_args.args[1] is identity

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
            patch(f"{WF}.upsert_library_song", return_value=_identity()) as mock_upsert,
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


class TestSyncFileToLibraryFastPath:
    """Fast path (``song`` supplied): no path lookup, no upsert."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_forwards_supplied_locator_without_upsert(self) -> None:
        mock_db = MagicMock()
        identity = _identity()

        with (
            patch(f"{WF}.upsert_library_song") as mock_upsert,
            patch(f"{WF}._sync_tags_and_entities") as mock_tags,
        ):
            result = sync_file_to_library(
                mock_db,
                "/music/song.mp3",
                _metadata(),
                namespace="nom",
                tagged_version="v1",
                library=None,
                song=identity,
            )

        assert result is None
        mock_upsert.assert_not_called()
        assert mock_tags.call_count == 1
        assert mock_tags.call_args.args[1] is identity

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
        mock_tags.assert_not_called()
        assert any("Failed to sync" in rec.message for rec in caplog.records)
