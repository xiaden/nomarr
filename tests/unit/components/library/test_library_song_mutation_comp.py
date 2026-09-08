"""Tests for nomarr.components.library.library_song_mutation_comp."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.components.library.library_song_mutation_comp import (
    bulk_delete_songs,
    delete_library_song,
    get_song_library_key,
    set_chromaprint,
    update_last_tagged_at,
    update_song_modified_time,
    update_song_path,
    upsert_library_song,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import (
    LibraryIdentity,
    SongIdentity,
    SongPathUpdate,
    SongScanUpdate,
    SongUpsertInput,
)


class TestDeleteLibraryFile:
    """Tests for single-file deletion cleanup."""

    @pytest.mark.unit
    def test_deletes_song_by_natural_path_and_library_identity(self) -> None:
        mock_db = MagicMock()
        library = Library(name="music", root_path="C:/music")

        delete_library_song(mock_db, "C:/music/song.mp3", library)

        mock_db.library.remove_song_by_path.assert_called_once_with("C:/music/song.mp3", library)
        mock_db.library.remove_song.assert_not_called()

    @pytest.mark.unit
    def test_numeric_looking_path_is_treated_as_path_not_id(self) -> None:
        mock_db = MagicMock()
        library = Library(name="music", root_path="C:/music")

        delete_library_song(mock_db, "12345", library)

        mock_db.library.remove_song_by_path.assert_called_once_with("12345", library)
        mock_db.library.remove_song.assert_not_called()


class TestBulkDeleteFiles:
    """Tests for bulk deletion cleanup."""

    @pytest.mark.unit
    def test_bulk_delete_resolves_paths_and_removes_each_found_file_once(self) -> None:
        mock_db = MagicMock()
        library = Library(name="music", root_path="C:/music")
        mock_db.library.get_song_by_path.side_effect = [object(), None, object()]

        result = bulk_delete_songs(
            mock_db,
            ["C:/music/a.mp3", "C:/music/missing.mp3", "C:/music/c.mp3"],
            library,
        )

        assert result == 2
        assert mock_db.library.get_song_by_path.call_args_list == [
            call("C:/music/a.mp3", library),
            call("C:/music/missing.mp3", library),
            call("C:/music/c.mp3", library),
        ]
        assert mock_db.library.remove_song_by_path.call_args_list == [
            call("C:/music/a.mp3", library),
            call("C:/music/c.mp3", library),
        ]

    @pytest.mark.unit
    def test_bulk_delete_returns_zero_when_no_paths_match(self) -> None:
        mock_db = MagicMock()
        library = Library(name="music", root_path="C:/music")
        mock_db.library.get_song_by_path.return_value = None

        result = bulk_delete_songs(mock_db, ["C:/music/missing.mp3"], library)

        assert result == 0
        mock_db.library.remove_song_by_path.assert_not_called()


class TestUpsertLibraryFile:
    """Tests for single-file insert/update writes."""

    @staticmethod
    def _make_path(relative: str = "relative/song.mp3", absolute: str = "C:/music/song.mp3") -> MagicMock:
        mock_path = MagicMock()
        mock_path.is_valid.return_value = True
        mock_path.relative = relative
        mock_path.absolute = absolute
        return mock_path

    @pytest.mark.unit
    def test_sends_typed_command_and_returns_semantic_identity(self) -> None:
        """The mock facade receives a typed ``SongUpsertInput`` (never a raw
        SQL-column dict) and the semantic ``SongIdentity`` is passed through."""
        mock_db = MagicMock()
        library = Library(name="music", root_path="C:/music")
        identity = SongIdentity(
            library=LibraryIdentity(name="music", root_path="C:/music"),
            normalized_path="relative/song.mp3",
        )
        mock_db.library.add_song_to_library.return_value = identity
        mock_path = self._make_path()

        result = upsert_library_song(
            mock_db,
            mock_path,
            library,
            file_size=1234,
            modified_time=5678,
        )

        assert result == identity
        assert not isinstance(result, int)
        mock_db.library.add_song_to_library.assert_called_once()
        command = mock_db.library.add_song_to_library.call_args.args[0]
        # No raw dict / column names cross the component→facade boundary.
        assert isinstance(command, SongUpsertInput)
        assert isinstance(command.library, LibraryIdentity)
        assert command.library.name == "music"
        assert command.library.root_path == "C:/music"
        assert command.path == "C:/music/song.mp3"
        assert command.last_tagged_at is None
        assert isinstance(command.scan, SongScanUpdate)
        assert command.scan.normalized_path == "relative/song.mp3"
        assert command.scan.file_size == 1234
        assert command.scan.modified_time == 5678
        assert command.scan.duration_seconds is None
        # Component does not generate a storage scan timestamp; persistence
        # applies its own default.
        assert command.scan.scanned_at is None

    @pytest.mark.unit
    def test_preserves_optional_duration_and_last_tagged_at_into_command(self) -> None:
        """Optional duration and tag timestamp are forwarded unchanged."""
        mock_db = MagicMock()
        library = Library(name="music", root_path="C:/music")
        identity = SongIdentity(
            library=LibraryIdentity(name="music", root_path="C:/music"),
            normalized_path="relative/song.mp3",
        )
        mock_db.library.add_song_to_library.return_value = identity
        mock_path = self._make_path()

        upsert_library_song(
            mock_db,
            mock_path,
            library,
            file_size=1234,
            modified_time=5678,
            duration_seconds=223.5,
            last_tagged_at=987654,
        )

        command = mock_db.library.add_song_to_library.call_args.args[0]
        assert isinstance(command, SongUpsertInput)
        assert command.last_tagged_at == 987654
        assert isinstance(command.scan, SongScanUpdate)
        assert command.scan.duration_seconds == 223.5

    @pytest.mark.unit
    def test_raises_value_error_for_invalid_path(self) -> None:
        """An invalid path short-circuits before the facade is called."""
        mock_db = MagicMock()
        library = Library(name="music", root_path="C:/music")
        mock_path = MagicMock()
        mock_path.is_valid.return_value = False
        mock_path.status = "invalid"
        mock_path.reason = "bad path"

        with pytest.raises(ValueError, match=r"Cannot upsert invalid path \(invalid\): bad path"):
            upsert_library_song(
                mock_db,
                mock_path,
                library,
                file_size=1234,
                modified_time=5678,
            )

        mock_db.library.add_song_to_library.assert_not_called()


class TestUpdateFilePath:
    """Tests for the atomic move-path adapter over the single move intent.

    ``update_song_path(db, command)`` is a component-level adapter: it forwards
    one complete ``SongPathUpdate`` (stable ``song_id`` + destination ``new_path``
    + full scan snapshot) via exactly one ``db.library.move_library_song`` call.
    It no longer composes the retired two-call path + scan-metadata choreography,
    resolves locators, opens transactions, or generates a storage timestamp.
    """

    @staticmethod
    def _command(
        *,
        song_id: int = 123,
        new_path: str = "C:/music/new-song.mp3",
        normalized_path: str = "relative/new-song.mp3",
        file_size: int = 4321,
        modified_time: int = 8765,
        duration_seconds: float | None = 123.4,
        is_valid: bool = True,
        scanned_at: int | None = None,
    ) -> SongPathUpdate:
        return SongPathUpdate(
            song_id=song_id,
            new_path=new_path,
            scan=SongScanUpdate(
                normalized_path=normalized_path,
                file_size=file_size,
                modified_time=modified_time,
                duration_seconds=duration_seconds,
                is_valid=is_valid,
                scanned_at=scanned_at,
            ),
        )

    @pytest.mark.unit
    def test_forwards_one_complete_move_command_via_single_intent(self) -> None:
        """One complete typed command is forwarded via exactly one move intent."""
        mock_db = MagicMock()
        command = self._command()

        update_song_path(mock_db, command)

        # Exactly one move-intent facade call carrying the typed command.
        mock_db.library.move_library_song.assert_called_once_with(command)
        forwarded = mock_db.library.move_library_song.call_args.args[0]
        assert isinstance(forwarded, SongPathUpdate)
        # The retired two-call path + scan-metadata surface is never invoked.
        mock_db.library.update_library_song_path.assert_not_called()
        mock_db.library.update_library_song_scan_metadata.assert_not_called()
        # The command carries the stable Song identity, destination and scan.
        assert forwarded.song_id == 123
        assert forwarded.new_path == "C:/music/new-song.mp3"
        assert forwarded.scan.normalized_path == "relative/new-song.mp3"

    @pytest.mark.unit
    def test_forwards_full_scan_data_unchanged(self) -> None:
        """Optional duration and an explicit scan timestamp pass through untouched."""
        mock_db = MagicMock()
        command = self._command(
            file_size=111,
            modified_time=222,
            duration_seconds=99.5,
            scanned_at=5555,
        )

        update_song_path(mock_db, command)

        forwarded = mock_db.library.move_library_song.call_args.args[0]
        assert forwarded is command
        assert forwarded.scan.file_size == 111
        assert forwarded.scan.modified_time == 222
        assert forwarded.scan.duration_seconds == 99.5
        assert forwarded.scan.scanned_at == 5555

    @pytest.mark.unit
    def test_optional_duration_and_validity_are_preserved(self) -> None:
        """Absent optional duration and a False validity are forwarded as-is."""
        mock_db = MagicMock()
        command = self._command(duration_seconds=None, is_valid=False)

        update_song_path(mock_db, command)

        forwarded = mock_db.library.move_library_song.call_args.args[0]
        assert forwarded.scan.duration_seconds is None
        assert forwarded.scan.is_valid is False

    @pytest.mark.unit
    def test_omitted_normalized_path_is_forwarded_for_persistence_decision(self) -> None:
        """A defensive out-of-root destination (normalized_path=None) is not
        silently resolved or dropped by the component; persistence owns the
        NOT NULL rejection decision."""
        mock_db = MagicMock()
        command = self._command(normalized_path=None)

        update_song_path(mock_db, command)

        forwarded = mock_db.library.move_library_song.call_args.args[0]
        assert forwarded.scan.normalized_path is None

    @pytest.mark.unit
    def test_leaves_scan_timestamp_to_persistence_default(self) -> None:
        """The adapter never synthesizes a storage scan timestamp: when the
        command's scan omits ``scanned_at`` it stays ``None`` and persistence
        owns filling the current time (matching upsert semantics)."""
        mock_db = MagicMock()
        command = self._command(scanned_at=None)

        update_song_path(mock_db, command)

        forwarded = mock_db.library.move_library_song.call_args.args[0]
        assert isinstance(forwarded, SongPathUpdate)
        assert forwarded.scan.scanned_at is None


class TestUpdateFileModifiedTime:
    """Tests for modified-time updates after file writes."""

    @pytest.mark.unit
    def test_updates_modified_time_on_normalized_file_id(self) -> None:
        mock_db = MagicMock()

        update_song_modified_time(mock_db, "abc123", 7777)

        mock_db.library.update_library_song_modified_time.assert_called_once_with(
            "abc123",
            7777,
        )


class TestGetFileLibraryKey:
    """Tests for resolving a file's owning library key."""

    @pytest.mark.unit
    def test_returns_library_key_when_file_exists(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_library_ids_for_songs.return_value = {123: 456}

        result = get_song_library_key(mock_db, 123)

        assert result == 456
        mock_db.library.get_library_ids_for_songs.assert_called_once_with([123])

    @pytest.mark.unit
    def test_returns_none_when_file_is_missing(self) -> None:
        mock_db = MagicMock()
        mock_db.library.get_library_ids_for_songs.return_value = {}

        result = get_song_library_key(mock_db, 123)

        assert result is None
        mock_db.library.get_library_ids_for_songs.assert_called_once_with([123])


class TestSetChromaprint:
    """Tests for chromaprint persistence."""

    @pytest.mark.unit
    def test_updates_chromaprint_on_normalized_file_id(self) -> None:
        mock_db = MagicMock()

        set_chromaprint(mock_db, "abc123", "chromaprint-value")

        mock_db.library.set_library_song_chromaprint.assert_called_once_with(
            "abc123",
            "chromaprint-value",
        )


class TestUpdateLastTaggedAt:
    """Tests for tag-timestamp updates."""

    @pytest.mark.unit
    def test_updates_last_tagged_at_with_current_timestamp(self) -> None:
        mock_db = MagicMock()

        with patch("nomarr.components.library.library_song_mutation_comp.now_ms") as mock_now_ms:
            mock_now_ms.return_value.value = 9999
            update_last_tagged_at(mock_db, f"{'songs'}/123")

        mock_db.library.update_library_song_last_tagged_at.assert_called_once_with(
            f"{'songs'}/123",
            9999,
        )
