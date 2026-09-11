from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from nomarr.components.library.library_song_query_comp import locators_for_carriers
from nomarr.components.library.song_query_types import (
    HydratedSong,
    RecentSong,
    StateTaggedSong,
    TaggedSong,
    TagMatchedSong,
    TrackSong,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_state_candidate_dataclass import SongStateCandidate
from nomarr.helpers.dataclasses.song_tag_dataclass import TagRef

LIBRARY = LibraryIdentity("library-uuid", name="music", root_path="/music")
LIBRARY_RECORD = Library(library_uuid="library-uuid", name="music", root_path="/music")


def song(path: str, *, title: str = "song") -> Song:
    return Song(
        path=f"/music/{path}",
        normalized_path=path,
        file_size=1,
        modified_time=1,
        duration_seconds=1.0,
        chromaprint=None,
        needs_tagging=False,
        is_valid=True,
        tagged=True,
        calibration_hash=None,
        write_claimed_by=None,
        last_tagged_at=None,
        scanned_at=None,
        created_at=1,
    )


def candidate(value: Song) -> SongStateCandidate:
    return SongStateCandidate(identity=SongIdentity(LIBRARY, value.normalized_path), song=value, states=("processed",))


def carriers(*songs: Song) -> list[Any]:
    return [
        HydratedSong(songs[0], {}),
        TaggedSong(songs[1], {}, ()),
        StateTaggedSong(candidate(songs[2]), True),
        RecentSong(candidate(songs[3]), {}, 1, "scanned"),
        TagMatchedSong(songs[4], {}, TagRef("genre", "jazz"), 0.1),
        TrackSong(songs[5], {}, None),
    ]


@pytest.mark.unit
def test_projects_all_public_carriers_in_input_order_using_semantic_equality() -> None:
    values = [song(f"{letter}.flac") for letter in "abcdef"]
    db = MagicMock()
    db.library.list_libraries.return_value = [LIBRARY_RECORD]
    db.library.list_songs_by_identity.return_value = list(reversed(values))
    assert locators_for_carriers(db, carriers(*values)) == [
        SongIdentity(LIBRARY, value.normalized_path) for value in values
    ]


@pytest.mark.unit
def test_unresolved_carrier_is_none_and_uuidless_library_is_skipped() -> None:
    present, missing = song("present.flac"), song("missing.flac")
    db = MagicMock()
    db.library.list_libraries.return_value = [
        Library(library_uuid=None, name="legacy", root_path="/legacy"),
        LIBRARY_RECORD,
    ]
    db.library.list_songs_by_identity.return_value = [present]
    assert locators_for_carriers(db, [HydratedSong(present, {}), HydratedSong(missing, {})]) == [
        SongIdentity(LIBRARY, "present.flac"),
        None,
    ]


@pytest.mark.unit
def test_rejects_rows_and_integer_inputs_without_compatibility_shim() -> None:
    db = MagicMock()
    invalid_rows: list[Any] = [{"id": 1}]
    invalid_ids: list[Any] = [42]
    with pytest.raises(TypeError, match="typed song carriers"):
        locators_for_carriers(db, invalid_rows)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="typed song carriers"):
        locators_for_carriers(db, invalid_ids)  # type: ignore[arg-type]
