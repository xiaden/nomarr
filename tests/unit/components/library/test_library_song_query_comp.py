"""Tests for ``nomarr.components.library.library_song_query_comp``.

Assertions target the sealed domain-facing tag facade
(``db.library.find_songs_with_tag`` / ``list_tags`` /
``list_song_tags_for_songs`` / ``find_songs_with_numeric_tag`` returning
domain values), never raw rows, integer tag ids, or deleted legacy accessor
names (``search_songs_by_tag`` / ``_collect_song_ids_for_tag_ids``).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.components.library.library_song_query_comp import (
    DEFAULT_LIMIT,
    clear_library_data,
    count_recently_tagged,
    count_songs_by_tag,
    detect_nd_path_prefix,
    find_move_candidate_by_chromaprint,
    get_all_library_paths,
    get_artist_album_frequencies,
    get_existing_file_paths,
    get_folder_rel_paths,
    get_library_counts,
    get_library_song,
    get_library_stats,
    get_recently_processed,
    get_sample_normalized_path,
    get_song_by_id,
    get_song_modified_times,
    get_songs_by_chromaprint,
    get_songs_by_ids_with_tags,
    get_songs_by_paths_bulk,
    get_songs_for_folder,
    get_songs_for_folders,
    get_tagged_file_paths,
    get_tracks_by_song_ids,
    get_tracks_for_matching,
    list_all_song_ids,
    list_songs,
    require_library_song_id,
    search_songs_by_tag,
    search_songs_with_tags,
)
from nomarr.helpers.constants.file_states import STATE_PROCESSED
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song, SongTagMatch
from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment, TagRef
from nomarr.helpers.dto.library_dto import FileTag


def make_db() -> MagicMock:

    db = MagicMock()

    db.library = MagicMock()

    db.app = MagicMock()

    db.ml = MagicMock()

    return db


def _song(**overrides: object) -> Song:
    base: dict = {
        "song_id": 1,
        "library_id": 1,
        "folder_id": None,
        "path": "/music/song.mp3",
        "normalized_path": "song.mp3",
        "file_size": 100,
        "modified_time": 1000,
        "duration_seconds": None,
        "chromaprint": None,
        "needs_tagging": False,
        "is_valid": True,
        "tagged": False,
        "calibration_hash": None,
        "write_claimed_by": None,
        "last_tagged_at": None,
        "scanned_at": None,
        "created_at": 1000,
    }
    base.update(overrides)
    return Song(**base)


def _lib_identity(name: str = "main", root_path: str = "/music") -> LibraryIdentity:
    return LibraryIdentity(name=name, root_path=root_path)


def _song_identity(normalized_path: str) -> SongIdentity:
    return SongIdentity(library=_lib_identity(), normalized_path=normalized_path)


@pytest.mark.unit
def test_get_file_by_id_uses_library_facade() -> None:

    db = make_db()

    db.library.get_song.return_value = _song(song_id=1)

    result = get_song_by_id(db, 1)

    assert result == _song(song_id=1).to_dict()

    db.library.get_song.assert_called_once_with(1)


@pytest.mark.unit
def test_count_recently_tagged_uses_library_counter() -> None:

    db = make_db()

    db.library.count_recently_tagged.return_value = 2

    with patch("nomarr.components.library.library_song_query_comp.now_ms") as mock_now_ms:
        mock_now_ms.return_value.value = 10_000

        result = count_recently_tagged(db, window_seconds=5)

    assert result == 2

    db.library.count_recently_tagged.assert_called_once_with(5_000)


@pytest.mark.unit
def test_get_existing_file_paths_uses_library_batch_lookup() -> None:

    db = make_db()

    paths = ["D:/Music/song.flac", "D:/Music/other.flac"]

    db.library.list_existing_song_paths.return_value = ["D:/Music/song.flac", "D:/Music/song.flac"]

    result = get_existing_file_paths(db, 1, paths)

    assert result == {"D:/Music/song.flac"}

    db.library.list_existing_song_paths.assert_called_once_with(1, paths)


@pytest.mark.unit
def test_get_files_by_ids_with_tags_hydrates_tags_and_library_ids() -> None:

    db = make_db()

    song = _song(song_id=1, path="D:/Music/song.flac", normalized_path="song.flac")

    identity = _song_identity("song.flac")

    db.library.list_songs_by_ids.return_value = [song]

    db.library.resolve_song_identities.return_value = {1: identity}

    db.library.list_song_tags_for_songs.return_value = {
        identity: (
            SongTagAssignment(name="genre", value="rock"),
            SongTagAssignment(name="nom:mood-tier-1", value="calm", namespace="nom"),
        )
    }
    db.library.get_library_ids_for_songs.return_value = {1: 1}

    result = get_songs_by_ids_with_tags(db, [1])

    assert result == [
        {
            **song.to_dict(),
            "tags": [
                FileTag(key="genre", value="rock", tag_type="string", is_nomarr=False),
                FileTag(key="nom:mood-tier-1", value="calm", tag_type="string", is_nomarr=True),
            ],
            "library_id": 1,
        }
    ]

    db.library.list_songs_by_ids.assert_called_once_with([1])

    db.library.list_song_tags_for_songs.assert_called_once_with([identity])


@pytest.mark.unit
def test_get_files_by_ids_with_tags_returns_empty_list_when_ids_empty() -> None:

    db = make_db()

    result = get_songs_by_ids_with_tags(db, [])

    assert result == []

    db.library.list_songs_by_ids.assert_not_called()


@pytest.mark.unit
def test_get_library_file_scoped_filters_songs() -> None:

    db = make_db()

    row = _song(song_id=1, path="D:/Music/song.flac", normalized_path="song.flac")

    db.library.get_song_by_normalized_path.return_value = row

    result = get_library_song(db, "song.flac", library=1)

    assert result == row.to_dict()

    db.library.get_song_by_normalized_path.assert_called_once_with("song.flac", 1)


@pytest.mark.unit
def test_get_library_file_unscoped_tries_normalized_then_unscoped_path() -> None:

    db = make_db()

    row = _song(song_id=1, path="D:/Music/song.flac", normalized_path="song.flac")

    db.library.find_song_by_path_any_library.return_value = row

    result = get_library_song(db, "D:/Music/song.flac")

    assert result == row.to_dict()

    db.library.find_song_by_path_any_library.assert_called_once_with("D:/Music/song.flac")


@pytest.mark.unit
def test_get_files_by_paths_bulk_maps_only_found_paths() -> None:

    db = make_db()

    with patch(
        "nomarr.components.library.library_song_query_comp.get_library_song",
        side_effect=[None, {"id": 2, "path": "D:/Music/found.flac"}],
    ) as get_library_file_mock:
        result = get_songs_by_paths_bulk(db, ["missing.flac", "D:/Music/found.flac"])

    assert result == {"D:/Music/found.flac": {"id": 2, "path": "D:/Music/found.flac"}}

    get_library_file_mock.assert_has_calls([call(db, "missing.flac"), call(db, "D:/Music/found.flac")])


@pytest.mark.unit
def test_get_files_by_paths_bulk_returns_empty_mapping_when_paths_empty() -> None:

    db = make_db()

    result = get_songs_by_paths_bulk(db, [])

    assert result == {}

    db.library.find_song_by_path_any_library.assert_not_called()


@pytest.mark.unit
def test_detect_nd_path_prefix_uses_longest_matching_normalized_path() -> None:

    db = make_db()

    db.library.list_libraries.return_value = [{"id": 1}]

    db.library.list_songs.return_value = [
        _song(normalized_path="song.flac"),
        _song(normalized_path="artist/song.flac"),
    ]

    result = detect_nd_path_prefix(db, "/music/artist/song.flac")

    assert result == "/music/"

    db.library.list_songs.assert_called_once_with({"id": 1}, limit=DEFAULT_LIMIT)


@pytest.mark.unit
def test_detect_nd_path_prefix_returns_none_without_match() -> None:

    db = make_db()

    db.library.list_songs.return_value = []

    assert detect_nd_path_prefix(db, "/music/missing.flac") is None


@pytest.mark.unit
def test_list_songs_unscoped_sorts_and_paginates() -> None:

    db = make_db()

    db.library.list_libraries.return_value = [{"id": 1}]

    db.library.list_songs.return_value = [
        _song(song_id=2, path="D:/Music/two.flac", normalized_path="two.flac"),
        _song(song_id=1, path="D:/Music/one.flac", normalized_path="one.flac"),
    ]

    metadata = {
        2: {"artist": "B", "album": "A", "title": "T2"},
        1: {"artist": "A", "album": "A", "title": "T1"},
    }

    with patch(
        "nomarr.components.library.library_song_query_comp.hydrate_songs_with_metadata",
        side_effect=lambda _db, docs: [{**d, **metadata.get(d.get("id"), {})} for d in docs],
    ):
        rows, total = list_songs(db, limit=1, offset=1)

    assert rows == [
        {
            **_song(song_id=2, path="D:/Music/two.flac", normalized_path="two.flac").to_dict(),
            "artist": "B",
            "album": "A",
            "title": "T2",
        }
    ]

    assert total == 2

    db.library.list_songs.assert_called_once_with({"id": 1}, limit=None)


@pytest.mark.unit
def test_list_songs_unscoped_paginates_beyond_default_collection_cap() -> None:
    db = make_db()

    db.library.list_libraries.return_value = [{"id": 1}]
    songs = [
        _song(song_id=song_id, path=f"D:/Music/s{song_id}.flac", normalized_path=f"s{song_id}.flac")
        for song_id in range(DEFAULT_LIMIT + 1)
    ]
    db.library.list_songs.return_value = songs

    with patch(
        "nomarr.components.library.library_song_query_comp.hydrate_songs_with_metadata",
        side_effect=lambda _db, docs: docs,
    ):
        rows, total = list_songs(db, limit=1, offset=DEFAULT_LIMIT)

    assert rows == [songs[-1].to_dict()]
    assert total == DEFAULT_LIMIT + 1
    db.library.list_songs.assert_called_once_with({"id": 1}, limit=None)


@pytest.mark.unit
def test_list_songs_scoped_filters_in_python() -> None:

    db = make_db()

    matching_row = _song(song_id=9, path="D:/Music/nine.flac", normalized_path="nine.flac")

    db.library.list_songs.return_value = [
        _song(song_id=8, path="D:/Music/eight.flac", normalized_path="eight.flac"),
        matching_row,
    ]

    metadata = {
        8: {"artist": "Other", "album": "Album", "title": "Song"},
        9: {"artist": "Artist", "album": "Album", "title": "Song"},
    }

    with patch(
        "nomarr.components.library.library_song_query_comp.hydrate_songs_with_metadata",
        side_effect=lambda _db, docs: [{**d, **metadata.get(d.get("id"), {})} for d in docs],
    ):
        rows, total = list_songs(db, artist="Artist", album="Album", library=1)

    assert rows == [
        {
            **matching_row.to_dict(),
            "artist": "Artist",
            "album": "Album",
            "title": "Song",
        }
    ]

    assert total == 1

    db.library.list_songs.assert_called_once_with(1, limit=None)


@pytest.mark.unit
def test_get_all_library_paths_uses_list_files() -> None:

    db = make_db()

    db.library.list_libraries.return_value = [{"id": 1}]

    db.library.list_songs.return_value = [
        _song(song_id=1, path="D:/Music/a.flac", normalized_path="a.flac"),
        _song(song_id=2, path="D:/Music/b.flac", normalized_path="b.flac"),
    ]

    result = get_all_library_paths(db)

    assert result == ["D:/Music/a.flac", "D:/Music/b.flac"]

    db.library.list_songs.assert_called_once_with({"id": 1}, limit=DEFAULT_LIMIT)


@pytest.mark.unit
def test_get_file_modified_times_builds_mapping_from_list_files() -> None:

    db = make_db()

    db.library.list_libraries.return_value = [{"id": 1}]

    db.library.list_songs.return_value = [
        _song(song_id=1, path="D:/Music/a.flac", normalized_path="a.flac", modified_time=10),
        _song(song_id=2, path="D:/Music/b.flac", normalized_path="b.flac", modified_time=20),
        _song(song_id=3, path="D:/Music/skip.flac", normalized_path="skip.flac", modified_time=None),
    ]

    result = get_song_modified_times(db)

    assert result == {"D:/Music/a.flac": 10, "D:/Music/b.flac": 20}

    db.library.list_songs.assert_called_once_with({"id": 1}, limit=None)


@pytest.mark.unit
def test_get_tagged_file_paths_reads_processed_songs_from_app_facade() -> None:

    db = make_db()

    db.app.songs_with_state.return_value = [
        _song(song_id=1, path="D:/Music/a.flac", normalized_path="a.flac"),
        _song(song_id=2, path="D:/Music/b.flac", normalized_path="b.flac"),
    ]

    result = get_tagged_file_paths(db)

    assert result == ["D:/Music/a.flac", "D:/Music/b.flac"]

    db.app.songs_with_state.assert_called_once_with(STATE_PROCESSED, limit=None)


@pytest.mark.unit
def test_get_folder_rel_paths_uses_library_folder_listing() -> None:

    db = make_db()

    db.library.list_folders_for_library.return_value = [
        SimpleNamespace(path="Artist"),
        SimpleNamespace(path="Artist/Album"),
    ]

    result = get_folder_rel_paths(db, 1)

    assert result == {"Artist", "Artist/Album"}

    db.library.list_folders_for_library.assert_called_once_with(1)


@pytest.mark.unit
def test_get_files_for_folder_marks_tagged_state_from_app_facade() -> None:

    db = make_db()

    matching_doc = _song(
        song_id=1,
        path="D:/Music/Artist/Album/song.flac",
        normalized_path="Artist/Album/song.flac",
    )

    db.library.list_songs_for_folder.return_value = [matching_doc]

    result = get_songs_for_folder(db, 1, "Artist/Album")

    assert result == {matching_doc.to_dict()["path"]: matching_doc.to_dict()}

    db.library.list_songs_for_folder.assert_called_once_with(1, "Artist/Album")


@pytest.mark.unit
def test_get_files_for_folders_matches_root_and_nested_paths() -> None:

    db = make_db()

    root_doc = _song(song_id=1, path="D:/Music/root.flac", normalized_path="root.flac")

    nested_doc = _song(song_id=2, path="D:/Music/Artist/song.flac", normalized_path="Artist/song.flac")

    db.library.list_songs.return_value = [root_doc, nested_doc]

    db.app.song_ids_with_state.return_value = [2]

    result = get_songs_for_folders(db, 1, ["", "Artist"])

    assert result == {
        root_doc.to_dict()["path"]: {**root_doc.to_dict(), "has_tagged_state": False},
        nested_doc.to_dict()["path"]: {**nested_doc.to_dict(), "has_tagged_state": True},
    }


@pytest.mark.unit
def test_get_recently_processed_sorts_by_latest_activity() -> None:

    db = make_db()

    db.app.songs_with_state.return_value = [
        _song(song_id=2, path="D:/Music/newer.flac", normalized_path="Artist/newer.flac", last_tagged_at=20),
        _song(song_id=1, path="D:/Music/older.flac", normalized_path="Artist/older.flac", scanned_at=10),
    ]

    metadata = {
        1: {"title": "Older", "artist": "Artist", "album": "Album"},
        2: {"title": "Newer", "artist": "Artist", "album": "Album"},
    }

    with patch(
        "nomarr.components.library.library_song_query_comp.hydrate_songs_with_metadata",
        side_effect=lambda _db, docs: [{**d, **metadata.get(d.get("id"), {})} for d in docs],
    ):
        result = get_recently_processed(db, limit=1)

    assert result == [
        {
            "file_id": 2,
            "path": "Artist/newer.flac",
            "title": "Newer",
            "artist": "Artist",
            "album": "Album",
            "activity_at": 20,
            "activity_event": "tagged",
        }
    ]

    db.app.songs_with_state.assert_called_once_with(
        STATE_PROCESSED,
        limit=DEFAULT_LIMIT,
        order_by_activity=True,
    )


@pytest.mark.unit
def test_get_recently_processed_scopes_to_library_ids() -> None:

    db = make_db()

    keep = _song(song_id=1, path="D:/Music/keep.flac", normalized_path="keep.flac", scanned_at=5)
    skip = _song(song_id=2, library_id=2, path="D:/Music/skip.flac", normalized_path="skip.flac", scanned_at=6)

    db.app.songs_with_state.return_value = [keep, skip]

    db.library.list_songs.return_value = [keep]

    with patch(
        "nomarr.components.library.library_song_query_comp.hydrate_songs_with_metadata",
        side_effect=lambda _db, docs: docs,
    ):
        result = get_recently_processed(db, library=1)

    assert [row["file_id"] for row in result] == [1]

    db.app.songs_with_state.assert_called_once_with(
        STATE_PROCESSED,
        limit=DEFAULT_LIMIT,
        order_by_activity=True,
    )
    db.library.list_songs.assert_called_once_with(1, limit=None)


@pytest.mark.unit
def test_get_files_by_chromaprint_scoped_filters_songs() -> None:

    db = make_db()

    matching_doc = _song(song_id=1, path="D:/Music/a.flac", chromaprint="abc")

    db.library.list_songs.return_value = [
        matching_doc,
        _song(song_id=2, path="D:/Music/b.flac", chromaprint="def"),
    ]

    result = get_songs_by_chromaprint(db, "abc", library=1)

    assert result == [matching_doc.to_dict()]

    db.library.list_songs.assert_called_once_with(1, limit=None)


@pytest.mark.unit
def test_get_files_by_chromaprint_unscoped_uses_filtered_list_files() -> None:

    db = make_db()

    db.library.list_libraries.return_value = [{"id": 1}]

    db.library.find_library_song_by_chromaprint.return_value = _song(
        song_id=1, path="D:/Music/a.flac", chromaprint="abc"
    )

    result = get_songs_by_chromaprint(db, "abc")

    assert result == [_song(song_id=1, path="D:/Music/a.flac", chromaprint="abc").to_dict()]

    db.library.find_library_song_by_chromaprint.assert_called_once_with({"id": 1}, "abc")


@pytest.mark.unit
def test_get_tracks_by_song_ids_sorts_and_applies_defaults() -> None:

    db = make_db()

    db.library.list_songs_by_ids.return_value = [
        _song(song_id=1, path="D:/Music/one.flac", normalized_path="one.flac"),
        _song(song_id=2, path="D:/Music/two.flac", normalized_path="two.flac"),
    ]

    with patch(
        "nomarr.components.library.library_song_query_comp.hydrate_songs_with_metadata",
        side_effect=lambda _db, docs: docs,
    ):
        result = get_tracks_by_song_ids(
            db,
            {1, 2},
            [("sort_rank", "desc")],
            limit=1,
        )

    assert result == [
        {"path": "D:/Music/one.flac", "title": "one", "artist": "Unknown Artist", "album": "Unknown Album"}
    ]

    db.library.list_songs_by_ids.assert_called_once()


@pytest.mark.unit
def test_get_library_stats_aggregates_global_songs() -> None:

    db = make_db()

    db.library.list_libraries.return_value = [{"id": 1}, {"id": 2}]

    db.library.list_songs.side_effect = [
        [_song(song_id=1, duration_seconds=10.5, file_size=100)],
        [_song(song_id=2, duration_seconds=9.5, file_size=200)],
    ]

    db.library.list_tags.side_effect = [
        (TagRef(name="artist", value="Artist A"), TagRef(name="artist", value="Artist B")),
        (TagRef(name="album", value="Album A"),),
    ]

    with patch("nomarr.components.library.library_song_query_comp.count_untagged_files", return_value=4):
        result = get_library_stats(db)

    assert result == {
        "total_files": 2,
        "total_artists": 2,
        "total_albums": 1,
        "total_duration": 20.0,
        "total_size": 300,
        "needs_tagging_count": 4,
    }

    assert db.library.list_songs.call_args_list == [call({"id": 1}, limit=None), call({"id": 2}, limit=None)]

    assert db.library.list_tags.call_args_list == [
        call(name="artist", limit=None),
        call(name="album", limit=None),
    ]


@pytest.mark.unit
def test_get_library_counts_groups_parent_folders_by_library() -> None:

    db = make_db()

    library = Library(name="main", root_path="/music")

    db.library.list_libraries.return_value = [library]

    db.library.list_songs.return_value = [
        _song(song_id=1, path="D:/Music/Artist A/song.flac", normalized_path="Artist A/song.flac"),
        _song(song_id=2, path="D:/Music/Artist B/other.flac", normalized_path="Artist B/other.flac"),
    ]

    result = get_library_counts(db)

    assert result == {"main": {"file_count": 2, "folder_count": 2}}

    db.library.list_songs.assert_called_once_with(library, limit=None)


@pytest.mark.unit
def test_get_artist_album_frequencies_delegates_to_library_facade() -> None:

    db = make_db()

    db.library.list_tag_value_frequencies.return_value = {
        "artist": [("Artist A", 3)],
        "album": [("Album A", 2)],
    }

    result = get_artist_album_frequencies(db, limit=5)

    assert result == {"artist_rows": [("Artist A", 3)], "album_rows": [("Album A", 2)]}

    db.library.list_tag_value_frequencies.assert_called_once_with(["artist", "album"], 5)


@pytest.mark.unit
def test_get_tracks_for_matching_filters_valid_files_and_projects_isrc() -> None:

    db = make_db()

    song = _song(song_id=1, path="D:/Music/song.flac", normalized_path="song.flac")

    identity = _song_identity("song.flac")

    db.library.list_libraries.return_value = [{"id": 1}]

    db.library.list_tracks_for_matching.return_value = [song]

    db.library.resolve_song_identities.return_value = {1: identity}

    db.library.list_song_tags_for_songs.return_value = {identity: (SongTagAssignment(name="isrc", value="ABC123"),)}

    metadata = {1: {"title": "Song", "artist": "Artist", "album": "Album"}}

    with patch(
        "nomarr.components.library.library_song_query_comp.hydrate_songs_with_metadata",
        side_effect=lambda _db, docs: [{**d, **metadata.get(d.get("id"), {})} for d in docs],
    ):
        result = get_tracks_for_matching(db)

    assert result == [
        {
            "id": 1,
            "path": "D:/Music/song.flac",
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
            "isrc": "ABC123",
        }
    ]

    db.library.list_tracks_for_matching.assert_called_once_with({"id": 1}, limit=DEFAULT_LIMIT)

    db.library.list_song_tags_for_songs.assert_called_once_with([identity])


@pytest.mark.unit
def test_get_tracks_for_matching_scopes_to_library_and_projects_isrc() -> None:

    db = make_db()

    song = _song(song_id=1, path="D:/Music/song.flac", normalized_path="song.flac")

    identity = _song_identity("song.flac")

    db.library.list_tracks_for_matching.return_value = [song]

    db.library.resolve_song_identities.return_value = {1: identity}

    db.library.list_song_tags_for_songs.return_value = {identity: (SongTagAssignment(name="isrc", value="XYZ789"),)}

    metadata = {1: {"title": "Song", "artist": "Artist", "album": "Album"}}

    with patch(
        "nomarr.components.library.library_song_query_comp.hydrate_songs_with_metadata",
        side_effect=lambda _db, docs: [{**d, **metadata.get(d.get("id"), {})} for d in docs],
    ):
        result = get_tracks_for_matching(db, library=1)

    assert result == [
        {
            "id": 1,
            "path": "D:/Music/song.flac",
            "title": "Song",
            "artist": "Artist",
            "album": "Album",
            "isrc": "XYZ789",
        }
    ]

    db.library.list_tracks_for_matching.assert_called_once_with(1, limit=DEFAULT_LIMIT)

    db.library.list_songs.assert_not_called()

    db.library.list_song_tags_for_songs.assert_called_once_with([identity])


@pytest.mark.unit
def test_clear_library_data_truncates_all_facades() -> None:

    db = make_db()

    # list_vector_collection_names is called synchronously (no await) in source,
    # so it must be a sync mock — AsyncMock would return a coroutine by default
    db.ml.list_vector_collection_names = MagicMock(return_value=["vectors_track__hot__effnet"])

    db.library.list_libraries.return_value = [{"id": 1}, {"id": 2}, {"id": 3}]

    db.library.list_library_song_ids.side_effect = [[1, 2], [3], []]

    with patch(
        "nomarr.components.ml.inference.ml_output_stream_store_comp.delete_output_streams"
    ) as mock_delete_output_streams:
        clear_library_data(db)

    db.ml.clear_vector_collection.assert_called_once_with("vectors_track__hot__effnet")

    assert db.library.list_library_song_ids.call_args_list == [
        call({"id": 1}, limit=None),
        call({"id": 2}, limit=None),
        call({"id": 3}, limit=None),
    ]

    assert mock_delete_output_streams.call_args_list == [
        call(db, 1),
        call(db, 2),
        call(db, 3),
    ]

    assert db.library.remove_pipeline_state.call_args_list == [
        call({"id": 1}),
        call({"id": 2}),
        call({"id": 3}),
    ]

    db.library.admin_truncate_song_tag_assignments.assert_called_once_with()

    db.app.truncate_song_state_edges.assert_called_once_with()

    db.library.truncate_song_links.assert_called_once_with()

    db.library.truncate_folder_links.assert_called_once_with()

    db.library.admin_truncate_tags.assert_called_once_with()

    db.library.truncate_songs.assert_called_once_with()

    db.library.truncate_folders.assert_called_once_with()

    db.library.truncate_scan_records.assert_called_once_with()


@pytest.mark.unit
def test_search_songs_with_tags_filters_and_hydrates_page() -> None:
    db = make_db()
    song = _song(song_id=1, path="D:/Music/one.flac", normalized_path="one.flac")
    identity = _song_identity("one.flac")
    # artist, album, title pattern lookups each resolve song 1.
    db.library.find_songs_with_tag_pattern.side_effect = [[song], [song], [song]]
    db.library.list_tags.return_value = (TagRef(name="genre", value="rock"),)
    db.library.find_songs_with_tag.return_value = [song]
    db.app.song_ids_with_state.return_value = [1]
    db.library.list_songs_by_ids.return_value = [song]
    db.library.resolve_song_identities.return_value = {1: identity}
    db.library.list_song_tags_for_songs.return_value = {identity: (SongTagAssignment(name="genre", value="rock"),)}
    db.library.get_library_ids_for_songs.return_value = {1: 1}

    metadata = {1: {"artist": "Artist", "album": "Album", "title": "Song One"}}

    with patch(
        "nomarr.components.library.library_song_query_comp.hydrate_songs_with_metadata",
        side_effect=lambda _db, docs: [{**d, **metadata.get(d.get("id"), {})} for d in docs],
    ):
        rows, total = search_songs_with_tags(
            db,
            query_text="song",
            artist="Artist",
            album="Album",
            tag_key="genre",
            tag_value="rock",
            tagged_only=True,
            limit=10,
            offset=0,
        )

    assert total == 1
    assert rows == [
        {
            **song.to_dict(),
            "artist": "Artist",
            "album": "Album",
            "title": "Song One",
            "tags": [FileTag(key="genre", value="rock", tag_type="string", is_nomarr=False)],
            "library_id": 1,
        }
    ]
    assert db.library.find_songs_with_tag_pattern.call_args_list == [
        call("artist", "%Artist%"),
        call("album", "%Album%"),
        call("title", "%song%"),
    ]
    db.library.list_tags.assert_called_once_with(name="genre", limit=None)
    db.library.find_songs_with_tag.assert_called_once_with(TagRef(name="genre", value="rock"), limit=None)
    db.app.song_ids_with_state.assert_called_once_with(STATE_PROCESSED, limit=None)
    db.library.list_songs_by_ids.assert_called_once_with([1])
    db.library.list_song_tags_for_songs.assert_called_once_with([identity])


@pytest.mark.unit
def test_count_files_by_tag_uses_library_facade_for_string_and_numeric_modes() -> None:
    # String branch: delegates to the facade's exact-tag count intent.
    db = make_db()
    db.library.count_songs_by_tag.return_value = 2

    string_count = count_songs_by_tag(db, "genre", "rock")

    assert string_count == 2
    db.library.count_songs_by_tag.assert_called_once_with("genre", "rock")

    # Numeric branch: dedicated uncapped SQL count intent, no tag/edge materialization.
    db = make_db()
    db.library.count_songs_by_numeric_tag.return_value = 7

    numeric_count = count_songs_by_tag(db, "nom:bpm", 120.0)

    assert numeric_count == 7
    db.library.count_songs_by_numeric_tag.assert_called_once_with("nom:bpm", 120.0)
    db.library.count_songs_by_tag.assert_not_called()


@pytest.mark.unit
def test_search_files_by_tag_numeric_sorts_by_distance_and_hydrates_tags() -> None:
    db = make_db()
    # SQL paged intent returns rows already ordered (distance ASC, song id ASC):
    # song 2 (distance 1.0) before song 1 (distance 2.0).
    song1 = _song(song_id=1, path="D:/Music/song1.mp3", normalized_path="song1.mp3")
    song2 = _song(song_id=2, path="D:/Music/song2.mp3", normalized_path="song2.mp3")
    identity1 = _song_identity("song1.mp3")
    identity2 = _song_identity("song2.mp3")
    db.library.find_songs_with_numeric_tag.return_value = (
        SongTagMatch(song=song2, matched_tag="121.0", distance=1.0),
        SongTagMatch(song=song1, matched_tag="118.0", distance=2.0),
    )
    db.library.resolve_song_identities.return_value = {2: identity2, 1: identity1}
    db.library.list_song_tags_for_songs.return_value = {
        identity1: (SongTagAssignment(name="nom:bpm", value=118.0),),
        identity2: (SongTagAssignment(name="nom:bpm", value=121.0),),
    }
    db.library.get_library_ids_for_songs.return_value = {1: 1, 2: 1}

    with patch(
        "nomarr.components.library.library_song_query_comp.hydrate_songs_with_metadata",
        side_effect=lambda _db, docs: docs,
    ):
        result = search_songs_by_tag(db, "nom:bpm", 120.0, limit=1, offset=0)

    assert result[0]["id"] == 2
    assert result[0]["distance"] == 1.0
    assert result[0]["library_id"] == 1
    assert result[0]["matched_tag"] == {"key": "nom:bpm", "value": 121.0}
    assert result[1]["matched_tag"] == {"key": "nom:bpm", "value": 118.0}
    db.library.find_songs_with_numeric_tag.assert_called_once_with(
        TagRef(name="nom:bpm", value=120.0), limit=1, offset=0
    )
    # Legacy capped materialization path is dead for numeric search.
    db.library.count_songs_by_tag.assert_not_called()
    db.library.list_tags.assert_not_called()
    # Only the SQL page is hydrated (its own song ids, not the full result).
    db.library.list_song_tags_for_songs.assert_called_once_with([identity2, identity1])


@pytest.mark.unit
def test_search_files_by_tag_numeric_preserves_sql_row_order_without_python_resort() -> None:
    """The component must NOT re-sort the SQL-returned page in Python."""
    db = make_db()
    # Deliberately scrambled (distance 2.0 before 1.0) — as the SQL would already
    # have ordered it. The component must preserve the row order as given.
    song1 = _song(song_id=1, path="D:/Music/song1.mp3", normalized_path="song1.mp3")
    song2 = _song(song_id=2, path="D:/Music/song2.mp3", normalized_path="song2.mp3")
    identity1 = _song_identity("song1.mp3")
    identity2 = _song_identity("song2.mp3")
    db.library.find_songs_with_numeric_tag.return_value = (
        SongTagMatch(song=song1, matched_tag="118.0", distance=2.0),
        SongTagMatch(song=song2, matched_tag="121.0", distance=1.0),
    )
    db.library.resolve_song_identities.return_value = {1: identity1, 2: identity2}
    db.library.list_song_tags_for_songs.return_value = {identity1: (), identity2: ()}
    db.library.get_library_ids_for_songs.return_value = {1: 1, 2: 1}

    with patch(
        "nomarr.components.library.library_song_query_comp.hydrate_songs_with_metadata",
        side_effect=lambda _db, docs: docs,
    ):
        result = search_songs_by_tag(db, "nom:bpm", 120.0, limit=10, offset=0)

    assert [r["id"] for r in result] == [1, 2]
    assert [r["distance"] for r in result] == [2.0, 1.0]


@pytest.mark.unit
def test_search_files_by_tag_numeric_page_total_equals_count() -> None:
    """A full page's size equals the page limit and matches the uncapped count."""
    db = make_db()
    matches = tuple(
        SongTagMatch(
            song=_song(song_id=i, path=f"D:/Music/s{i}.mp3", normalized_path=f"s{i}.mp3"),
            matched_tag="120.0",
            distance=float(i),
        )
        for i in (1, 2, 3)
    )
    db.library.find_songs_with_numeric_tag.return_value = matches
    db.library.count_songs_by_numeric_tag.return_value = 3
    identity_map = {i: _song_identity(f"s{i}.mp3") for i in (1, 2, 3)}
    db.library.resolve_song_identities.return_value = identity_map
    db.library.list_song_tags_for_songs.return_value = dict.fromkeys(identity_map.values(), ())
    db.library.get_library_ids_for_songs.return_value = dict.fromkeys((1, 2, 3), 1)

    with patch(
        "nomarr.components.library.library_song_query_comp.hydrate_songs_with_metadata",
        side_effect=lambda _db, docs: docs,
    ):
        result = search_songs_by_tag(db, "nom:bpm", 120.0, limit=3, offset=0)
        total = count_songs_by_tag(db, "nom:bpm", 120.0)

    assert len(result) == 3
    assert total == 3


