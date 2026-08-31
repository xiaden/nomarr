"""Tests for nomarr.components.tagging.tag_query_comp module.

Phase 6 rewrite: asserts the migrated domain-facing API. All reads route
through the sealed ``LibraryTagsDb`` facade using ``TagRef`` /
``SongIdentity`` and typed results (``SongTagAssignment`` / ``Song`` /
``TagUsage``); numeric handles are translated by the identity bridge
(``db.resolve_tag_identity`` / ``db.library.resolve_song_identity(s)``).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.tagging.tag_query_comp import (
    _candidate_filter_values,
    _first_assignment_value,
    _matches_tag_operator,
    _numeric_value,
    count_tags_by_name,
    get_distinct_tag_values_for_files,
    get_file_ids_for_mood_tags,
    get_file_ids_matching_tag,
    get_nomarr_tags_bulk,
    get_song_tags,
    get_tag,
    get_tag_values_grouped_by_file,
    list_songs_for_tag,
    list_tags_by_name,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment, TagRef, TagUsage


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


def _song_identity(song_id: int) -> SongIdentity:
    return SongIdentity(
        library=LibraryIdentity(name="Music", root_path="/music"),
        normalized_path=f"song{song_id}.mp3",
    )


class TestMatchesTagOperator:
    """Tests for _matches_tag_operator."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_true_for_equal_values(self) -> None:
        assert _matches_tag_operator("rock", "==", "rock") is True
        assert _matches_tag_operator("rock", "==", "jazz") is False

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_true_for_different_values_with_not_equal(self) -> None:
        assert _matches_tag_operator("rock", "!=", "jazz") is True
        assert _matches_tag_operator("rock", "!=", "rock") is False

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_contains_is_case_insensitive(self) -> None:
        assert _matches_tag_operator("Dream Pop", "CONTAINS", "dream") is True
        assert _matches_tag_operator("Dream Pop", "CONTAINS", "metal") is False

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_notcontains_returns_true_when_value_is_absent(self) -> None:
        assert _matches_tag_operator("Dream Pop", "NOTCONTAINS", "metal") is True
        assert _matches_tag_operator("Dream Pop", "NOTCONTAINS", "dream") is False

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_greater_than_compares_numerically_when_possible(self) -> None:
        assert _matches_tag_operator("10", ">", 2) is True
        assert _matches_tag_operator("2", ">", 10) is False

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_less_than_compares_numerically_when_possible(self) -> None:
        assert _matches_tag_operator("2", "<", 10) is True
        assert _matches_tag_operator("10", "<", 2) is False

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_falls_back_to_string_comparison_for_non_numeric_values(self) -> None:
        assert _matches_tag_operator("beta", ">", "alpha") is True
        assert _matches_tag_operator("alpha", "<", "beta") is True


class TestCandidateFilterValues:
    """Tests for _candidate_filter_values."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_integer_string_generates_string_and_int_candidates(self) -> None:
        assert _candidate_filter_values("1") == ["1", 1]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_float_string_generates_string_and_float_candidates(self) -> None:
        assert _candidate_filter_values("3.14") == ["3.14", 3.14]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_non_numeric_string_returns_only_string_candidate(self) -> None:
        assert _candidate_filter_values("rock") == ["rock"]


class TestFirstAssignmentValue:
    """Tests for _first_assignment_value."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_first_matching_string_value(self) -> None:
        assignments = [
            SongTagAssignment(name="artist", value="First Artist"),
            SongTagAssignment(name="genre", value="Rock"),
            SongTagAssignment(name="artist", value="Second Artist"),
        ]

        result = _first_assignment_value(assignments, "artist")

        assert result == "First Artist"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_string_when_no_match_is_found(self) -> None:
        result = _first_assignment_value([SongTagAssignment(name="genre", value="Rock")], "artist")

        assert result == ""


class TestNumericValue:
    """Tests for _numeric_value."""

    @pytest.mark.unit
    @pytest.mark.mocked
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (7, 7.0),
            (3.5, 3.5),
            (" 42 ", 42.0),
            (True, 1.0),
            (False, 0.0),
        ],
    )
    def test_returns_float_for_numeric_inputs_and_bools(self, value: object, expected: float) -> None:
        assert _numeric_value(value) == expected

    @pytest.mark.unit
    @pytest.mark.mocked
    @pytest.mark.parametrize("value", ["", "abc", None])
    def test_returns_none_for_non_numeric_inputs(self, value: object) -> None:
        assert _numeric_value(value) is None


