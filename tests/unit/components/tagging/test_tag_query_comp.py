"""Tests for nomarr.components.tagging.tag_query_comp module.

Q3-H rewrite: asserts the locator-keyed domain-facing API. All reads route
through the sealed ``LibraryTagsDb`` facade using ``TagRef`` /
``SongIdentity`` and typed results (``SongTagAssignment`` / ``Song`` /
``TagUsage``); bare ``Song`` results are projected to UUID-bearing
``SongIdentity`` locators via the Q3-C public carrier projection
(``locators_for_carriers``). No generated id, row, resolver, or path heuristic
participates in the analytics helpers.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest

from nomarr.components.tagging.tag_query_comp import (
    _candidate_filter_values,
    _first_assignment_value,
    _matches_tag_operator,
    _numeric_value,
    _project_song_locators,
    assignments_to_tags,
    count_songs_for_tag,
    count_tags_by_name,
    get_distinct_tag_values_for_files,
    get_file_ids_for_mood_tags,
    get_file_ids_for_tags,
    get_file_ids_matching_tag,
    get_tag,
    get_tag_songs_with_metadata,
    get_tag_values_grouped_by_file,
    list_songs_for_tag,
    list_tags_by_name,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_tag_dataclass import SongTagAssignment, TagRef, TagUsage
from nomarr.helpers.song_locator_codec import encode_song_locator

# Canonical lowercase version-4 UUID accepted by the opaque ``nom1`` codec.
_LIBRARY_UUID = "6313b0d3-d270-4a8e-9e0d-21e8255107e3"
_LIBRARY = Library(name="Music", root_path="/music", library_uuid=_LIBRARY_UUID)
_LIBRARY_IDENTITY = LibraryIdentity(library_uuid=_LIBRARY_UUID, name="Music", root_path="/music")


def _song(**overrides: object) -> Song:
    base: dict = {
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


def _locator(normalized_path: str, library: Library | None = None) -> SongIdentity:
    """Build the ``SongIdentity`` a resolved song projects to."""
    selected = library or _LIBRARY
    return SongIdentity(
        library=LibraryIdentity(
            library_uuid=selected.library_uuid,
            name=selected.name,
            root_path=selected.root_path,
        ),
        normalized_path=normalized_path,
    )


def _wire_projection(db: MagicMock, pairs: list[tuple[Library, list[Song]]]) -> None:
    """Wire the Q3-C carrier projection facades for the given library/song pairs."""
    db.library.list_libraries.return_value = [library for library, _ in pairs]

    def _resolve(requested: list[SongIdentity]) -> list[Song]:
        resolved: list[Song] = []
        for library, songs in pairs:
            by_path = {song.normalized_path: song for song in songs}
            resolved.extend(
                by_path[identity.normalized_path]
                for identity in requested
                if identity.library.library_uuid == library.library_uuid and identity.normalized_path in by_path
            )
        return resolved

    db.library.list_songs_by_identity.side_effect = _resolve


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


class TestAssignmentsToTags:
    """Tests for the public ``assignments_to_tags`` projection."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_merges_duplicate_names_and_preserves_order(self) -> None:
        assignments = [
            SongTagAssignment(name="genre", value="Rock"),
            SongTagAssignment(name="genre", value="Pop"),
            SongTagAssignment(name="artist", value="A"),
        ]

        tags = assignments_to_tags(assignments)

        assert tags.to_dict() == {"artist": ("A",), "genre": ("Rock", "Pop")}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_empty_input_raises_canonical_value_error(self) -> None:
        with pytest.raises(ValueError):
            assignments_to_tags([])


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
            {"id": "Rock", "name": "genre", "value": "Rock", "namespace": "default", "song_count": 4},
            {"id": "Jazz", "name": "genre", "value": "Jazz", "namespace": "default", "song_count": 2},
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
            {"id": "Jazz", "name": "genre", "value": "Jazz", "namespace": "default", "song_count": 3},
            {"id": "Rock", "name": "genre", "value": "Rock", "namespace": "default", "song_count": 1},
        ]
        mock_db.library.count_tags_filtered.assert_called_once_with(name="genre", search=None)
        mock_db.library.list_tags_with_song_count.assert_called_once_with(name="genre", search=None, limit=2, offset=0)