@pytest.mark.unit
def test_search_files_by_tag_numeric_empty_page_returns_empty() -> None:
    """An empty SQL page short-circuits to an empty result without hydration."""
    db = make_db()
    db.library.find_songs_with_numeric_tag.return_value = ()

    with patch(
        "nomarr.components.library.library_song_query_comp.hydrate_songs_with_metadata",
    ):
        result = search_songs_by_tag(db, "nom:bpm", 120.0, limit=10, offset=0)

    assert result == []
    db.library.find_songs_with_numeric_tag.assert_called_once_with(
        TagRef(name="nom:bpm", value=120.0), limit=10, offset=0
    )
    db.library.count_songs_by_tag.assert_not_called()
    db.library.list_tags.assert_not_called()
    db.library.list_songs_by_ids.assert_not_called()


@pytest.mark.unit
def test_require_library_song_id_returns_id_for_existing_song() -> None:

    db = make_db()

    with patch("nomarr.components.library.library_song_query_comp.get_library_song") as mock_get_library_file:
        mock_get_library_file.return_value = {"id": 123}

        result = require_library_song_id(db, "D:/Music/song.flac", library=1)

    assert result == 123

    mock_get_library_file.assert_called_once_with(db, "D:/Music/song.flac", library=1)


@pytest.mark.unit
def test_require_library_song_id_raises_for_missing_song() -> None:

    db = make_db()

    with patch("nomarr.components.library.library_song_query_comp.get_library_song") as mock_get_library_file:
        mock_get_library_file.return_value = None

        with pytest.raises(FileNotFoundError, match=r"File not in library: D:/Music/missing\.flac"):
            require_library_song_id(db, "D:/Music/missing.flac")

    mock_get_library_file.assert_called_once_with(db, "D:/Music/missing.flac", library=None)


