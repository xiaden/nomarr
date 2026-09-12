from __future__ import annotations

import inspect
import re
from dataclasses import replace
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
    invalid_objects: list[Any] = [None, object()]
    for invalid in (invalid_rows, invalid_ids, invalid_objects):
        with pytest.raises(TypeError, match="typed song carriers"):
            locators_for_carriers(db, invalid)
    db.library.list_libraries.assert_not_called()
    db.library.list_songs_by_identity.assert_not_called()


@pytest.mark.unit
def test_empty_input_is_empty_without_touching_the_facade() -> None:
    db = MagicMock()
    assert locators_for_carriers(db, []) == []
    db.library.list_libraries.assert_not_called()
    db.library.list_songs_by_identity.assert_not_called()


@pytest.mark.unit
def test_all_uuidless_libraries_yield_none_without_facade_lookup() -> None:
    value = song("x.flac")
    db = MagicMock()
    db.library.list_libraries.return_value = [Library(library_uuid=None, name="legacy", root_path="/legacy")]
    assert locators_for_carriers(db, [HydratedSong(value, {})]) == [None]
    db.library.list_songs_by_identity.assert_not_called()


@pytest.mark.unit
def test_malformed_carrier_payloads_are_rejected_before_facade_work() -> None:
    db = MagicMock()
    malformed: list[Any] = [
        HydratedSong(song={"id": 1}, metadata={}),  # type: ignore[arg-type]
        StateTaggedSong(candidate={"song": song("x.flac")}, has_tagged_state=True),  # type: ignore[arg-type]
    ]
    for carrier in malformed:
        with pytest.raises(TypeError, match="typed song carriers") as excinfo:
            locators_for_carriers(db, [carrier])
        assert "id" not in str(excinfo.value)
    db.library.list_libraries.assert_not_called()
    db.library.list_songs_by_identity.assert_not_called()


@pytest.mark.unit
def test_same_normalized_path_but_non_equal_song_is_unresolved() -> None:
    value = song("x.flac")
    impostor = replace(value, path="/music/impostor/x.flac")
    db = MagicMock()
    db.library.list_libraries.return_value = [LIBRARY_RECORD]
    db.library.list_songs_by_identity.return_value = [impostor]
    assert locators_for_carriers(db, [HydratedSong(value, {})]) == [None]


@pytest.mark.unit
def test_resolves_against_uuid_bearing_library_not_path_prefix() -> None:
    other_record = Library(library_uuid="other-uuid", name="other", root_path="/other")
    other_identity = LibraryIdentity("other-uuid", name="other", root_path="/other")
    value = song("shared.flac")
    decoy = replace(value, path="/other/shared.flac")

    db = MagicMock()
    db.library.list_libraries.return_value = [LIBRARY_RECORD, other_record]

    def resolve(locators: list[SongIdentity]) -> list[Song]:
        return [value] if locators[0].library.library_uuid == "other-uuid" else [decoy]

    db.library.list_songs_by_identity.side_effect = resolve
    assert locators_for_carriers(db, [TrackSong(value, {}, None)]) == [SongIdentity(other_identity, "shared.flac")]


@pytest.mark.unit
def test_projection_source_has_no_private_helper_or_transaction_tokens() -> None:
    source = inspect.getsource(locators_for_carriers)
    for forbidden in (
        "_locators_for_songs",
        "resolve_song_identity",
        ".transaction",
        ".session",
        ".to_dict",
        "from_row",
        "require_library_song_id",
    ):
        assert forbidden not in source
    assert re.search(r"\bsong_id\b", source) is None