class TestGetTag:
    """Tests for get_tag."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_resolves_natural_identity_and_returns_dict(self) -> None:
        mock_db = MagicMock()
        rock = TagRef(name="genre", value="rock")
        mock_db.library.get_tag.return_value = rock

        result = get_tag(mock_db, rock)

        # Ordinary tags normalize to the literal "default" namespace. ``id``
        # mirrors the listing projection (natural value), never a storage PK.
        assert result == {"id": "rock", "name": "genre", "value": "rock", "namespace": "default"}
        mock_db.library.get_tag.assert_called_once_with(rock)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_when_natural_identity_is_not_found(self) -> None:
        mock_db = MagicMock()
        rock = TagRef(name="genre", value="rock")
        mock_db.library.get_tag.return_value = None

        result = get_tag(mock_db, rock)

        assert result is None
        mock_db.library.get_tag.assert_called_once_with(rock)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_does_not_parse_numeric_looking_string_value_as_pk(self) -> None:
        """The natural value "120" is data routed by natural key, never a storage id."""
        mock_db = MagicMock()
        bpm = TagRef(name="bpm", value="120")
        mock_db.library.get_tag.return_value = bpm

        result = get_tag(mock_db, bpm)

        assert result == {"id": "120", "name": "bpm", "value": "120", "namespace": "default"}
        mock_db.library.get_tag.assert_called_once_with(TagRef(name="bpm", value="120"))


class TestCountSongsForTag:
    """Tests for count_songs_for_tag."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_counts_songs_via_natural_identity_lookup(self) -> None:
        mock_db = MagicMock()
        electronic = TagRef(name="genre", value="Electronic")
        mock_db.library.find_songs_with_tag.return_value = (_song(), _song())

        result = count_songs_for_tag(mock_db, electronic)

        assert result == 2
        mock_db.library.find_songs_with_tag.assert_called_once_with(electronic, limit=None)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_when_natural_identity_has_no_edges(self) -> None:
        mock_db = MagicMock()
        mock_db.library.find_songs_with_tag.return_value = ()

        result = count_songs_for_tag(mock_db, TagRef(name="genre", value="Electronic"))

        assert result == 0
        mock_db.library.find_songs_with_tag.assert_called_once_with(
            TagRef(name="genre", value="Electronic"), limit=None
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_string_120_value_routed_as_natural_value_not_storage_pk(self) -> None:
        """A numeric-looking natural value "120" is forwarded verbatim as the value.

        The component never converts ``120`` into a storage tag primary key; only the
        exact natural key drives selection.
        """
        mock_db = MagicMock()
        string_120 = TagRef(name="bpm", value="120")
        int_120 = TagRef(name="bpm", value=120)
        mock_db.library.find_songs_with_tag.return_value = (_song(),)

        result = count_songs_for_tag(mock_db, string_120)

        assert result == 1
        # The string and int natural values are DISTINCT natural identities;
        # each is looked up only by its own exact natural key.
        mock_db.library.find_songs_with_tag.assert_called_once_with(string_120, limit=None)
        assert string_120 != int_120

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_preserves_namespace_separation(self) -> None:
        """nom vs default namespaces route through distinct natural identities."""
        mock_db = MagicMock()
        mock_db.library.find_songs_with_tag.return_value = (_song(),)
        nom = TagRef(name="nom:mood-tier-1", value="calm", namespace="nom")
        ordinary = TagRef(name="mood-tier-1", value="calm")

        assert count_songs_for_tag(mock_db, nom) == 1
        assert count_songs_for_tag(mock_db, ordinary) == 1

        assert mock_db.library.find_songs_with_tag.call_args_list == [
            ((nom,), {"limit": None}),
            ((ordinary,), {"limit": None}),
        ]


class TestListSongsForTag:
    """Tests for list_songs_for_tag."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_song_locators_from_domain_songs(self) -> None:
        mock_db = MagicMock()
        electronic = TagRef(name="genre", value="Electronic")
        song = _song(normalized_path="a.mp3")
        mock_db.library.find_songs_with_tag.return_value = (song,)
        _wire_projection(mock_db, [(_LIBRARY, [song])])

        result = list_songs_for_tag(mock_db, electronic, limit=5, offset=2)

        assert result == [_locator("a.mp3")]
        mock_db.library.find_songs_with_tag.assert_called_once_with(electronic, limit=5, offset=2)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_list_when_no_edges_exist(self) -> None:
        mock_db = MagicMock()
        mock_db.library.find_songs_with_tag.return_value = ()

        result = list_songs_for_tag(mock_db, TagRef(name="genre", value="Electronic"))

        assert result == []
        mock_db.library.find_songs_with_tag.assert_called_once_with(
            TagRef(name="genre", value="Electronic"), limit=100, offset=0
        )
        mock_db.library.list_libraries.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_listing_to_lookup_continuity_uses_same_natural_identity(self) -> None:
        """A listed natural identity drives the song lookup unchanged."""
        mock_db = MagicMock()
        usage_identity = TagRef(name="genre", value="Electronic")
        first = _song(normalized_path="a.mp3")
        second = _song(normalized_path="b.mp3")
        mock_db.library.find_songs_with_tag.return_value = (first, second)
        _wire_projection(mock_db, [(_LIBRARY, [first, second])])

        result = list_songs_for_tag(mock_db, usage_identity, limit=50, offset=0)

        assert result == [_locator("a.mp3"), _locator("b.mp3")]
        mock_db.library.find_songs_with_tag.assert_called_once_with(usage_identity, limit=50, offset=0)


class TestGetTagSongsWithMetadata:
    """Tests for get_tag_songs_with_metadata."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_tag_song_items_with_opaque_locator_file_id(self) -> None:
        mock_db = MagicMock()
        electronic = TagRef(name="genre", value="Electronic")
        song = _song()
        mock_db.library.find_songs_with_tag.return_value = (song,)
        _wire_projection(mock_db, [(_LIBRARY, [song])])
        mock_db.library.get_song.return_value = song
        mock_db.library.list_tags_for_song.return_value = (
            SongTagAssignment(name="title", value="Neon"),
            SongTagAssignment(name="artist", value="Synthwave Artist"),
            SongTagAssignment(name="album", value="Retro"),
        )

        result = get_tag_songs_with_metadata(mock_db, electronic, limit=5, offset=2)

        assert len(result) == 1
        assert result[0]["file_id"] == encode_song_locator(_locator("song.mp3"))
        assert result[0]["file_id"].startswith("nom1")
        assert result[0]["title"] == "Neon"
        assert result[0]["artist"] == "Synthwave Artist"
        assert result[0]["album"] == "Retro"
        assert result[0]["path"] == "/music/song.mp3"
        mock_db.library.find_songs_with_tag.assert_called_once_with(electronic, limit=5, offset=2)
        mock_db.library.get_song.assert_called_once_with(_locator("song.mp3"))
        mock_db.library.list_tags_for_song.assert_called_once_with(_locator("song.mp3"))

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_when_natural_identity_has_no_songs(self) -> None:
        mock_db = MagicMock()
        mock_db.library.find_songs_with_tag.return_value = ()

        result = get_tag_songs_with_metadata(mock_db, TagRef(name="genre", value="Electronic"))

        assert result == []
        mock_db.library.get_song.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_skips_song_whose_locator_projection_is_none(self) -> None:
        """An unresolved song projects to no locator, so its row is skipped."""
        mock_db = MagicMock()
        electronic = TagRef(name="genre", value="Electronic")
        resolvable = _song(normalized_path="a.mp3")
        unresolved = _song(normalized_path="z.mp3")
        mock_db.library.find_songs_with_tag.return_value = (resolvable, unresolved)
        # Only the resolvable song is registered in the library projection; the
        # unresolved song yields ``None`` from ``locators_for_carriers``.
        _wire_projection(mock_db, [(_LIBRARY, [resolvable])])
        mock_db.library.get_song.return_value = resolvable
        mock_db.library.list_tags_for_song.return_value = (SongTagAssignment(name="title", value="Neon"),)

        result = get_tag_songs_with_metadata(mock_db, electronic)

        assert len(result) == 1
        assert result[0]["file_id"] == encode_song_locator(_locator("a.mp3"))
        assert result[0]["file_id"].startswith("nom1")
        assert result[0]["title"] == "Neon"
        mock_db.library.get_song.assert_called_once_with(_locator("a.mp3"))
        mock_db.library.list_tags_for_song.assert_called_once_with(_locator("a.mp3"))


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


class TestGetDistinctTagValuesForFiles:
    """Tests for get_distinct_tag_values_for_files (locator-keyed)."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_list_for_empty_locators(self) -> None:
        mock_db = MagicMock()

        result = get_distinct_tag_values_for_files(mock_db, [], "genre")

        assert result == []
        mock_db.library.list_song_tags_for_songs.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_sorted_distinct_string_values(self) -> None:
        mock_db = MagicMock()
        id1 = _locator("song1.mp3")
        id2 = _locator("song2.mp3")
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

        result = get_distinct_tag_values_for_files(mock_db, [id1, id2], "genre")

        assert result == ["Ambient", "Pop", "Rock"]
        mock_db.library.list_song_tags_for_songs.assert_called_once_with([id1, id2])


class TestGetTagValuesGroupedByFile:
    """Tests for get_tag_values_grouped_by_file (locator-keyed)."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_dict_for_empty_locators(self) -> None:
        mock_db = MagicMock()

        result = get_tag_values_grouped_by_file(mock_db, [], "genre")

        assert result == {}
        mock_db.library.list_song_tags_for_songs.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_groups_matching_values_by_locator(self) -> None:
        mock_db = MagicMock()
        id1 = _locator("song1.mp3")
        id2 = _locator("song2.mp3")
        id3 = _locator("song3.mp3")
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

        result = get_tag_values_grouped_by_file(mock_db, [id1, id2, id3], "genre")

        assert result == {
            id1: {"Rock", "Pop"},
            id3: {"Jazz"},
        }
        mock_db.library.list_song_tags_for_songs.assert_called_once_with([id1, id2, id3])


class TestGetFileIdsMatchingTag:
    """Tests for get_file_ids_matching_tag - locator projection."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_uses_domain_tags_and_songs_for_locator_lookup(self) -> None:
        """Matching domain tag identities drive per-identity song lookups."""
        mock_db = MagicMock()
        rock = TagRef(name="genre", value="Rock")
        jazz = TagRef(name="genre", value="Jazz")
        mock_db.library.list_tags.return_value = (rock, jazz)
        first = _song(normalized_path="a.mp3")
        second = _song(normalized_path="b.mp3")
        third = _song(normalized_path="c.mp3")
        mock_db.library.find_songs_with_tag.side_effect = [
            (first, third),
            (second,),
        ]
        _wire_projection(mock_db, [(_LIBRARY, [first, second, third])])

        result = get_file_ids_matching_tag(mock_db, "genre", "==", "Rock")

        assert result == {_locator("a.mp3"), _locator("c.mp3")}
        mock_db.library.list_tags.assert_called_once_with(name="genre", limit=None)
        mock_db.library.find_songs_with_tag.assert_called_once_with(rock, limit=None)


class TestGetFileIdsForTags:
    """Tests for get_file_ids_for_tags (locator-keyed, library-scoped by uuid)."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_locator_sets_per_spec(self) -> None:
        mock_db = MagicMock()
        rock = TagRef(name="genre", value="Rock")
        first = _song(normalized_path="a.mp3")
        second = _song(normalized_path="b.mp3")
        mock_db.library.list_tags.return_value = (rock,)
        mock_db.library.find_songs_with_tag.return_value = (first, second)
        _wire_projection(mock_db, [(_LIBRARY, [first, second])])

        result = get_file_ids_for_tags(mock_db, [("genre", "Rock")])

        assert result == {("genre", "Rock"): {_locator("a.mp3"), _locator("b.mp3")}}
        mock_db.library.list_tags.assert_called_once_with(name="genre", limit=None)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_scopes_locators_to_library_uuid(self) -> None:
        """Library scope filters projected locators on the owning library uuid."""
        mock_db = MagicMock()
        other_library = Library(name="Other", root_path="/other", library_uuid="aaaaaaaa-1111-4bbb-8ccc-222222222222")
        in_library = _song(normalized_path="a.mp3")
        out_of_library = _song(normalized_path="z.mp3")
        mock_db.library.list_tags.return_value = (TagRef(name="genre", value="Rock"),)
        mock_db.library.find_songs_with_tag.return_value = (in_library, out_of_library)
        _wire_projection(mock_db, [(_LIBRARY, [in_library]), (other_library, [out_of_library])])

        result = get_file_ids_for_tags(mock_db, [("genre", "Rock")], library=_LIBRARY)

        assert result == {("genre", "Rock"): {_locator("a.mp3")}}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_wildcard_value_matches_all_tags_for_the_name(self) -> None:
        """``*`` bypasses value filtering and unions every matching tag's songs."""
        mock_db = MagicMock()
        rock = TagRef(name="genre", value="Rock")
        jazz = TagRef(name="genre", value="Jazz")
        first = _song(normalized_path="a.mp3")
        second = _song(normalized_path="b.mp3")
        mock_db.library.list_tags.return_value = (rock, jazz)
        mock_db.library.find_songs_with_tag.side_effect = [(first,), (second,)]
        _wire_projection(mock_db, [(_LIBRARY, [first, second])])

        result = get_file_ids_for_tags(mock_db, [("genre", "*")])

        assert result == {("genre", "*"): {_locator("a.mp3"), _locator("b.mp3")}}
        mock_db.library.list_tags.assert_called_once_with(name="genre", limit=None)


class TestGetFileIdsForMoodTags:
    """Tests for get_file_ids_for_mood_tags (locator-keyed, CONTAINS matching)."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_uses_contains_matching_for_mood_tags(self) -> None:
        """Mood tags are stored as arrays, so we need CONTAINS matching."""
        mock_db = MagicMock()
        first = _song(normalized_path="a.mp3")
        second = _song(normalized_path="b.mp3")
        third = _song(normalized_path="c.mp3")
        mock_db.library.find_songs_with_tag_contains.side_effect = [
            (first, second),
            (second, third),
        ]
        _wire_projection(mock_db, [(_LIBRARY, [first, second, third])])

        result = get_file_ids_for_mood_tags(
            mock_db,
            mood_values=["aggressive", "happy"],
            mood_tier="mood-strict",
        )

        assert result == {
            "aggressive": {_locator("a.mp3"), _locator("b.mp3")},
            "happy": {_locator("b.mp3"), _locator("c.mp3")},
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
        """A library should restrict results to locators owned by that library."""
        other_library = Library(name="Other", root_path="/other", library_uuid="aaaaaaaa-1111-4bbb-8ccc-222222222222")
        mock_db = MagicMock()
        in_library = _song(normalized_path="a.mp3")
        out_of_library = _song(normalized_path="z.mp3")
        mock_db.library.find_songs_with_tag_contains.return_value = (in_library, out_of_library)
        _wire_projection(mock_db, [(_LIBRARY, [in_library]), (other_library, [out_of_library])])

        result = get_file_ids_for_mood_tags(
            mock_db,
            mood_values=["aggressive"],
            mood_tier="mood-strict",
            library=_LIBRARY,
        )

        assert result == {"aggressive": {_locator("a.mp3")}}

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

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_already_namespaced_mood_tier_is_not_double_prefixed(self) -> None:
        """A tier that is already ``nom:``-prefixed is forwarded unchanged."""
        mock_db = MagicMock()
        song = _song(normalized_path="a.mp3")
        mock_db.library.find_songs_with_tag_contains.return_value = (song,)
        _wire_projection(mock_db, [(_LIBRARY, [song])])

        result = get_file_ids_for_mood_tags(
            mock_db,
            mood_values=["aggressive"],
            mood_tier="nom:mood-strict",
        )

        assert result == {"aggressive": {_locator("a.mp3")}}
        mock_db.library.find_songs_with_tag_contains.assert_called_once_with(
            TagRef(name="nom:mood-strict", value="aggressive", namespace="nom"),
            limit=None,
        )


class TestNoGeneratedIdProjection:
    """Negative proof: the analytics helpers never derive a generated id."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_song_carries_no_generated_id(self) -> None:
        assert not hasattr(Song, "song_id")
        assert not hasattr(Song, "library_id")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_owned_helpers_have_no_generated_id_or_resolver(self) -> None:
        owned = (
            _project_song_locators,
            assignments_to_tags,
            list_songs_for_tag,
            get_file_ids_matching_tag,
            get_file_ids_for_tags,
            get_file_ids_for_mood_tags,
            get_distinct_tag_values_for_files,
            get_tag_values_grouped_by_file,
            get_tag_songs_with_metadata,
        )
        forbidden = (
            ".song_id",
            ".to_dict(",
            "from_row",
            "resolve_song_identity",
            "resolve_song_identities",
            "require_library_song_id",
            "_locators_for_songs(",
        )
        for func in owned:
            source = inspect.getsource(func)
            for token in forbidden:
                assert token not in source, f"{func.__name__} contains forbidden token {token!r}"