@pytest.mark.unit
def test_list_all_song_ids_filters_non_string_ids_and_uses_default_limit() -> None:

    db = make_db()

    db.library.list_libraries.return_value = [{"id": 1}]

    db.library.list_library_song_ids.return_value = [1, 4]

    result = list_all_song_ids(db)

    assert result == [1, 4]

    db.library.list_library_song_ids.assert_called_once_with({"id": 1}, limit=DEFAULT_LIMIT)


@pytest.mark.unit
def test_get_sample_normalized_path_returns_first_value() -> None:

    db = make_db()

    db.library.list_libraries.return_value = [{"id": 1}]

    db.library.list_songs.return_value = [_song(normalized_path="Artist/Album/song.flac")]

    result = get_sample_normalized_path(db)

    assert result == "Artist/Album/song.flac"

    db.library.list_songs.assert_called_once_with({"id": 1}, limit=1)


@pytest.mark.unit
def test_find_move_candidate_by_chromaprint_passes_library_domain_object() -> None:

    db = make_db()

    library = Library(name="main", root_path="/music")

    candidate = _song(song_id=9, path="D:/Music/cand.flac", normalized_path="cand.flac", chromaprint="abc123")

    db.library.find_library_song_by_chromaprint.return_value = candidate

    result = find_move_candidate_by_chromaprint(db, library, "abc123")

    assert result == candidate.to_dict()

    db.library.find_library_song_by_chromaprint.assert_called_once_with(library, "abc123")