class TestListTagsByName:
    """Tests for list_tags_by_name."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_page_with_counts_from_aggregate_lookup(self) -> None:
        mock_db = MagicMock()
        mock_db.library.list_tags_with_song_count.return_value = (
            TagUsage(identity=TagRef(name="genre", value="Rock"), song_count=4),
            TagUsage(identity=TagRef(name="genre", value="Jazz"), song_count=2),
        )

        result = list_tags_by_name(mock_db, name="genre", limit=10, offset=0)

        assert result == [
            {"id": "Rock", "name": "genre", "value": "Rock", "song_count": 4},
            {"id": "Jazz", "name": "genre", "value": "Jazz", "song_count": 2},
        ]
        mock_db.library.list_tags_with_song_count.assert_called_once_with(name="genre", search=None, limit=10, offset=0)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_sorts_by_song_count_using_aggregate_lookup(self) -> None:
        mock_db = MagicMock()
        mock_db.library.count_tags_filtered.return_value = 2
        mock_db.library.list_tags_with_song_count.return_value = (
            TagUsage(identity=TagRef(name="genre", value="Rock"), song_count=1),
            TagUsage(identity=TagRef(name="genre", value="Jazz"), song_count=3),
        )

        result = list_tags_by_name(mock_db, name="genre", limit=10, offset=0, sort_by_count=True)

        assert result == [
            {"id": "Jazz", "name": "genre", "value": "Jazz", "song_count": 3},
            {"id": "Rock", "name": "genre", "value": "Rock", "song_count": 1},
        ]
        mock_db.library.count_tags_filtered.assert_called_once_with(name="genre", search=None)
        mock_db.library.list_tags_with_song_count.assert_called_once_with(name="genre", search=None, limit=2, offset=0)


class TestGetTag:
    """Tests for get_tag."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_resolves_tag_identity_and_returns_dict(self) -> None:
        mock_db = MagicMock()
        mock_db.resolve_tag_identity.return_value = TagRef(name="genre", value="rock")

        result = get_tag(mock_db, 5)

        # Ordinary tags normalize to the literal "default" namespace.
        assert result == {"id": 5, "name": "genre", "value": "rock", "namespace": "default"}
        mock_db.resolve_tag_identity.assert_called_once_with(5)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_when_tag_is_not_found(self) -> None:
        mock_db = MagicMock()
        mock_db.resolve_tag_identity.return_value = None

        result = get_tag(mock_db, 99)

        assert result is None
        mock_db.resolve_tag_identity.assert_called_once_with(99)


class TestListSongsForTag:
    """Tests for list_songs_for_tag."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_song_ids_from_domain_songs(self) -> None:
        mock_db = MagicMock()
        rock = TagRef(name="genre", value="Rock")
        mock_db.resolve_tag_identity.return_value = rock
        mock_db.library.find_songs_with_tag.return_value = (_song(song_id=1),)

        result = list_songs_for_tag(mock_db, 1, limit=5, offset=2)

        assert result == [1]
        mock_db.resolve_tag_identity.assert_called_once_with(1)
        mock_db.library.find_songs_with_tag.assert_called_once_with(rock, limit=5, offset=2)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_list_when_no_edges_exist(self) -> None:
        mock_db = MagicMock()
        rock = TagRef(name="genre", value="Rock")
        mock_db.resolve_tag_identity.return_value = rock
        mock_db.library.find_songs_with_tag.return_value = ()

        result = list_songs_for_tag(mock_db, 1)

        assert result == []
        mock_db.resolve_tag_identity.assert_called_once_with(1)
        mock_db.library.find_songs_with_tag.assert_called_once_with(rock, limit=100, offset=0)


class TestCountTagsByName:
    """Tests for count_tags_by_name."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_count_for_name(self) -> None:
        mock_db = MagicMock()
        mock_db.library.count_tags_filtered.return_value = 3

        result = count_tags_by_name(mock_db, name="genre", search=None)

        assert result == 3
        mock_db.library.count_tags_filtered.assert_called_once_with(name="genre", search=None)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_applies_search_filter_when_provided(self) -> None:
        mock_db = MagicMock()
        mock_db.library.count_tags_filtered.return_value = 2

        result = count_tags_by_name(mock_db, name=None, search="pop")

        assert result == 2
        mock_db.library.count_tags_filtered.assert_called_once_with(name=None, search="pop")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_when_no_tags_match_search(self) -> None:
        mock_db = MagicMock()
        mock_db.library.count_tags_filtered.return_value = 0

        result = count_tags_by_name(mock_db, name="genre", search="classical")

        assert result == 0
        mock_db.library.count_tags_filtered.assert_called_once_with(name="genre", search="classical")


