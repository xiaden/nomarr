"""Semantic lifecycle coverage for opaque ``nom1`` SongLocator projections.

These component-level tests cover stale and partial locator projections,
retry/idempotence, deterministic concurrent token generation, rename and
delete/recreate invalidation, and projection-error redaction. They intentionally
exercise the component boundary without importing interfaces. Database-backed
characterization coverage is environment-dependent and remains deferred to the
CI PostgreSQL test job when local PostgreSQL or Docker is unavailable.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, cast

import pytest

from nomarr.components.library.library_song_query_comp import tagged_songs_for_locators
from nomarr.components.navidrome.descriptor_match_comp import (
    _descriptors_by_key,
    descriptor_for_locator,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment
from nomarr.helpers.song_locator_codec import (
    SongLocatorFormatError,
    encode_song_locator,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

pytestmark = pytest.mark.unit

_UUID_A = "123e4567-e89b-42d3-a456-426614174000"
_UUID_B = "223e4567-e89b-42d3-b456-426614174001"
_UUID_V5 = "123e4567-e89b-52d3-a456-426614174000"


def _locator(library_uuid: str, path: str) -> SongIdentity:
    return SongIdentity(library=LibraryIdentity(library_uuid=library_uuid), normalized_path=path)


def _song(path: str, duration_seconds: float | None = 180.0) -> Song:
    return Song(
        path=f"/music/{path}",
        normalized_path=path,
        file_size=100,
        modified_time=1000,
        duration_seconds=duration_seconds,
        chromaprint=None,
        needs_tagging=False,
        is_valid=True,
        tagged=False,
        calibration_hash=None,
        write_claimed_by=None,
        last_tagged_at=None,
        scanned_at=None,
        created_at=1000,
    )


def _tags(path: str, title: str, artist: str, album: str = "Album") -> tuple[SongTagAssignment, ...]:
    return (
        SongTagAssignment(name="title", value=title),
        SongTagAssignment(name="artist", value=artist),
        SongTagAssignment(name="album", value=album),
    )


def _production_db(db: _ProjectionDb) -> Database:
    """Cross the production ``Database`` boundary for this in-memory fixture."""
    return cast("Database", db)


class _ProjectionDb:
    """Minimal in-memory stand-in for the ``db.library`` read facade."""

    def __init__(
        self,
        entries: list[tuple[str, str, str, str, str]],
    ) -> None:
        # entries: (library_uuid, path, title, artist, album)
        self.library = self
        self._libraries: list[Library] = []
        self._songs: dict[tuple[str, str], Song] = {}
        self._tags: dict[tuple[str, str], tuple[SongTagAssignment, ...]] = {}
        seen: set[str] = set()
        for library_uuid, path, title, artist, album in entries:
            if library_uuid not in seen:
                seen.add(library_uuid)
                self._libraries.append(
                    Library(name=f"lib-{library_uuid[:8]}", root_path="/music", library_uuid=library_uuid)
                )
            key = (library_uuid, path)
            self._songs[key] = _song(path)
            self._tags[key] = _tags(path, title, artist, album)

    def list_libraries(self) -> list[Library]:
        return list(self._libraries)

    def list_songs_by_identity(self, locators: list[SongIdentity]) -> list[Song]:
        out: list[Song] = []
        for locator in locators:
            song = self._songs.get((locator.library.library_uuid, locator.normalized_path))
            if song is not None:
                out.append(song)
        return out

    def list_song_tags_for_songs(
        self, locators: list[SongIdentity]
    ) -> dict[SongIdentity, tuple[SongTagAssignment, ...]]:
        return {
            locator: self._tags.get((locator.library.library_uuid, locator.normalized_path), ()) for locator in locators
        }

    def get_song(self, locator: SongIdentity) -> Song | None:
        return self._songs.get((locator.library.library_uuid, locator.normalized_path))

    def find_songs_with_tag_pattern(self, name: str, value: str, limit: int | None = None) -> list[Song]:
        assert name == "title"
        return [song for key, song in self._songs.items() if self._tags[key][0].value == value]


class TestStaleAndPartialProjection:
    def test_library_scope_keeps_colliding_path_with_live_library(self) -> None:
        db = _ProjectionDb([(_UUID_B, "shared.mp3", "Library B", "Artist B", "Album B")])
        stale_a = _locator(_UUID_A, "shared.mp3")
        live_b = _locator(_UUID_B, "shared.mp3")

        carriers = tagged_songs_for_locators(_production_db(db), [stale_a, live_b])
        projected = _descriptors_by_key(_production_db(db), [stale_a, live_b])

        assert [carrier.song for carrier in carriers] == [db.get_song(live_b)]
        tags_by_name = {tag.key: tag.value for tag in carriers[0].tags}
        assert tags_by_name == {"title": "Library B", "artist": "Artist B", "album": "Album B"}
        assert set(projected) == {encode_song_locator(live_b)}
        assert projected[encode_song_locator(live_b)]["title"] == "Library B"
        assert projected[encode_song_locator(live_b)]["artist"] == "Artist B"
        assert projected[encode_song_locator(live_b)]["nomarr_file_key"] == encode_song_locator(live_b)

    def test_stale_locator_projects_to_none(self) -> None:
        db = _ProjectionDb([(_UUID_A, "gone.mp3", "Gone", "Artist", "Album")])
        assert descriptor_for_locator(_production_db(db), _locator(_UUID_A, "gone.mp3")) is not None
        assert descriptor_for_locator(_production_db(db), _locator(_UUID_A, "never.mp3")) is None

    def test_partial_projection_skips_stale_locator(self) -> None:
        db = _ProjectionDb([(_UUID_A, "live.mp3", "Live", "Artist", "Album")])
        live = _locator(_UUID_A, "live.mp3")
        stale = _locator(_UUID_A, "missing.mp3")

        projected = _descriptors_by_key(_production_db(db), [live, stale])

        assert set(projected) == {encode_song_locator(live)}
        assert projected[encode_song_locator(live)]["title"] == "Live"

    def test_all_stale_projection_is_empty_not_an_error(self) -> None:
        db = _ProjectionDb([(_UUID_A, "live.mp3", "Live", "Artist", "Album")])
        assert _descriptors_by_key(_production_db(db), [_locator(_UUID_A, "a.mp3"), _locator(_UUID_A, "b.mp3")]) == {}


class TestRetryAndConcurrency:
    def test_projection_retry_is_idempotent(self) -> None:
        db = _ProjectionDb([(_UUID_A, "song.mp3", "Song", "Artist", "Album")])
        locator = _locator(_UUID_A, "song.mp3")

        first = _descriptors_by_key(_production_db(db), [locator])
        second = _descriptors_by_key(_production_db(db), [locator])

        assert first == second
        assert encode_song_locator(locator) == encode_song_locator(locator)

    def test_concurrent_token_generation_is_deterministic(self) -> None:
        locator = _locator(_UUID_A, "song.mp3")
        expected = encode_song_locator(locator)
        results: set[str] = set()
        lock = threading.Lock()

        def work() -> None:
            token = encode_song_locator(locator)
            with lock:
                results.add(token)

        threads = [threading.Thread(target=work) for _ in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert results == {expected}


class TestRenameDeleteRecreate:
    def test_rename_changes_token_and_stales_old_locator(self) -> None:
        _ProjectionDb([(_UUID_A, "old.mp3", "Song", "Artist", "Album")])
        old_locator = _locator(_UUID_A, "old.mp3")
        old_token = encode_song_locator(old_locator)

        after = _ProjectionDb([(_UUID_A, "new.mp3", "Song", "Artist", "Album")])
        new_locator = _locator(_UUID_A, "new.mp3")
        new_token = encode_song_locator(new_locator)

        assert new_token != old_token
        assert descriptor_for_locator(_production_db(after), old_locator) is None
        assert descriptor_for_locator(_production_db(after), new_locator) is not None

    def test_delete_and_recreate_mints_new_library_uuid_and_token(self) -> None:
        path = "song.mp3"
        first_token = encode_song_locator(_locator(_UUID_A, path))

        recreated = _ProjectionDb([(_UUID_B, path, "Song", "Artist", "Album")])
        second_token = encode_song_locator(_locator(_UUID_B, path))

        assert second_token != first_token
        assert descriptor_for_locator(_production_db(recreated), _locator(_UUID_A, path)) is None
        assert descriptor_for_locator(_production_db(recreated), _locator(_UUID_B, path)) is not None


class TestProjectionErrorsDoNotLeak:
    def test_noncanonical_uuid_error_does_not_echo_locator_contents(self) -> None:
        db = _ProjectionDb([(_UUID_V5, "secret-song.mp3", "Secret", "Artist", "Album")])
        with pytest.raises(SongLocatorFormatError) as excinfo:
            descriptor_for_locator(_production_db(db), _locator(_UUID_V5, "secret-song.mp3"))

        message = str(excinfo.value)
        assert "secret-song.mp3" not in message
        assert _UUID_V5 not in message