@pytest.mark.unit
def test_search_songs_with_tags_unfiltered_paginates_beyond_default_limit() -> None:
    """Broad searches include songs after the former 1,000-song cap."""
    db = make_db()
    songs = [
        _song(song_id=song_id, path=f"D:/Music/s{song_id}.flac", normalized_path=f"s{song_id}.flac")
        for song_id in range(DEFAULT_LIMIT + 1)
    ]
    db.library.list_libraries.return_value = [{"id": 1}]
    db.library.list_songs.return_value = songs

    with (
        patch(
            "nomarr.components.library.library_song_query_comp.hydrate_songs_with_metadata",
            side_effect=lambda _db, docs: docs,
        ),
        patch(
            "nomarr.components.library.library_song_query_comp._hydrate_files_with_tags",
            side_effect=lambda _db, docs: docs,
        ),
    ):
        rows, total = search_songs_with_tags(db, limit=1, offset=DEFAULT_LIMIT)

    assert rows == [songs[-1].to_dict()]
    assert total == DEFAULT_LIMIT + 1
    db.library.list_songs.assert_called_once_with({"id": 1}, limit=None)


@pytest.mark.unit
def test_search_songs_with_tags_tagged_only_paginates_beyond_default_limit() -> None:
    """Tagged-only searches use every processed song id, not only the first 1,000."""
    db = make_db()
    song_ids = list(range(DEFAULT_LIMIT + 1))
    songs = [
        _song(song_id=song_id, path=f"D:/Music/s{song_id}.flac", normalized_path=f"s{song_id}.flac")
        for song_id in song_ids
    ]
    db.app.song_ids_with_state.return_value = song_ids
    db.library.list_songs_by_ids.return_value = songs

    with (
        patch(
            "nomarr.components.library.library_song_query_comp.hydrate_songs_with_metadata",
            side_effect=lambda _db, docs: docs,
        ),
        patch(
            "nomarr.components.library.library_song_query_comp._hydrate_files_with_tags",
            side_effect=lambda _db, docs: docs,
        ),
    ):
        rows, total = search_songs_with_tags(db, tagged_only=True, limit=1, offset=DEFAULT_LIMIT)

    assert rows == [songs[-1].to_dict()]
    assert total == DEFAULT_LIMIT + 1
    db.app.song_ids_with_state.assert_called_once_with(STATE_PROCESSED, limit=None)
    db.library.list_songs_by_ids.assert_called_once_with(song_ids)