class TestGetNomarrTagsBulk:
    """Tests for get_nomarr_tags_bulk."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_dict_for_empty_file_ids(self) -> None:
        mock_db = MagicMock()

        result = get_nomarr_tags_bulk(mock_db, [])

        assert result == {}
        mock_db.library.resolve_song_identities.assert_not_called()
        mock_db.library.list_song_tags_for_songs.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_batches_nomarr_rows_by_file_id(self) -> None:
        mock_db = MagicMock()
        id1 = _song_identity(1)
        id2 = _song_identity(2)
        mock_db.library.resolve_song_identities.return_value = {1: id1, 2: id2}
        mock_db.library.list_song_tags_for_songs.return_value = {
            id1: (
                SongTagAssignment(name="nom:mood", value="calm"),
                SongTagAssignment(name="nom:mood", value="bright"),
            ),
            id2: (SongTagAssignment(name="nom:energy", value=0.91),),
        }

        result = get_nomarr_tags_bulk(mock_db, [1, 2])

        assert result[1].to_dict() == {"nom:mood": ("calm", "bright")}
        assert result[2].to_dict() == {"nom:energy": (0.91,)}
        mock_db.library.resolve_song_identities.assert_called_once_with([1, 2])
        mock_db.library.list_song_tags_for_songs.assert_called_once_with([id1, id2], name_starts_with="nom:")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_preserves_scalar_types_and_required_fields(self) -> None:
        """Bulk conversion keeps scalar value types; persistence-only fields stay out."""
        mock_db = MagicMock()
        id1 = _song_identity(1)
        mock_db.library.resolve_song_identities.return_value = {1: id1}
        mock_db.library.list_song_tags_for_songs.return_value = {
            id1: (
                SongTagAssignment(name="nom:energy", value=0.91, namespace="nom", confidence=0.8, source="ml"),
                SongTagAssignment(name="nom:energy", value=0.91),
                SongTagAssignment(name="nom:year", value=1990),
            ),
        }

        result = get_nomarr_tags_bulk(mock_db, [1])

        assert result[1].to_dict() == {"nom:energy": (0.91,), "nom:year": (1990,)}
        mock_db.library.resolve_song_identities.assert_called_once_with([1])
        mock_db.library.list_song_tags_for_songs.assert_called_once_with([id1], name_starts_with="nom:")


class TestGetDistinctTagValuesForFiles:
    """Tests for get_distinct_tag_values_for_files."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_list_for_empty_file_ids(self) -> None:
        mock_db = MagicMock()

        result = get_distinct_tag_values_for_files(mock_db, [], "genre")

        assert result == []
        mock_db.library.resolve_song_identities.assert_not_called()
        mock_db.library.list_song_tags_for_songs.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_sorted_distinct_string_values(self) -> None:
        mock_db = MagicMock()
        id1 = _song_identity(1)
        id2 = _song_identity(2)
        mock_db.library.resolve_song_identities.return_value = {1: id1, 2: id2}
        mock_db.library.list_song_tags_for_songs.return_value = {
            id1: (
                SongTagAssignment(name="genre", value="Rock"),
                SongTagAssignment(name="genre", value="Pop"),
            ),
            id2: (
                SongTagAssignment(name="genre", value="Rock"),
                SongTagAssignment(name="genre", value="Ambient"),
                SongTagAssignment(name="genre", value=123),
            ),
        }

        result = get_distinct_tag_values_for_files(mock_db, [1, 2], "genre")

        assert result == ["Ambient", "Pop", "Rock"]
        mock_db.library.resolve_song_identities.assert_called_once_with([1, 2])
        mock_db.library.list_song_tags_for_songs.assert_called_once_with([id1, id2])


