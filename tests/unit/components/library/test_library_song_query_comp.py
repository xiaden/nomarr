"""Tests for ``nomarr.components.library.library_song_query_comp``.

These exercise the typed semantic query boundary that F landed in P1: public helpers
return semantic ``Song`` / ``SongStateCandidate`` values, typed carriers
(``HydratedSong``/``TaggedSong``/``StateTaggedSong``/``RecentSong``/``TagMatchedSong``/
``TrackSong``), or scalar/aggregate values — never row-shaped documents. The facade is
mocked at the boundary with canned semantic values (per nomarr-testing); persistence
semantics (SQL/paging internals/FK behavior) are owned by Plan C/E and are not duplicated
here.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.library_song_query_comp import (
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
    get_song_modified_times,
    get_songs_by_chromaprint,
    locators_for_carriers,
    get_songs_by_paths_bulk,
    get_songs_for_folder,
    get_songs_for_folders,
    get_tagged_file_paths,
    get_tracks_for_matching,
    list_songs,
    search_songs_by_tag,
    search_songs_with_tags,
)
from nomarr.components.library.song_query_types import (
    HydratedSong,
    RecentSong,
    StateTaggedSong,
    TaggedSong,
    TagMatchedSong,
    TrackSong,
)
from nomarr.helpers.constants.file_states import STATE_PROCESSED
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_state_candidate_dataclass import SongStateCandidate
from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment

MUSIC = LibraryIdentity(library_uuid="2621ebfb-71ff-5168-a812-5342ca310e8c", name="music", root_path="/music")
VAULT = LibraryIdentity(library_uuid="eb6bc02b-f253-5146-ae58-ece0bb02e9ee", name="vault", root_path="/vault")
MUSIC_LIB = Library(library_uuid="2621ebfb-71ff-5168-a812-5342ca310e8c", name="music", root_path="/music")
VAULT_LIB = Library(library_uuid="eb6bc02b-f253-5146-ae58-ece0bb02e9ee", name="vault", root_path="/vault")


def _db() -> MagicMock:
    db = MagicMock()
    db.library = MagicMock()
    return db


def _song(normalized_path: str, *, root_path: str = "/music", tagged: bool = True, **overrides: object) -> Song:
    """Build a semantic ``Song`` (no generated ids) for one library root."""
    base: dict[str, object] = {
        "path": f"{root_path}/{normalized_path}",
        "normalized_path": normalized_path,
        "file_size": 0,
        "modified_time": 0,
        "duration_seconds": None,
        "chromaprint": None,
        "needs_tagging": False,
        "is_valid": True,
        "tagged": tagged,
        "calibration_hash": None,
        "write_claimed_by": None,
        "last_tagged_at": None,
        "scanned_at": None,
        "created_at": 0,
    }
    base.update(overrides)
    return Song(**base)  # type: ignore[arg-type]


def _identity(library: LibraryIdentity, normalized_path: str) -> SongIdentity:
    return SongIdentity(library=library, normalized_path=normalized_path)


def _tag(name: str, value: object, namespace: str = "default") -> SongTagAssignment:
    return SongTagAssignment(name=name, value=value, namespace=namespace)


def _tags_by_name(songs: list[Song]) -> dict[SongIdentity, tuple[SongTagAssignment, ...]]:
    """Default: every song carries its artist/album/title from its file name words."""
    out: dict[SongIdentity, tuple[SongTagAssignment, ...]] = {}
    for song in songs:
        stem = song.normalized_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        out[_identity(MUSIC, song.normalized_path)] = (_tag("title", stem),)
    return out


def _candidate(song: Song, *, states: tuple[str, ...] = ("processed",)) -> SongStateCandidate:
    name = song.path.split("/")[1] if len(song.path) > 1 else "music"
    root_path = song.path.rsplit("/", 1)[0]
    lib = LibraryIdentity(
        library_uuid=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{name}\x00{root_path}")),
        name=name,
        root_path=root_path,
    )
    identity = SongIdentity(library=lib, normalized_path=song.normalized_path)
    return SongStateCandidate(identity=identity, song=song, states=states)


# ─────────────────────────────────────────────────────────────────────────
# P2-S3 — path lookup / single-song lookups
# ─────────────────────────────────────────────────────────────────────────


class TestSingleSongLookups:
    @pytest.mark.unit
    def test_get_library_song_scoped_uses_normalized_identity(self) -> None:
        db = _db()
        song = _song("album/x.flac")
        db.library.get_song_by_normalized_path.return_value = song
        result = get_library_song(db, "/music/album/x.flac", library=MUSIC_LIB)
        assert result is song
        assert isinstance(result, Song)
        assert not hasattr(result, "song_id")

    @pytest.mark.unit
    def test_get_library_song_scoped_miss_returns_none(self) -> None:
        db = _db()
        db.library.get_song_by_normalized_path.return_value = None
        assert get_library_song(db, "/music/missing.flac", library=MUSIC_LIB) is None

    @pytest.mark.unit
    def test_get_library_song_unscoped_searches_all_libraries(self) -> None:
        db = _db()
        song = _song("x.flac", root_path="/vault")
        db.library.find_song_by_path_any_library.return_value = song
        assert get_library_song(db, "/vault/x.flac") is song

    @pytest.mark.unit
    def test_get_library_song_unscoped_miss_returns_none(self) -> None:
        db = _db()
        db.library.find_song_by_path_any_library.return_value = None
        assert get_library_song(db, "/nope/x.flac") is None

    @pytest.mark.unit
    def test_get_songs_by_paths_bulk_keys_by_input_path_and_skips_misses(self) -> None:
        db = _db()
        present = _song("a.flac", root_path="/music")
        db.library.find_song_by_path_any_library.side_effect = lambda path: present if path == "/music/a.flac" else None
        result = get_songs_by_paths_bulk(db, ["/music/a.flac", "/music/missing.flac"])
        assert set(result) == {"/music/a.flac"}
        assert result["/music/a.flac"] is present

    @pytest.mark.unit
    def test_get_songs_by_paths_bulk_empty_input(self) -> None:
        assert get_songs_by_paths_bulk(_db(), []) == {}

    @pytest.mark.unit
    def test_find_move_candidate_by_chromaprint_delegates(self) -> None:
        db = _db()
        song = _song("a.flac")
        db.library.find_library_song_by_chromaprint.return_value = song
        assert find_move_candidate_by_chromaprint(db, MUSIC_LIB, "fp") is song


# ─────────────────────────────────────────────────────────────────────────
# P2-S3 — listing / filtering / ordering / paging / cross-library
# ─────────────────────────────────────────────────────────────────────────


class TestListSongs:
    @pytest.mark.unit
    def test_scoped_listing_hydrates_and_pages_with_total_before_slice(self) -> None:
        db = _db()
        songs = [_song("a.flac"), _song("b.flac"), _song("c.flac")]
        db.library.list_songs.return_value = songs
        db.library.list_song_tags_for_songs.return_value = _tags_by_name(songs)
        page, total = list_songs(db, limit=2, offset=0, library=MUSIC_LIB)
        assert total == 3
        assert len(page) == 2
        assert all(isinstance(row, HydratedSong) for row in page)
        assert {row.song.normalized_path for row in page} == {"a.flac", "b.flac"}

    @pytest.mark.unit
    def test_empty_library_returns_empty_page(self) -> None:
        db = _db()
        db.library.list_songs.return_value = []
        page, total = list_songs(db, limit=10, library=MUSIC_LIB)
        assert page == []
        assert total == 0

    @pytest.mark.unit
    def test_exact_derived_artist_and_album_filter(self) -> None:
        db = _db()
        song_a = _song("a.flac")
        song_b = _song("b.flac")
        db.library.list_songs.return_value = [song_a, song_b]
        db.library.list_song_tags_for_songs.return_value = {
            _identity(MUSIC, "a.flac"): (_tag("artist", "Alpha"), _tag("album", "One")),
            _identity(MUSIC, "b.flac"): (_tag("artist", "Beta"), _tag("album", "Two")),
        }
        page, total = list_songs(db, artist="Alpha", album="One", library=MUSIC_LIB)
        assert total == 1
        assert [row.song for row in page] == [song_a]
        # exact match: substring/different-case does not pass
        page, total = list_songs(db, artist="alpha", library=MUSIC_LIB)
        assert total == 0

    @pytest.mark.unit
    def test_deterministic_order_casefold_missing_last(self) -> None:
        db = _db()
        s_b = _song("b.flac")
        s_a = _song("a.flac")
        s_c = _song("c.flac")
        db.library.list_songs.return_value = [s_b, s_a, s_c]
        db.library.list_song_tags_for_songs.return_value = {
            _identity(MUSIC, "b.flac"): (_tag("artist", "alpha"), _tag("album", "A")),
            _identity(MUSIC, "a.flac"): (_tag("artist", "Zed"), _tag("album", "B")),
            # s_c has no artist → must sort last
            _identity(MUSIC, "c.flac"): (_tag("album", "Z"),),
        }
        page, _total = list_songs(db, limit=10, library=MUSIC_LIB)
        # casefolded alpha < zed; artist-missing (c) sorts last
        assert [row.song.normalized_path for row in page] == ["b.flac", "a.flac", "c.flac"]

    @pytest.mark.unit
    def test_cross_library_materializes_full_set_before_paging(self) -> None:
        db = _db()
        music_songs = [_song("a.flac"), _song("b.flac")]
        vault_songs = [_song("v.flac", root_path="/vault")]
        db.library.list_libraries.return_value = [MUSIC_LIB, VAULT_LIB]

        def fake_list_songs(identity: LibraryIdentity, limit: int | None = None) -> list[Song]:
            return music_songs if identity.root_path == "/music" else vault_songs

        db.library.list_songs.side_effect = fake_list_songs
        music_songs + vault_songs
        db.library.list_song_tags_for_songs.side_effect = lambda ids: (
            {
                _identity(MUSIC, s.normalized_path): (_tag("title", s.normalized_path),)
                for s in music_songs
                if _identity(MUSIC, s.normalized_path) in ids
            }
            | {
                _identity(VAULT, s.normalized_path): (_tag("title", s.normalized_path),)
                for s in vault_songs
                if _identity(VAULT, s.normalized_path) in ids
            }
        )
        page, total = list_songs(db, limit=2, offset=0)
        assert total == 3
        assert len(page) == 2
        # full set materialized: both libraries queried with limit=None
        for ident in (MUSIC, VAULT):
            assert any(
                call.args[0] == ident and call.kwargs.get("limit") is None
                for call in db.library.list_songs.call_args_list
            )

    @pytest.mark.unit
    def test_cross_library_paging_offset(self) -> None:
        db = _db()
        songs = [_song(f"{i}.flac") for i in range(5)]
        db.library.list_libraries.return_value = [MUSIC_LIB]
        db.library.list_songs.return_value = songs
        db.library.list_song_tags_for_songs.return_value = _tags_by_name(songs)
        page, total = list_songs(db, limit=2, offset=2)
        assert total == 5
        assert len(page) == 2


# ─────────────────────────────────────────────────────────────────────────
# P2-S3 — path/derived listings and state reads
# ─────────────────────────────────────────────────────────────────────────


class TestPathAndStateListings:
    @pytest.mark.unit
    def test_get_tagged_file_paths_returns_physical_paths(self) -> None:
        db = _db()
        cand_a = _candidate(_song("a.flac"))
        db.library.list_songs_with_state.return_value = [cand_a]
        result = get_tagged_file_paths(db)
        assert result == ["/music/a.flac"]
        db.library.list_songs_with_state.assert_called_once_with(STATE_PROCESSED)

    @pytest.mark.unit
    def test_get_tagged_file_paths_empty(self) -> None:
        db = _db()
        db.library.list_songs_with_state.return_value = []
        assert get_tagged_file_paths(db) == []

    @pytest.mark.unit
    def test_get_song_modified_times(self) -> None:
        db = _db()
        songs = [_song("a.flac", modified_time=10), _song("b.flac", modified_time=20)]
        db.library.list_libraries.return_value = [MUSIC_LIB]
        db.library.list_songs.return_value = songs
        assert get_song_modified_times(db) == {"/music/a.flac": 10, "/music/b.flac": 20}

    @pytest.mark.unit
    def test_get_all_library_paths(self) -> None:
        db = _db()
        db.library.list_libraries.return_value = [MUSIC_LIB, VAULT_LIB]
        db.library.list_songs.side_effect = lambda identity, **_: (
            [_song("a.flac")] if identity.root_path == "/music" else [_song("v.flac", root_path="/vault")]
        )
        assert sorted(get_all_library_paths(db)) == ["/music/a.flac", "/vault/v.flac"]

    @pytest.mark.unit
    def test_get_sample_normalized_path_and_empty(self) -> None:
        db = _db()
        db.library.list_libraries.return_value = [MUSIC_LIB]
        db.library.list_songs.return_value = [_song("a.flac")]
        assert get_sample_normalized_path(db) == "a.flac"
        db.library.list_songs.return_value = []
        assert get_sample_normalized_path(db) is None

    @pytest.mark.unit
    def test_get_existing_file_paths(self) -> None:
        db = _db()
        db.library.list_existing_song_paths.return_value = ["/music/a.flac"]
        assert get_existing_file_paths(db, MUSIC_LIB, ["/music/a.flac"]) == {"/music/a.flac"}
        assert get_existing_file_paths(db, MUSIC_LIB, []) == set()

    @pytest.mark.unit
    def test_get_folder_rel_paths(self) -> None:
        db = _db()
        db.library.list_folders_for_library.return_value = [SimpleNamespace(path="folder"), SimpleNamespace(path=None)]
        assert get_folder_rel_paths(db, MUSIC_LIB) == {"folder"}

    @pytest.mark.unit
    def test_detect_nd_path_prefix(self) -> None:
        db = _db()
        db.library.list_libraries.return_value = [MUSIC_LIB]
        db.library.list_songs.return_value = [_song("album/a.flac")]
        assert detect_nd_path_prefix(db, "/nd/music/album/a.flac") == "/nd/music/"
        assert detect_nd_path_prefix(db, "/unrelated/x.flac") is None


# ─────────────────────────────────────────────────────────────────────────
# P2-S3 — tag search / typed tag outputs
# ─────────────────────────────────────────────────────────────────────────


class TestTagSearch:
    @pytest.mark.unit
    def test_search_songs_by_tag_numeric_returns_tag_matched_songs(self) -> None:
        db = _db()
        song = _song("a.flac")
        rows = [SimpleNamespace(song=song, matched_tag=0.9, distance=0.1)]
        db.library.find_songs_with_numeric_tag.return_value = rows
        db.library.list_songs_by_identity.return_value = [song]
        db.library.list_songs_with_state.return_value = []
        db.library.list_song_tags_for_songs.return_value = {_identity(MUSIC, "a.flac"): ()}
        result = search_songs_by_tag(db, "nom:bpm", 120.0)
        assert len(result) == 1
        match = result[0]
        assert isinstance(match, TagMatchedSong)
        assert match.song is song
        assert match.distance == 0.1
        assert match.matched_tag.name == "nom:bpm"
        assert match.matched_tag.namespace == "nom"
        assert match.metadata == {}

    @pytest.mark.unit
    def test_search_songs_by_tag_exact_sorted_and_empty(self) -> None:
        db = _db()
        s1 = _song("a.flac")
        s2 = _song("b.flac")
        db.library.find_songs_with_tag.return_value = [s2, s1]
        db.library.list_libraries.return_value = [MUSIC_LIB]
        db.library.list_songs_by_identity.return_value = [s1, s2]
        db.library.list_song_tags_for_songs.return_value = {
            _identity(MUSIC, "a.flac"): (_tag("artist", "A"),),
            _identity(MUSIC, "b.flac"): (_tag("artist", "B"),),
        }
        result = search_songs_by_tag(db, "artist", "match")
        assert [m.song.normalized_path for m in result] == ["a.flac", "b.flac"]
        # no persistence detail surfaces in the returned value
        assert all(isinstance(m, TagMatchedSong) for m in result)
        db2 = _db()
        db2.library.find_songs_with_tag.return_value = ()
        assert search_songs_by_tag(db2, "artist", "nope") == []

    @pytest.mark.unit
    def test_count_songs_by_tag_delegates_with_namespace(self) -> None:
        db = _db()
        db.library.count_songs_by_tag.return_value = 4
        assert count_songs_by_tag(db, "artist", "A") == 4
        db.library.count_songs_by_tag.assert_called_once_with("artist", "A", namespace="default")
        db2 = _db()
        db2.library.count_songs_by_numeric_tag.return_value = 2
        assert count_songs_by_tag(db2, "nom:bpm", 120.0) == 2
        db2.library.count_songs_by_numeric_tag.assert_called_once_with("nom:bpm", 120.0, namespace="nom")

    @pytest.mark.unit
    def test_search_songs_with_tags_no_filter_returns_tagged_universe(self) -> None:
        db = _db()
        songs = [_song("a.flac"), _song("b.flac")]
        db.library.list_libraries.return_value = [MUSIC_LIB]
        db.library.list_songs.return_value = songs
        db.library.list_song_tags_for_songs.return_value = {
            _identity(MUSIC, "a.flac"): (_tag("title", "A"), _tag("artist", "Artist")),
            _identity(MUSIC, "b.flac"): (_tag("title", "B"),),
        }
        page, total = search_songs_with_tags(db)
        assert total == 2
        assert len(page) == 2
        assert all(isinstance(row, TaggedSong) for row in page)
        assert page[0].tags  # FileTag values present
        # tags carry no generated id
        assert not any(hasattr(t, "song_id") for t in page[0].tags)

    @pytest.mark.unit
    def test_search_songs_with_tags_artist_pattern_narrows_and_total_before_page(self) -> None:
        db = _db()
        match_song = _song("a.flac")
        other = _song("b.flac")
        db.library.find_songs_with_tag_pattern.return_value = (match_song,)
        db.library.list_songs_by_identity.return_value = [match_song]
        db.library.list_libraries.return_value = [MUSIC_LIB]
        db.library.list_songs.return_value = [match_song, other]
        db.library.list_song_tags_for_songs.return_value = {
            _identity(MUSIC, "a.flac"): (_tag("artist", "Artist X"), _tag("title", "A")),
            _identity(MUSIC, "b.flac"): (_tag("title", "B"),),
        }
        page, total = search_songs_with_tags(db, artist="Artist X", limit=1, offset=0)
        assert total == 1
        assert len(page) == 1

    @pytest.mark.unit
    def test_search_songs_with_tags_tagged_only_intersects_processed(self) -> None:
        db = _db()
        s1 = _song("a.flac")
        s2 = _song("b.flac")
        db.library.find_songs_with_tag_pattern.return_value = (s1, s2)
        processed = _candidate(s1)
        db.library.list_songs_with_state.return_value = [processed]
        db.library.list_songs_by_identity.return_value = [s1]
        db.library.list_song_tags_for_songs.return_value = {
            _identity(MUSIC, "a.flac"): (_tag("title", "A"),),
        }
        page, total = search_songs_with_tags(db, tagged_only=True)
        assert total == 1
        assert page[0].song.normalized_path == "a.flac"

    @pytest.mark.unit
    def test_search_songs_with_tags_empty_when_no_matches(self) -> None:
        db = _db()
        db.library.find_songs_with_tag_pattern.return_value = ()
        page, total = search_songs_with_tags(db, artist="nothing")
        assert page == []
        assert total == 0


# ─────────────────────────────────────────────────────────────────────────
# P2-S3 — recent activity / typed track outputs
# ─────────────────────────────────────────────────────────────────────────


class TestRecentAndTracks:
    @pytest.mark.unit
    def test_get_recently_processed_orders_by_activity(self) -> None:
        db = _db()
        newest = _candidate(_song("new.flac", last_tagged_at=5000))
        oldest = _candidate(_song("old.flac", scanned_at=1000))
        db.library.list_songs_with_state.return_value = [newest, oldest]
        db.library.list_song_tags_for_songs.return_value = {
            newest.identity: (_tag("title", "new"),),
            oldest.identity: (_tag("title", "old"),),
        }
        result = get_recently_processed(db, limit=1)
        assert len(result) == 1
        assert isinstance(result[0], RecentSong)
        assert result[0].candidate.song.normalized_path == "new.flac"
        assert result[0].activity_event == "tagged"

    @pytest.mark.unit
    def test_get_recently_processed_empty(self) -> None:
        db = _db()
        db.library.list_songs_with_state.return_value = []
        assert get_recently_processed(db) == []

    @pytest.mark.unit
    def test_get_tracks_for_matching_returns_track_carriers(self) -> None:
        db = _db()
        song = _song("a.flac")
        db.library.list_libraries.return_value = [MUSIC_LIB]
        db.library.list_tracks_for_matching.return_value = [song]
        db.library.list_song_tags_for_songs.return_value = {
            _identity(MUSIC, "a.flac"): (_tag("nom:isrc", "US-ABC-00", namespace="nom"),)
        }
        result = get_tracks_for_matching(db)
        assert len(result) == 1
        track = result[0]
        assert isinstance(track, TrackSong)
        assert track.song is song
        assert track.isrc == "US-ABC-00"
        assert not hasattr(track, "id")
        assert not hasattr(track.song, "song_id")

    @pytest.mark.unit
    def test_get_tracks_for_matching_scoped_and_empty(self) -> None:
        db = _db()
        db.library.list_tracks_for_matching.return_value = []
        assert get_tracks_for_matching(db, library=MUSIC_LIB) == []
        db2 = _db()
        db2.library.list_tracks_for_matching.return_value = [_song("a.flac")]
        db2.library.list_libraries.return_value = [MUSIC_LIB]
        db2.library.list_song_tags_for_songs.return_value = {_identity(MUSIC, "a.flac"): ()}
        result = get_tracks_for_matching(db2)
        assert result[0].isrc is None


# ─────────────────────────────────────────────────────────────────────────
# P2-S3 — folder / state-annotation carriers
# ─────────────────────────────────────────────────────────────────────────


class TestFolderStateAnnotations:
    @pytest.mark.unit
    def test_get_songs_for_folder_returns_state_tagged_keyed_by_path(self) -> None:
        db = _db()
        song_a = _song("album/a.flac")
        song_b = _song("album/b.flac")
        db.library.list_songs_for_folder.return_value = [song_a, song_b]
        db.library.list_songs_with_state.return_value = [_candidate(song_a)]
        result = get_songs_for_folder(db, MUSIC_LIB, "album")
        assert set(result) == {"/music/album/a.flac", "/music/album/b.flac"}
        assert all(isinstance(v, StateTaggedSong) for v in result.values())
        assert result["/music/album/a.flac"].has_tagged_state is True
        assert result["/music/album/b.flac"].has_tagged_state is False
        # candidate carries a semantic locator (never an id)
        assert isinstance(result["/music/album/a.flac"].candidate.identity, SongIdentity)
        assert not hasattr(result["/music/album/a.flac"].candidate.song, "song_id")

    @pytest.mark.unit
    def test_get_songs_for_folders_filters_across_folders(self, song_state_contract) -> None:
        db = _db()
        song_in = _song("folder/a.flac")
        song_out = _song("other/a.flac")
        db.library.list_songs.return_value = [song_in, song_out]
        db.library.list_songs_with_state.return_value = []
        result = get_songs_for_folders(db, MUSIC_LIB, ["folder"])
        assert set(result) == {"/music/folder/a.flac"}
        for value in result.values():
            assert isinstance(value, StateTaggedSong)
            song_state_contract.assert_candidate_semantic(value.candidate)

    @pytest.mark.unit
    def test_get_songs_for_folders_empty_input(self) -> None:
        assert get_songs_for_folders(_db(), MUSIC_LIB, []) == {}


# ─────────────────────────────────────────────────────────────────────────
# P2-S3/P2-S4 — aggregates, malformed/empty, resilience, no resurrection
# ─────────────────────────────────────────────────────────────────────────


class TestAggregatesAndResilience:
    @pytest.mark.unit
    def test_get_songs_by_chromaprint_scoped_filters(self) -> None:
        db = _db()
        match = _song("a.flac", chromaprint="fp")
        other = _song("b.flac")
        db.library.list_songs.return_value = [match, other]
        assert get_songs_by_chromaprint(db, "fp", library=MUSIC_LIB) == [match]
        assert not hasattr(get_songs_by_chromaprint(db, "fp", library=MUSIC_LIB)[0], "song_id")

    @pytest.mark.unit
    def test_get_library_stats_scoped(self) -> None:
        db = _db()
        song = _song("a.flac", file_size=100, duration_seconds=10.0)
        db.library.list_songs.return_value = [song]
        db.library.count_songs_for_library.return_value = 1
        db.library.list_song_tags_for_songs.return_value = {
            _identity(MUSIC, "a.flac"): (_tag("artist", "A"), _tag("album", "B"))
        }
        with patch("nomarr.components.library.library_song_query_comp.count_untagged_files", return_value=0):
            stats = get_library_stats(db, library=MUSIC_LIB)
        assert stats["total_files"] == 1
        assert stats["total_artists"] == 1
        assert stats["total_albums"] == 1
        assert stats["total_size"] == 100
        assert stats["needs_tagging_count"] == 0

    @pytest.mark.unit
    def test_get_library_counts(self) -> None:
        db = _db()
        db.library.list_libraries.return_value = [MUSIC_LIB]
        db.library.list_songs.return_value = [_song("a.flac"), _song("sub/b.flac")]
        counts = get_library_counts(db)
        assert counts["music"]["file_count"] == 2
        assert counts["music"]["folder_count"] == 2  # "" root + "sub"

    @pytest.mark.unit
    def test_get_artist_album_frequencies(self) -> None:
        db = _db()
        db.library.list_tag_value_frequencies.return_value = {"artist": [("A", 2)], "album": [("B", 1)]}
        assert get_artist_album_frequencies(db, 5) == {"artist_rows": [("A", 2)], "album_rows": [("B", 1)]}

    @pytest.mark.unit
    def test_clear_library_data_delegates_single_maintenance_intent(self) -> None:
        db = _db()
        clear_library_data(db)
        db.library.maintenance.reset_library_data.assert_called_once_with()

    @pytest.mark.unit
    def test_unresolvable_song_degrades_to_empty_metadata_not_error(self) -> None:
        db = _db()
        song = _song("orphan.flac")
        db.library.list_libraries.return_value = [MUSIC_LIB]
        db.library.list_songs.return_value = [song]
        # list_songs_by_identity returns nothing → owning locator unresolvable
        db.library.list_songs_by_identity.return_value = []
        db.library.list_song_tags_for_songs.return_value = {}
        page, total = search_songs_with_tags(db)
        assert total == 1
        row = page[0]
        assert isinstance(row, TaggedSong)
        assert row.metadata == {}
        assert not hasattr(row.song, "song_id")

    @pytest.mark.unit
    def test_removal_no_resurrection(self) -> None:
        db = _db()
        db.library.list_songs.return_value = []
        page, total = list_songs(db, library=MUSIC_LIB)
        assert page == []
        assert total == 0
        db.library.find_song_by_path_any_library.return_value = None
        assert get_library_song(db, "/music/gone.flac") is None

    @pytest.mark.unit
    def test_retry_reload_is_stateless(self) -> None:
        db = _db()
        song = _song("a.flac")
        db.library.list_songs.return_value = [song]
        db.library.list_song_tags_for_songs.return_value = {_identity(MUSIC, "a.flac"): (_tag("artist", "A"),)}
        first = list_songs(db, library=MUSIC_LIB)[0]
        second = list_songs(db, library=MUSIC_LIB)[0]
        assert first[0].song is song
        assert first[0].metadata == second[0].metadata == {"artist": "A"}

    @pytest.mark.unit
    def test_database_state_error_propagates_typed_and_never_becomes_row(self, song_state_contract) -> None:
        # Facade raising the canonical typed error must not be swallowed into a
        # None/row/None-keyed result; it propagates deterministically.
        db = _db()
        db.library.list_songs_with_state.side_effect = song_state_contract.DatabaseStateError("boom")
        with pytest.raises(song_state_contract.DatabaseStateError):
            get_tagged_file_paths(db)

    @pytest.mark.unit
    def test_write_claimed_song_still_returned_no_claim_filtering(self) -> None:
        db = _db()
        claimed = _song("a.flac", write_claimed_by="worker-1")
        db.library.list_songs.return_value = [claimed]
        db.library.list_song_tags_for_songs.return_value = {_identity(MUSIC, "a.flac"): ()}
        page, total = list_songs(db, library=MUSIC_LIB)
        assert total == 1
        assert page[0].song is claimed


# ─────────────────────────────────────────────────────────────────────────
# P2-S1/P2-S4 — scalar helpers
# ─────────────────────────────────────────────────────────────────────────


class TestScalarHelpers:
    @pytest.mark.unit
    def test_count_recently_tagged(self) -> None:
        db = _db()
        db.library.count_recently_tagged.return_value = 3
        with patch("nomarr.components.library.library_song_query_comp.now_ms") as mock_now:
            mock_now.return_value.value = 10_000
            assert count_recently_tagged(db, window_seconds=5) == 3
        db.library.count_recently_tagged.assert_called_once_with(5_000)
