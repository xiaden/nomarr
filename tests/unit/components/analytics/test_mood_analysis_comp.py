"""Tests for ``nomarr.components.analytics.mood_analysis_comp``."""

from __future__ import annotations

import ast
from inspect import getsource
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.analytics.mood_analysis_comp import (
    _get_tag_edge_rows,
    _get_top_mood_pairs,
    compute_mood_analysis,
    get_mood_and_tier_tags_for_correlation,
    get_mood_balance,
    get_mood_coverage,
    get_mood_distribution_data,
)
from nomarr.components.library.library_song_query_comp import locators_for_carriers
from nomarr.components.library.song_query_types import TrackSong
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.song_tag_dataclass import TagRef

_UUID = "123e4567-e89b-42d3-a456-426614174000"


def _locator(path: str) -> SongIdentity:
    return SongIdentity(library=LibraryIdentity(library_uuid=_UUID), normalized_path=path)


def _row(path: str, value: str) -> tuple[SongIdentity, str]:
    return (_locator(path), value)


def _song(song_id: int, **overrides: object) -> Song:
    base: dict = {
        "path": f"/music/{song_id}.mp3",
        "normalized_path": f"{song_id}.mp3",
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


def _identity(name: str, value: str | int | float | bool) -> TagRef:
    """Build a domain ``TagRef`` for the sealed tag facade."""
    return TagRef(name=name, value=value)


class TestGetTopMoodPairs:
    @pytest.mark.unit
    @pytest.mark.mocked
    @pytest.mark.parametrize(
        ("tier", "expected_names", "expected_pairs"),
        [
            (
                "strict",
                ["nom:mood-strict"],
                [("bright", "calm", 1)],
            ),
            (
                "regular",
                ["nom:mood-strict", "nom:mood-regular"],
                [("bright", "calm", 1), ("bright", "warm", 1)],
            ),
            (
                "loose",
                ["nom:mood-strict", "nom:mood-regular", "nom:mood-loose"],
                [("bright", "calm", 2), ("bright", "warm", 1)],
            ),
        ],
    )
    def test_hierarchy_grouping_duplicate_suppression_and_library_forwarding(
        self, tier: str, expected_names: list[str], expected_pairs: list[tuple[str, str, int]]
    ) -> None:
        library = Library(name="main", root_path="/music", library_uuid=_UUID)
        rows = {
            "nom:mood-strict": [_row("same.mp3", "calm"), _row("same.mp3", "calm"), _row("same.mp3", "bright")],
            "nom:mood-regular": [_row("same.mp3", "warm"), _row("other.mp3", "bright")],
            "nom:mood-loose": [_row("other.mp3", "calm"), _row("third.mp3", "zest")],
        }
        db = MagicMock()
        with patch(
            "nomarr.components.analytics.mood_analysis_comp._get_tag_edge_rows",
            side_effect=lambda _db, name, _library: rows[name],
        ) as query:
            result = _get_top_mood_pairs(db, library, tier, limit=2)

        assert query.call_count == len(expected_names)
        assert [call.args[1] for call in query.call_args_list] == expected_names
        assert all(call.args[2] is library for call in query.call_args_list)
        assert result == [{"mood1": mood1, "mood2": mood2, "count": count} for mood1, mood2, count in expected_pairs]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_pairs_are_deterministic_and_limit_is_respected(self) -> None:
        db = MagicMock()
        rows = [_row("one.mp3", "zeta"), _row("one.mp3", "alpha"), _row("one.mp3", "mid")]
        with patch("nomarr.components.analytics.mood_analysis_comp._get_tag_edge_rows", return_value=rows):
            assert _get_top_mood_pairs(db, None, "strict", limit=1) == [{"mood1": "alpha", "mood2": "mid", "count": 1}]


class TestComputeMoodAnalysis:
    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_four_sections_calls_pairs_at_fifty_and_derives_vibes(self) -> None:
        db = MagicMock()
        library = Library(name="main", root_path="/music", library_uuid=_UUID)
        coverage = {"total_files": 3, "tiers": {}}
        balance = {"strict": [{"mood": "calm", "count": 2}], "regular": [], "loose": []}
        pairs = {"strict": [{"mood1": "calm", "mood2": "warm", "count": 2}], "regular": [], "loose": []}
        with (
            patch(
                "nomarr.components.analytics.mood_analysis_comp.get_mood_coverage", return_value=coverage
            ) as coverage_mock,
            patch(
                "nomarr.components.analytics.mood_analysis_comp.get_mood_balance", return_value=balance
            ) as balance_mock,
            patch(
                "nomarr.components.analytics.mood_analysis_comp._get_top_mood_pairs",
                side_effect=lambda _db, _library, *, mood_tier, limit: pairs[mood_tier] if limit == 50 else [],
            ) as pairs_mock,
            patch(
                "nomarr.components.analytics.mood_analysis_comp.compute_dominant_vibes",
                return_value=[{"mood": "calm", "percentage": 100.0}],
            ) as vibes_mock,
        ):
            result = compute_mood_analysis(db, library)

        assert result == {
            "coverage": coverage,
            "balance": balance,
            "top_pairs_by_tier": pairs,
            "dominant_vibes": [{"mood": "calm", "percentage": 100.0}],
        }
        coverage_mock.assert_called_once_with(db, library)
        balance_mock.assert_called_once_with(db, library)
        assert [call.kwargs for call in pairs_mock.call_args_list] == [
            {"mood_tier": "strict", "limit": 50},
            {"mood_tier": "regular", "limit": 50},
            {"mood_tier": "loose", "limit": 50},
        ]
        assert all(call.args[1] is library for call in pairs_mock.call_args_list)
        vibes_mock.assert_called_once_with(balance)


@pytest.mark.unit
@pytest.mark.mocked
def test_mood_analysis_isolates_colliding_paths_by_library_uuid() -> None:
    other_uuid = "223e4567-e89b-42d3-a456-426614174000"
    requested = Library(name="requested", root_path="/one", library_uuid=_UUID)
    other = Library(name="other", root_path="/two", library_uuid=other_uuid)
    requested_locator = SongIdentity(LibraryIdentity(library_uuid=_UUID), "same.mp3")
    other_locator = SongIdentity(LibraryIdentity(library_uuid=other_uuid), "same.mp3")
    db = MagicMock()
    db.library.list_libraries.return_value = [requested, other]
    tag_values = {
        "nom:mood-strict": ("calm", "foreign-strict"),
        "nom:mood-regular": ("warm", "foreign-regular"),
        "nom:mood-loose": ("vivid", "foreign-loose"),
    }

    def list_tags(*, name: str, limit: int, offset: int) -> list[TagRef]:
        del limit
        return [TagRef(name=name, value=value) for value in tag_values[name]] if offset == 0 else []

    db.library.list_tags.side_effect = list_tags
    requested_song = _song(1, normalized_path="same.mp3", file_size=101)
    foreign_song = _song(2, normalized_path="same.mp3", file_size=202)

    def find_songs_with_tag(tag: TagRef, *, limit: int) -> tuple[Song, ...]:
        del limit
        return (foreign_song,) if str(tag.value).startswith("foreign") else (requested_song,)

    db.library.find_songs_with_tag.side_effect = find_songs_with_tag
    db.library.list_songs_by_identity.side_effect = lambda identities: [
        requested_song if identity.library.library_uuid == _UUID else foreign_song
        for identity in identities
        if identity.library.library_uuid in (_UUID, other_uuid)
    ]
    with patch("nomarr.components.analytics.mood_analysis_comp.get_library_stats", return_value={"total_files": 2}):
        analysis = compute_mood_analysis(db, requested)

    assert requested_locator != other_locator
    assert analysis == {
        "coverage": {
            "total_files": 2,
            "tiers": {
                "strict": {"tagged": 1, "percentage": 50.0},
                "regular": {"tagged": 1, "percentage": 50.0},
                "loose": {"tagged": 1, "percentage": 50.0},
            },
        },
        "balance": {
            "strict": [{"mood": "calm", "count": 1}],
            "regular": [{"mood": "warm", "count": 1}],
            "loose": [{"mood": "vivid", "count": 1}],
        },
        "top_pairs_by_tier": {
            "strict": [],
            "regular": [{"mood1": "calm", "mood2": "warm", "count": 1}],
            "loose": [
                {"mood1": "calm", "mood2": "vivid", "count": 1},
                {"mood1": "calm", "mood2": "warm", "count": 1},
                {"mood1": "vivid", "mood2": "warm", "count": 1},
            ],
        },
        "dominant_vibes": [
            {"mood": "calm", "percentage": 33.3},
            {"mood": "warm", "percentage": 33.3},
            {"mood": "vivid", "percentage": 33.3},
        ],
    }
    assert all(
        foreign not in str(analysis) for foreign in (other_uuid, "foreign-strict", "foreign-regular", "foreign-loose")
    )


def _executable_source_tokens(source: str) -> set[str]:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body.pop(0)
    tokens: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            tokens.add(node.id)
        elif isinstance(node, ast.Attribute):
            tokens.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            tokens.add(node.value)
    return tokens


@pytest.mark.unit
def test_analytics_source_uses_tagref_and_public_semantic_projection_only() -> None:
    source = getsource(__import__("nomarr.components.analytics.mood_analysis_comp", fromlist=["_get_tag_edge_rows"]))
    tokens = _executable_source_tokens(source)
    assert "TagRef" in tokens and "locators_for_carriers" in tokens and "TrackSong" in tokens
    for forbidden in (
        # Persistence rows, generated/integer identity, and resolver surfaces.
        "SongRow",
        "row_to_domain",
        "raw_row",
        "persistence_row",
        "SongUpsert",
        "SongUpsertInput",
        "song_id",
        "file_id",
        "generated_id",
        "integer_identity",
        "resolver",
        "shim",
        "alias",
        "dual_path",
        "transaction",
        "library_id",
        "folder_id",
        "songs.id",
        "storage_id",
        "integer_id",
        "resolve_song_identity",
        "resolve_song_identities",
        "get_song_by_id",
        "require_library_song_id",
        "list_all_song_ids",
        "get_songs_by_ids_with_tags",
        # Resolver, adapter, shim, alias, and dual-path ownership.
        "integer_adapter",
        "integer_fallback",
        "resolver_shim",
        "compatibility_shim",
        "legacy_alias",
        "dual_path",
        "dual-path",
        # Caller-managed transaction ownership.
        "sessionmaker",
        "begin_nested",
        "begin_transaction",
        "caller_transaction",
        "caller-managed transaction",
        # External ML and tag-repository/mood persistence ownership.
        "MlDb",
        "ml_inference",
        "replace_song_inference_results",
        "persist_backbone_vector",
        "OutputStreamWrite",
        "TagRepository",
        "SongTagRepository",
        "LibraryTagsDb",
        "tag_repo",
        "replace_song_tags",
        "save_mood_tags",
        "replace_mood_tags",
        "replace_mood_tags_batch",
        "MoodReplacementCommand",
        "CalibrationMoodMarker",
        "_commit_mood_batch",
        "mood_tags_to_assignments",
    ):
        assert all(forbidden not in token for token in tokens)


class TestGetMoodCoverage:
    """Tests for ``get_mood_coverage``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_coverage_when_no_files(self) -> None:
        """Zero files should produce zero coverage for every tier."""
        mock_db = MagicMock()

        with patch(
            "nomarr.components.analytics.mood_analysis_comp.get_library_stats",
            return_value={"total_files": 0},
        ) as get_library_stats_mock:
            result = get_mood_coverage(mock_db)

        assert result == {
            "total_files": 0,
            "tiers": {
                "strict": {"tagged": 0, "percentage": 0.0},
                "regular": {"tagged": 0, "percentage": 0.0},
                "loose": {"tagged": 0, "percentage": 0.0},
            },
        }
        get_library_stats_mock.assert_called_once_with(mock_db, None)
        mock_db.library.list_tags.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_percentage_for_each_tier(self) -> None:
        """Tier counts should be converted into rounded percentages."""
        mock_db = MagicMock()
        with (
            patch(
                "nomarr.components.analytics.mood_analysis_comp._get_tag_edge_rows",
                side_effect=[
                    [_row("1.mp3", "happy"), _row("2.mp3", "calm"), _row("1.mp3", "happy")],
                    [_row("3.mp3", "warm"), _row("4.mp3", "bright"), _row("3.mp3", "warm")],
                    [_row("5.mp3", "dreamy")],
                ],
            ) as get_tag_edge_rows_mock,
            patch(
                "nomarr.components.analytics.mood_analysis_comp.get_library_stats",
                return_value={"total_files": 10},
            ) as get_library_stats_mock,
        ):
            result = get_mood_coverage(mock_db)

        assert result == {
            "total_files": 10,
            "tiers": {
                "strict": {"tagged": 2, "percentage": 20.0},
                "regular": {"tagged": 2, "percentage": 20.0},
                "loose": {"tagged": 1, "percentage": 10.0},
            },
        }
        get_library_stats_mock.assert_called_once_with(mock_db, None)
        assert get_tag_edge_rows_mock.call_count == 3


class TestGetMoodBalance:
    """Tests for ``get_mood_balance``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_tiers_when_no_data(self) -> None:
        """Each tier should return an empty list when the query yields no rows."""
        mock_db = MagicMock()
        with patch(
            "nomarr.components.analytics.mood_analysis_comp._get_tag_edge_rows",
            side_effect=[[], [], []],
        ) as get_tag_edge_rows_mock:
            result = get_mood_balance(mock_db)

        assert result == {"strict": [], "regular": [], "loose": []}
        assert get_tag_edge_rows_mock.call_count == 3

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_counts_plain_mood_values(self) -> None:
        """Repeated plain mood values should be counted within their tier."""
        mock_db = MagicMock()
        with patch(
            "nomarr.components.analytics.mood_analysis_comp._get_tag_edge_rows",
            side_effect=[
                [_row("1.mp3", "happy"), _row("2.mp3", "happy")],
                [],
                [],
            ],
        ):
            result = get_mood_balance(mock_db)

        assert result == {
            "strict": [{"mood": "happy", "count": 2}],
            "regular": [],
            "loose": [],
        }

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_splits_parenthetical_compound_values(self) -> None:
        """Compound mood tuples should increment each cleaned mood separately."""
        mock_db = MagicMock()
        with patch(
            "nomarr.components.analytics.mood_analysis_comp._get_tag_edge_rows",
            side_effect=[[_row("1.mp3", "(happy,sad)")], [], []],
        ):
            result = get_mood_balance(mock_db)

        assert result == {
            "strict": [
                {"mood": "happy", "count": 1},
                {"mood": "sad", "count": 1},
            ],
            "regular": [],
            "loose": [],
        }


class TestGetMoodAndTierTagsForCorrelation:
    """Tests for ``get_mood_and_tier_tags_for_correlation``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_mood_rows_tier_keys_and_tier_rows(self) -> None:
        """Collects rows from the three mood relations plus discovered tier tags."""
        mock_db = MagicMock()
        with (
            patch(
                "nomarr.components.analytics.mood_analysis_comp._get_tag_edge_rows",
                side_effect=[
                    [_row("1.mp3", "happy")],
                    [_row("2.mp3", "calm")],
                    [],
                    [_row("1.mp3", "high")],
                    [_row("2.mp3", "fast")],
                ],
            ) as get_tag_edge_rows_mock,
            patch(
                "nomarr.components.analytics.mood_analysis_comp._get_tier_tag_keys",
                return_value=["nom:energy_tier", "nom:tempo_tier"],
            ) as get_tier_tag_keys_mock,
        ):
            result = get_mood_and_tier_tags_for_correlation(mock_db)

        assert result == {
            "mood_tag_rows": [
                _row("1.mp3", "happy"),
                _row("2.mp3", "calm"),
            ],
            "tier_tag_keys": ["nom:energy_tier", "nom:tempo_tier"],
            "tier_tag_rows": {
                "nom:energy_tier": [_row("1.mp3", "high")],
                "nom:tempo_tier": [_row("2.mp3", "fast")],
            },
        }
        get_tier_tag_keys_mock.assert_called_once_with(mock_db)
        assert get_tag_edge_rows_mock.call_count == 5


class TestGetMoodDistributionData:
    """Tests for ``get_mood_distribution_data``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_flattened_rows_for_each_mood_tier(self) -> None:
        mock_db = MagicMock()
        with patch(
            "nomarr.components.analytics.mood_analysis_comp._get_tag_edge_rows",
            side_effect=[
                [_row("1.mp3", "happy")],
                [_row("2.mp3", "calm")],
                [_row("3.mp3", "dreamy")],
            ],
        ) as get_tag_edge_rows_mock:
            result = get_mood_distribution_data(mock_db)

        assert result == [
            ("nom:mood-strict", "happy"),
            ("nom:mood-regular", "calm"),
            ("nom:mood-loose", "dreamy"),
        ]
        assert get_tag_edge_rows_mock.call_count == 3

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_passes_library_when_filtering_distribution(self) -> None:
        """The natural ``Library`` scope is forwarded to the edge-row query."""
        mock_db = MagicMock()
        library = Library(name="main", root_path="/music")
        with patch(
            "nomarr.components.analytics.mood_analysis_comp._get_tag_edge_rows",
            side_effect=[[], [_row("2.mp3", "warm")], []],
        ) as get_tag_edge_rows_mock:
            result = get_mood_distribution_data(mock_db, library=library)

        assert result == [("nom:mood-regular", "warm")]
        for call in get_tag_edge_rows_mock.call_args_list:
            assert call.args[2] == library


@pytest.mark.unit
@pytest.mark.mocked
def test_locators_for_carriers_preserves_order_scopes_uuid_and_drops_stale() -> None:
    """Public locator projection preserves input order and rejects stale/missing songs."""
    db = MagicMock()
    first_library = Library(name="first", root_path="/one", library_uuid=_UUID)
    second_uuid = "223e4567-e89b-42d3-a456-426614174000"
    second_library = Library(name="second", root_path="/two", library_uuid=second_uuid)
    db.library.list_libraries.return_value = [first_library, second_library]
    first = _song(1, normalized_path="one.mp3")
    stale = _song(2, normalized_path="stale.mp3")
    second = _song(3, normalized_path="two.mp3")

    def resolve(requested: list[SongIdentity]) -> list[Song]:
        available = {
            (_UUID, "one.mp3"): first,
            (second_uuid, "two.mp3"): second,
        }
        return [
            available[key]
            for key in ((item.library.library_uuid, item.normalized_path) for item in requested)
            if key in available
        ]

    db.library.list_songs_by_identity.side_effect = resolve
    carriers = [
        TrackSong(song=second, metadata={}, isrc=None),
        TrackSong(song=stale, metadata={}, isrc=None),
        TrackSong(song=first, metadata={}, isrc=None),
    ]

    assert locators_for_carriers(db, carriers) == [
        _locator("two.mp3").__class__(library=LibraryIdentity(library_uuid=second_uuid), normalized_path="two.mp3"),
        None,
        _locator("one.mp3"),
    ]


@pytest.mark.unit
@pytest.mark.mocked
def test_locators_for_carriers_ignores_libraries_without_uuid() -> None:
    db = MagicMock()
    db.library.list_libraries.return_value = [Library(name="new", root_path="/new")]
    carrier = TrackSong(song=_song(1), metadata={}, isrc=None)

    assert locators_for_carriers(db, [carrier]) == [None]
    db.library.list_songs_by_identity.assert_not_called()


@pytest.mark.unit
@pytest.mark.mocked
def test_locators_for_carriers_empty_input_is_a_noop() -> None:
    db = MagicMock()

    assert locators_for_carriers(db, []) == []
    db.library.list_libraries.assert_not_called()
    db.library.list_songs_by_identity.assert_not_called()


@pytest.mark.unit
@pytest.mark.mocked
def test_locators_for_carriers_rejects_malformed_input_deterministically() -> None:
    db = MagicMock()

    with pytest.raises(TypeError, match="only typed song carriers"):
        locators_for_carriers(db, [object()])  # type: ignore[list-item]

    db.library.list_libraries.assert_not_called()
    db.library.list_songs_by_identity.assert_not_called()


@pytest.mark.unit
@pytest.mark.mocked
def test_mood_rows_scope_multiple_libraries_by_uuid() -> None:
    db = MagicMock()
    other_uuid = "223e4567-e89b-42d3-a456-426614174000"
    requested = Library(name="requested", root_path="/requested", library_uuid=_UUID)
    other = Library(name="other", root_path="/other", library_uuid=other_uuid)
    requested_song = _song(1, normalized_path="requested.mp3")
    other_song = _song(2, normalized_path="other.mp3")
    db.library.list_tags.return_value = [_identity("nom:mood-strict", "happy")]
    db.library.find_songs_with_tag.return_value = (requested_song, other_song)
    db.library.list_libraries.return_value = [requested, other]
    db.library.list_songs_by_identity.side_effect = lambda locators: [
        requested_song if locator.library.library_uuid == _UUID else other_song for locator in locators
    ]

    assert _get_tag_edge_rows(db, "nom:mood-strict", requested) == [(_locator("requested.mp3"), "happy")]


@pytest.mark.unit
@pytest.mark.mocked
def test_mood_rows_project_track_song_with_tagref_value_to_uuid_locator() -> None:
    db = MagicMock()
    library = Library(name="main", root_path="/music", library_uuid=_UUID)
    song = _song(1, normalized_path="mood.mp3")
    db.library.list_tags.return_value = [_identity("nom:mood-strict", "focused")]
    db.library.find_songs_with_tag.return_value = (song,)
    db.library.list_libraries.return_value = [library]
    db.library.list_songs_by_identity.return_value = [song]

    rows = _get_tag_edge_rows(db, "nom:mood-strict")

    assert rows == [(_locator("mood.mp3"), "focused")]
    assert rows[0][0].library.library_uuid == _UUID
    assert not isinstance(rows[0][0], int)


class TestGetTagEdgeRows:
    """Tests for ``_get_tag_edge_rows``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_resolves_identities_and_searches_songs_per_value(self) -> None:
        mock_db = MagicMock()
        library = Library(name="main", root_path="/music", library_uuid=_UUID)
        songs_by_path = {"1.mp3": _song(1), "2.mp3": _song(2)}
        mock_db.library.list_tags.side_effect = [
            [
                _identity("nom:mood-strict", "happy"),
                _identity("nom:mood-strict", "calm"),
            ],
            [],
        ]

        def find_songs_side_effect(identity: TagRef, *, limit: int | None) -> tuple[Song, ...]:
            assert limit is None
            return {"happy": (_song(1),), "calm": (_song(2),)}[str(identity.value)]

        mock_db.library.find_songs_with_tag.side_effect = find_songs_side_effect
        mock_db.library.list_libraries.return_value = [library]
        mock_db.library.list_songs_by_identity.side_effect = lambda locators: [
            songs_by_path[locator.normalized_path] for locator in locators if locator.normalized_path in songs_by_path
        ]

        result = _get_tag_edge_rows(mock_db, "nom:mood-strict")

        identity = LibraryIdentity(library_uuid=_UUID)
        assert result == [
            (SongIdentity(library=identity, normalized_path="1.mp3"), "happy"),
            (SongIdentity(library=identity, normalized_path="2.mp3"), "calm"),
        ]
        mock_db.library.list_tags.assert_any_call(name="nom:mood-strict", limit=1000, offset=0)
        mock_db.library.find_songs_with_tag.assert_any_call(_identity("nom:mood-strict", "happy"), limit=None)
        mock_db.library.find_songs_with_tag.assert_any_call(_identity("nom:mood-strict", "calm"), limit=None)
        assert mock_db.library.find_songs_with_tag.call_count == 2