class TestGetTagValuesGroupedByFile:
    """Tests for get_tag_values_grouped_by_file."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_dict_for_empty_file_ids(self) -> None:
        mock_db = MagicMock()

        result = get_tag_values_grouped_by_file(mock_db, [], "genre")

        assert result == {}
        mock_db.library.resolve_song_identities.assert_not_called()
        mock_db.library.list_song_tags_for_songs.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_groups_matching_values_by_file(self) -> None:
        mock_db = MagicMock()
        id1 = _song_identity(1)
        id2 = _song_identity(2)
        id3 = _song_identity(3)
        mock_db.library.resolve_song_identities.return_value = {1: id1, 2: id2, 3: id3}
        mock_db.library.list_song_tags_for_songs.return_value = {
            id1: (
                SongTagAssignment(name="genre", value="Rock"),
                SongTagAssignment(name="genre", value="Pop"),
            ),
            id2: (SongTagAssignment(name="artist", value="Artist One"),),
            id3: (
                SongTagAssignment(name="genre", value="Jazz"),
                SongTagAssignment(name="genre", value="Jazz"),
            ),
        }

        result = get_tag_values_grouped_by_file(mock_db, [1, 2, 3], "genre")

        assert result == {
            1: {"Rock", "Pop"},
            3: {"Jazz"},
        }
        mock_db.library.resolve_song_identities.assert_called_once_with([1, 2, 3])
        mock_db.library.list_song_tags_for_songs.assert_called_once_with([id1, id2, id3])


class TestGetSongTags:
    """Tests for get_song_tags."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_all_tags_when_no_filters_are_provided(self) -> None:
        mock_db = MagicMock()
        song_identity = _song_identity(1)
        mock_db.library.resolve_song_identity.return_value = song_identity
        mock_db.library.list_tags_for_song.return_value = (
            SongTagAssignment(name="genre", value="Rock"),
            SongTagAssignment(name="artist", value="Artist One"),
        )

        result = get_song_tags(mock_db, 1)

        assert result.to_dict() == {
            "artist": ("Artist One",),
            "genre": ("Rock",),
        }
        mock_db.library.resolve_song_identity.assert_called_once_with(1)
        mock_db.library.list_tags_for_song.assert_called_once_with(song_identity)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_filters_by_name_when_name_is_provided(self) -> None:
        mock_db = MagicMock()
        song_identity = _song_identity(1)
        mock_db.library.resolve_song_identity.return_value = song_identity
        mock_db.library.list_tags_for_song.return_value = (
            SongTagAssignment(name="genre", value="Rock"),
            SongTagAssignment(name="artist", value="Artist One"),
            SongTagAssignment(name="genre", value="Pop"),
        )

        result = get_song_tags(mock_db, 1, name="genre")

        assert result.to_dict() == {"genre": ("Rock", "Pop")}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_filters_to_nomarr_tags_when_nomarr_only_is_true(self) -> None:
        mock_db = MagicMock()
        song_identity = _song_identity(1)
        mock_db.library.resolve_song_identity.return_value = song_identity
        mock_db.library.list_tags_for_song.return_value = (
            SongTagAssignment(name="genre", value="Rock", namespace="default"),
            SongTagAssignment(name="nom:mood-tier-1", value="calm", namespace="nom"),
            SongTagAssignment(name="nom:mood-tier-1", value="bright", namespace="nom"),
        )

        result = get_song_tags(mock_db, 1, nomarr_only=True)

        assert result.to_dict() == {"nom:mood-tier-1": ("calm", "bright")}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_when_no_rows_match(self) -> None:
        """The strict None state represents a song with no matching tags."""
        mock_db = MagicMock()
        song_identity = _song_identity(1)
        mock_db.library.resolve_song_identity.return_value = song_identity
        mock_db.library.list_tags_for_song.return_value = (SongTagAssignment(name="genre", value="Rock"),)

        result = get_song_tags(mock_db, 1, name="artist")

        assert result is None

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_when_no_rows_at_all(self) -> None:
        mock_db = MagicMock()
        song_identity = _song_identity(1)
        mock_db.library.resolve_song_identity.return_value = song_identity
        mock_db.library.list_tags_for_song.return_value = ()

        result = get_song_tags(mock_db, 1)

        assert result is None

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_when_song_identity_not_resolved(self) -> None:
        mock_db = MagicMock()
        mock_db.library.resolve_song_identity.return_value = None

        result = get_song_tags(mock_db, 999)

        assert result is None
        mock_db.library.list_tags_for_song.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_preserves_mixed_scalar_value_types(self) -> None:
        """Mixed value types (str/int/float/bool) survive conversion untouched."""
        mock_db = MagicMock()
        song_identity = _song_identity(1)
        mock_db.library.resolve_song_identity.return_value = song_identity
        mock_db.library.list_tags_for_song.return_value = (
            SongTagAssignment(name="year", value=1990),
            SongTagAssignment(name="rating", value=3.5),
            SongTagAssignment(name="genre", value="Rock"),
            SongTagAssignment(name="is_compilation", value=True),
        )

        result = get_song_tags(mock_db, 1)

        assert result.to_dict() == {
            "genre": ("Rock",),
            "is_compilation": (True,),
            "rating": (3.5,),
            "year": (1990,),
        }

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_merges_duplicate_names_and_dedupes_values(self) -> None:
        """Repeated names collapse into one Tag with duplicate values removed."""
        mock_db = MagicMock()
        song_identity = _song_identity(1)
        mock_db.library.resolve_song_identity.return_value = song_identity
        mock_db.library.list_tags_for_song.return_value = (
            SongTagAssignment(name="genre", value="Rock"),
            SongTagAssignment(name="genre", value="Pop"),
            SongTagAssignment(name="genre", value="Rock"),
        )

        result = get_song_tags(mock_db, 1)

        assert result.to_dict() == {"genre": ("Rock", "Pop")}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_preserves_name_value_and_not_persistence_only_fields(self) -> None:
        """Public name/value carry through; source/confidence/namespace do not leak."""
        mock_db = MagicMock()
        song_identity = _song_identity(1)
        mock_db.library.resolve_song_identity.return_value = song_identity
        mock_db.library.list_tags_for_song.return_value = (
            SongTagAssignment(name="nom:mood", value="calm", namespace="nom", confidence=0.9, source="ml"),
            SongTagAssignment(name="genre", value="Rock"),
        )

        result = get_song_tags(mock_db, 1)

        assert result.to_dict() == {"genre": ("Rock",), "nom:mood": ("calm",)}


