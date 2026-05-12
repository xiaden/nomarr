"""Tests for library-file mutation helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.library_file_mutation_comp import (
    bulk_delete_files,
    delete_library_file,
    get_file_library_key,
    set_chromaprint,
    update_file_modified_time,
    update_file_path,
    update_metadata_cache,
    update_metadata_cache_batch,
    upsert_batch,
    upsert_library_file,
)


class TestUpdateMetadataCache:
    """Tests for update_metadata_cache()."""

    @pytest.mark.unit
    def test_updates_library_file_by_id_with_metadata_fields(self) -> None:
        """Updates one library-file document through the flat collection update verb."""
        mock_db = MagicMock()

        update_metadata_cache(
            mock_db,
            "library_files/123",
            artist="Artist",
            artists=["Artist"],
            album="Album",
            labels=None,
            genres=["Rock"],
            year=2020,
        )

        mock_db.library.update_file.assert_called_once_with(
            "library_files/123",
            {
                "artist": "Artist",
                "artists": ["Artist"],
                "album": "Album",
                "labels": None,
                "genres": ["Rock"],
                "year": 2020,
            },
        )


class TestUpdateMetadataCacheBatch:
    """Tests for update_metadata_cache_batch()."""

    @pytest.mark.unit
    def test_skips_updates_when_updates_empty(self) -> None:
        """Skips collection updates entirely when there are no batch updates."""
        mock_db = MagicMock()

        update_metadata_cache_batch(mock_db, [])

        mock_db.library.update_file.assert_not_called()

    @pytest.mark.unit
    def test_updates_each_song_by_id_from_updates_list(self) -> None:
        """Updates each batch entry through the flat collection update verb."""
        mock_db = MagicMock()
        updates = [
            {
                "song_id": "library_files/1",
                "artist": "Artist 1",
                "artists": ["Artist 1"],
                "album": "Album 1",
                "labels": ["Label 1"],
                "genres": ["Rock"],
                "year": 2020,
            },
            {
                "song_id": "library_files/2",
                "artist": "Artist 2",
                "artists": ["Artist 2"],
                "album": "Album 2",
                "labels": ["Label 2"],
                "genres": ["Jazz"],
                "year": 2021,
            },
        ]

        update_metadata_cache_batch(mock_db, updates)

        assert mock_db.library.update_file.call_count == 2
        mock_db.library.update_file.assert_any_call(
            "library_files/1",
            {
                "artist": "Artist 1",
                "artists": ["Artist 1"],
                "album": "Album 1",
                "labels": ["Label 1"],
                "genres": ["Rock"],
                "year": 2020,
            },
        )
        mock_db.library.update_file.assert_any_call(
            "library_files/2",
            {
                "artist": "Artist 2",
                "artists": ["Artist 2"],
                "album": "Album 2",
                "labels": ["Label 2"],
                "genres": ["Jazz"],
                "year": 2021,
            },
        )


class TestUpdateFileModifiedTime:
    """Tests for update_file_modified_time()."""

    @pytest.mark.unit
    def test_updates_library_file_by_key_with_modified_time(self) -> None:
        """Updates the stored modified time through the flat collection update verb."""
        mock_db = MagicMock()

        update_file_modified_time(mock_db, "abc123", 123456789)

        mock_db.library.update_file.assert_called_once_with(
            "library_files/abc123",
            {"modified_time": 123456789},
        )


class TestUpdateFilePath:
    """Tests for update_file_path()."""

    @pytest.mark.unit
    def test_updates_standard_fields_with_scanned_timestamp(self) -> None:
        """Updates the standard path fields and uses ``now_ms`` for ``scanned_at``."""
        mock_db = MagicMock()

        with patch("nomarr.components.library.library_file_mutation_comp.now_ms") as mock_now_ms:
            mock_now_ms.return_value = MagicMock()
            mock_now_ms.return_value.value = 987654321

            update_file_path(
                mock_db,
                "library_files/123",
                "D:/Music/new-song.flac",
                4096,
                123456789,
                artist="Artist",
                album="Album",
                title="Title",
                duration_seconds=245.5,
            )

        mock_db.library.update_file.assert_called_once_with(
            "library_files/123",
            {
                "path": "D:/Music/new-song.flac",
                "file_size": 4096,
                "modified_time": 123456789,
                "is_valid": 1,
                "artist": "Artist",
                "album": "Album",
                "title": "Title",
                "duration_seconds": 245.5,
                "scanned_at": 987654321,
            },
        )

    @pytest.mark.unit
    def test_includes_normalized_path_when_provided(self) -> None:
        """Adds ``normalized_path`` to the update payload when present."""
        mock_db = MagicMock()

        with patch("nomarr.components.library.library_file_mutation_comp.now_ms") as mock_now_ms:
            mock_now_ms.return_value = MagicMock()
            mock_now_ms.return_value.value = 123456789

            update_file_path(
                mock_db,
                "library_files/123",
                "D:/Music/new-song.flac",
                4096,
                123456789,
                normalized_path="d:/music/new-song.flac",
            )

        update_dict = mock_db.library.update_file.call_args.args[1]
        assert update_dict["normalized_path"] == "d:/music/new-song.flac"

    @pytest.mark.unit
    def test_omits_normalized_path_when_none(self) -> None:
        """Leaves ``normalized_path`` out of the update payload when not provided."""
        mock_db = MagicMock()

        with patch("nomarr.components.library.library_file_mutation_comp.now_ms") as mock_now_ms:
            mock_now_ms.return_value = MagicMock()
            mock_now_ms.return_value.value = 123456789

            update_file_path(
                mock_db,
                "library_files/123",
                "D:/Music/new-song.flac",
                4096,
                123456789,
            )

        update_dict = mock_db.library.update_file.call_args.args[1]
        assert "normalized_path" not in update_dict


class TestUpsertBatch:
    """Tests for upsert_batch()."""

    @pytest.mark.unit
    def test_returns_empty_list_without_upsert_when_docs_empty(self) -> None:
        """Returns early and skips collection upsert when there are no file docs."""
        mock_db = MagicMock()

        result = upsert_batch(mock_db, [])

        assert result == []
        mock_db.library.upsert_files_batch.assert_not_called()

    @pytest.mark.unit
    def test_strips_library_id_before_path_upsert(self) -> None:
        """Removes ``library_id`` from docs before calling the collection upsert verb."""
        mock_db = MagicMock()
        mock_db.library.get_file_by_path.return_value = {"_id": "library_files/1"}
        file_docs = [
            {
                "library_id": "libraries/1",
                "path": "D:/Music/song.flac",
                "file_size": 4096,
                "modified_time": 123456789,
            }
        ]

        with (
            patch(
                "nomarr.components.library.library_file_mutation_comp.get_existing_file_paths",
                return_value=set(),
            ),
            patch(
                "nomarr.components.library.library_file_mutation_comp.initialize_file_states_batch"
            ) as mock_initialize_file_states_batch,
        ):
            result = upsert_batch(mock_db, file_docs)

        assert result == ["library_files/1"]
        mock_db.library.upsert_files_batch.assert_called_once_with(
            [
                {
                    "path": "D:/Music/song.flac",
                    "file_size": 4096,
                    "modified_time": 123456789,
                }
            ]
        )
        mock_db.library.get_file_by_path.assert_called_once_with("D:/Music/song.flac", "libraries/1")
        mock_db.library.upsert_library_file_links_batch.assert_called_once_with(
            [{"_from": "libraries/1", "_to": "library_files/1"}]
        )
        mock_initialize_file_states_batch.assert_called_once_with(mock_db, ["library_files/1"])

    @pytest.mark.unit
    def test_skips_state_initialization_for_existing_files(self) -> None:
        """Skips ``initialize_file_states_batch`` for files that already exist in the DB.

        Re-initialising an existing file would silently re-insert the negative-side
        edges for every axis (e.g. not_tagged), reverting transitions that have already
        occurred and pushing those files backwards through the ML pipeline.
        """
        mock_db = MagicMock()
        mock_db.library.get_file_by_path.return_value = {"_id": "library_files/1"}
        file_docs = [
            {
                "library_id": "libraries/1",
                "path": "D:/Music/song.flac",
                "file_size": 4096,
                "modified_time": 123456789,
            }
        ]

        with (
            patch(
                "nomarr.components.library.library_file_mutation_comp.get_existing_file_paths",
                return_value={"D:/Music/song.flac"},
            ),
            patch(
                "nomarr.components.library.library_file_mutation_comp.initialize_file_states_batch"
            ) as mock_initialize_file_states_batch,
        ):
            result = upsert_batch(mock_db, file_docs)

        assert result == ["library_files/1"]
        mock_initialize_file_states_batch.assert_called_once_with(mock_db, [])

    @pytest.mark.unit
    def test_initializes_state_only_for_new_files_in_mixed_batch(self) -> None:
        """Only new files get state initialisation when a batch contains both new and existing files."""
        mock_db = MagicMock()
        mock_db.library.get_file_by_path.side_effect = [
            {"_id": "library_files/1"},
            {"_id": "library_files/2"},
        ]
        file_docs = [
            {
                "library_id": "libraries/1",
                "path": "D:/Music/existing.flac",
                "file_size": 4096,
                "modified_time": 111,
            },
            {
                "library_id": "libraries/1",
                "path": "D:/Music/new.flac",
                "file_size": 8192,
                "modified_time": 222,
            },
        ]

        with (
            patch(
                "nomarr.components.library.library_file_mutation_comp.get_existing_file_paths",
                return_value={"D:/Music/existing.flac"},
            ),
            patch(
                "nomarr.components.library.library_file_mutation_comp.initialize_file_states_batch"
            ) as mock_initialize_file_states_batch,
        ):
            result = upsert_batch(mock_db, file_docs)

        assert result == ["library_files/1", "library_files/2"]
        mock_db.library.upsert_files_batch.assert_called_once_with(
            [
                {
                    "path": "D:/Music/existing.flac",
                    "file_size": 4096,
                    "modified_time": 111,
                },
                {
                    "path": "D:/Music/new.flac",
                    "file_size": 8192,
                    "modified_time": 222,
                },
            ]
        )
        mock_db.library.upsert_library_file_links_batch.assert_called_once_with(
            [
                {"_from": "libraries/1", "_to": "library_files/1"},
                {"_from": "libraries/1", "_to": "library_files/2"},
            ]
        )
        mock_initialize_file_states_batch.assert_called_once_with(mock_db, ["library_files/2"])


class TestBulkDeleteFiles:
    """Tests for bulk_delete_files()."""

    @pytest.mark.unit
    def test_returns_zero_without_db_calls_when_paths_empty(self) -> None:
        """Returns immediately when there are no paths to delete."""
        mock_db = MagicMock()
        result = bulk_delete_files(mock_db, [])

        assert result == 0
        mock_db.library.get_file_by_path_unscoped.assert_not_called()
        mock_db.app.delete_file_state_edges.assert_not_called()
        mock_db.library.delete_file.assert_not_called()

    @pytest.mark.unit
    def test_returns_zero_without_delete_when_no_matching_docs(self) -> None:
        """Skips deletion when the per-path lookup returns no library-file documents."""
        mock_db = MagicMock()
        mock_db.library.get_file_by_path_unscoped.return_value = None

        with patch(
            "nomarr.components.library.library_file_mutation_comp._delete_library_files"
        ) as mock_delete_library_files:
            result = bulk_delete_files(mock_db, ["D:/Music/missing.flac"])

        assert result == 0
        mock_db.library.get_file_by_path_unscoped.assert_called_once_with("D:/Music/missing.flac")
        mock_delete_library_files.assert_not_called()

    @pytest.mark.unit
    def test_deletes_matching_files_and_returns_count(self) -> None:
        """Deletes all matched library-file ids and returns the number deleted."""
        mock_db = MagicMock()
        mock_db.library.get_file_by_path_unscoped.side_effect = [
            {"_id": "library_files/1"},
            {"_id": "library_files/2"},
        ]

        with patch(
            "nomarr.components.library.library_file_mutation_comp._delete_library_files"
        ) as mock_delete_library_files:
            result = bulk_delete_files(
                mock_db,
                ["D:/Music/song-1.flac", "D:/Music/song-2.flac"],
            )

        assert result == 2
        mock_delete_library_files.assert_called_once_with(mock_db, ["library_files/1", "library_files/2"])


class TestSetChromaprint:
    """Tests for set_chromaprint()."""

    @pytest.mark.unit
    def test_extracts_key_from_full_id_before_update(self) -> None:
        """Uses the trailing document key when the file id includes a collection prefix."""
        mock_db = MagicMock()

        set_chromaprint(mock_db, "library_files/abc", "fp123")

        mock_db.library.update_file.assert_called_once_with(
            "library_files/abc",
            {"chromaprint": "fp123"},
        )

    @pytest.mark.unit
    def test_uses_bare_key_directly_before_update(self) -> None:
        """Uses the provided file id directly when it is already a bare key."""
        mock_db = MagicMock()

        set_chromaprint(mock_db, "abc", "fp123")

        mock_db.library.update_file.assert_called_once_with(
            "library_files/abc",
            {"chromaprint": "fp123"},
        )


class TestUpsertLibraryFile:
    """Tests for upsert_library_file()."""

    @pytest.mark.unit
    def test_upserts_file_and_initializes_edges_with_full_args(self) -> None:
        """Inserts a new file doc, upserts ownership, and transitions tagged state."""
        mock_db = MagicMock()
        path = MagicMock()
        path.is_valid.return_value = True
        path.relative = "artist/song.flac"
        path.absolute = "D:/Music/artist/song.flac"
        mock_db.library.get_file_by_path.return_value = None
        mock_db.library.add_file.return_value = "library_files/1"

        with (
            patch("nomarr.components.library.library_file_mutation_comp.now_ms") as mock_now_ms,
            patch(
                "nomarr.components.library.library_file_mutation_comp.initialize_file_states"
            ) as mock_initialize_file_states,
            patch(
                "nomarr.components.library.library_file_mutation_comp.transition_file_state"
            ) as mock_transition_file_state,
        ):
            mock_now_ms.return_value = MagicMock(value=111222333)

            result = upsert_library_file(
                mock_db,
                path,
                "libraries/1",
                4096,
                123456789,
                duration_seconds=245.5,
                artist="Artist",
                album="Album",
                title="Title",
                last_tagged_at=987654321,
            )

        assert result == "library_files/1"
        mock_db.library.get_file_by_path.assert_called_once_with("D:/Music/artist/song.flac", "libraries/1")
        mock_db.library.add_file.assert_called_once_with(
            {
                "path": "D:/Music/artist/song.flac",
                "library_key": "1",
                "normalized_path": "artist/song.flac",
                "file_size": 4096,
                "modified_time": 123456789,
                "duration_seconds": 245.5,
                "artist": "Artist",
                "album": "Album",
                "title": "Title",
                "scanned_at": 111222333,
                "chromaprint": None,
            }
        )
        mock_db.library.link_file_to_library.assert_called_once_with("libraries/1", "library_files/1")
        mock_initialize_file_states.assert_called_once_with(mock_db, "library_files/1")
        mock_transition_file_state.assert_called_once_with(
            mock_db,
            ["library_files/1"],
            "file_states/not_tagged",
            "file_states/tagged",
        )

    @pytest.mark.unit
    def test_updates_existing_file_without_overwriting_chromaprint(self) -> None:
        """Updates an existing file doc and skips tagged transition when not requested."""
        mock_db = MagicMock()
        path = MagicMock()
        path.is_valid.return_value = True
        path.relative = "artist/song.flac"
        path.absolute = "D:/Music/artist/song.flac"
        mock_db.library.get_file_by_path.return_value = {
            "_id": "library_files/2",
            "chromaprint": "keep-me",
        }

        with (
            patch("nomarr.components.library.library_file_mutation_comp.now_ms") as mock_now_ms,
            patch(
                "nomarr.components.library.library_file_mutation_comp.initialize_file_states"
            ) as mock_initialize_file_states,
            patch(
                "nomarr.components.library.library_file_mutation_comp.transition_file_state"
            ) as mock_transition_file_state,
        ):
            mock_now_ms.return_value = MagicMock(value=222333444)

            result = upsert_library_file(
                mock_db,
                path,
                "libraries/2",
                8192,
                987654321,
            )

        assert result == "library_files/2"
        mock_db.library.add_file.assert_not_called()
        mock_db.library.update_file.assert_called_once_with(
            "library_files/2",
            {
                "library_key": "2",
                "normalized_path": "artist/song.flac",
                "file_size": 8192,
                "modified_time": 987654321,
                "duration_seconds": None,
                "artist": None,
                "album": None,
                "title": None,
                "scanned_at": 222333444,
            },
        )
        mock_db.library.link_file_to_library.assert_called_once_with("libraries/2", "library_files/2")
        mock_initialize_file_states.assert_not_called()
        mock_transition_file_state.assert_not_called()


class TestDeleteLibraryFile:
    """Tests for delete_library_file()."""

    @pytest.mark.unit
    def test_deletes_file_and_directly_derived_edges_by_id(self) -> None:
        """Deletes the file document through the library-files cascade API."""
        mock_db = MagicMock()

        with patch(
            "nomarr.components.library.library_file_mutation_comp._delete_library_files"
        ) as mock_delete_library_files:
            delete_library_file(mock_db, "library_files/123")

        mock_delete_library_files.assert_called_once_with(mock_db, ["library_files/123"])

    @pytest.mark.unit
    def test_looks_up_by_path_and_cascades_when_raw_path_given(self) -> None:
        """Resolves raw path to _id via get(), then calls cascade with the resolved ID."""
        mock_db = MagicMock()
        mock_db.library.list_libraries.return_value = [{"_id": "libraries/main"}]
        mock_db.library.get_file_by_path.return_value = {"_id": "library_files/456"}

        with patch(
            "nomarr.components.library.library_file_mutation_comp._delete_library_files"
        ) as mock_delete_library_files:
            delete_library_file(mock_db, "/music/track.flac")

        mock_db.library.list_libraries.assert_called_once_with()
        mock_db.library.get_file_by_path.assert_called_once_with("/music/track.flac", "libraries/main")
        mock_delete_library_files.assert_called_once_with(mock_db, ["library_files/456"])

    @pytest.mark.unit
    def test_returns_early_when_raw_path_not_found(self) -> None:
        """When get() returns None for an unknown path, cascade is never called."""
        mock_db = MagicMock()
        mock_db.library.list_libraries.return_value = [{"_id": "libraries/main"}]
        mock_db.library.get_file_by_path.return_value = None

        with patch(
            "nomarr.components.library.library_file_mutation_comp._delete_library_files"
        ) as mock_delete_library_files:
            delete_library_file(mock_db, "/music/missing.flac")

        mock_db.library.list_libraries.assert_called_once_with()
        mock_db.library.get_file_by_path.assert_called_once_with("/music/missing.flac", "libraries/main")
        mock_delete_library_files.assert_not_called()


class TestGetFileLibraryKey:
    """Tests for get_file_library_key()."""

    @pytest.mark.unit
    def test_returns_library_key_when_edge_exists(self) -> None:
        """Extracts the trailing key from the owning library id."""
        mock_db = MagicMock()
        mock_db.library.get_library_ids_for_files.return_value = {"library_files/123": "libraries/main"}

        result = get_file_library_key(mock_db, "library_files/123")

        assert result == "main"
        mock_db.library.get_library_ids_for_files.assert_called_once_with(["library_files/123"])

    @pytest.mark.unit
    def test_returns_none_when_no_owning_library_found(self) -> None:
        """Missing ownership rows should yield ``None``."""
        mock_db = MagicMock()
        mock_db.library.get_library_ids_for_files.return_value = {}

        result = get_file_library_key(mock_db, "library_files/missing")

        assert result is None