class TestGetFileIdsMatchingTag:
    """Tests for get_file_ids_matching_tag - verifies domain tags/songs matching."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_uses_domain_tags_and_songs_for_file_lookup(self) -> None:
        """Matching domain tag identities drive per-identity song lookups."""
        mock_db = MagicMock()
        rock = TagRef(name="genre", value="Rock")
        jazz = TagRef(name="genre", value="Jazz")
        mock_db.library.list_tags.return_value = (rock, jazz)
        mock_db.library.find_songs_with_tag.side_effect = [
            (_song(song_id=1), _song(song_id=3)),
            (_song(song_id=2),),
        ]

        result = get_file_ids_matching_tag(mock_db, "genre", "==", "Rock")

        assert result == {1, 3}
        mock_db.library.list_tags.assert_called_once_with(name="genre", limit=None)
        mock_db.library.find_songs_with_tag.assert_called_once_with(rock, limit=None)


class TestGetFileIdsForMoodTags:
    """Tests for get_file_ids_for_mood_tags."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_uses_contains_matching_for_mood_tags(self) -> None:
        """Mood tags are stored as arrays, so we need CONTAINS matching."""
        mock_db = MagicMock()
        # Simulate files with mood arrays
        mock_db.library.find_songs_with_tag_contains.side_effect = [
            # Files with "aggressive" in their mood array
            (_song(song_id=1), _song(song_id=2)),
            # Files with "happy" in their mood array
            (_song(song_id=2), _song(song_id=3)),
        ]

        result = get_file_ids_for_mood_tags(
            mock_db,
            mood_values=["aggressive", "happy"],
            mood_tier="mood-strict",
        )

        assert result == {
            "aggressive": {1, 2},
            "happy": {2, 3},
        }
        # Verify CONTAINS method was called (not exact match) with domain identities
        assert mock_db.library.find_songs_with_tag_contains.call_count == 2
        mock_db.library.find_songs_with_tag_contains.assert_any_call(
            TagRef(name="nom:mood-strict", value="aggressive", namespace="nom"),
            limit=None,
        )
        mock_db.library.find_songs_with_tag_contains.assert_any_call(
            TagRef(name="nom:mood-strict", value="happy", namespace="nom"),
            limit=None,
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_scopes_to_library_when_provided(self) -> None:
        """A library should restrict results to files in that library."""
        library = Library(name="Music", root_path="/music")
        mock_db = MagicMock()
        mock_db.library.list_songs.return_value = (_song(song_id=1), _song(song_id=2))
        mock_db.library.find_songs_with_tag_contains.return_value = (
            _song(song_id=1),
            _song(song_id=2),
            _song(song_id=3),  # Not in library
        )

        result = get_file_ids_for_mood_tags(
            mock_db,
            mood_values=["aggressive"],
            mood_tier="mood-strict",
            library=library,
        )

        # Should only include files 1 and 2 (file 3 is not in the library)
        assert result == {"aggressive": {1, 2}}
        mock_db.library.list_songs.assert_called_once_with(library, limit=None)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_handles_empty_results(self) -> None:
        """Empty results should return empty sets."""
        mock_db = MagicMock()
        mock_db.library.find_songs_with_tag_contains.return_value = ()

        result = get_file_ids_for_mood_tags(
            mock_db,
            mood_values=["nonexistent"],
            mood_tier="mood-strict",
        )

        assert result == {"nonexistent": set()}
