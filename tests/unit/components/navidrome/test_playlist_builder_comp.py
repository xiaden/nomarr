"""Tests for nomarr.components.navidrome.playlist_builder_comp module.

The builders now consume the typed vector domain contract: cold embeddings are
read via ``db.ml.embedding_counts``/``search_similar_vectors`` returning domain
values, ANN results are typed :class:`VectorMatch` values carrying a natural
:class:`SongIdentity`, and each match is adapted back to its transport file
handle through ``db.library.get_song_by_normalized_path``.  Tests mock those
authoritative methods with domain fixtures — no raw ``song_id`` rows or
``stats`` dict access.
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.navidrome.playlist_builder_comp import (
    _GENRE_MIN_SONGS,
    _MAX_GENRE_PLAYLISTS_CAP,
    _interleave_per_cluster,
    build_discovery_playlist,
    build_familiar_playlist,
    build_genre_playlists,
    build_hidden_gems_playlist,
    build_universal_playlist,
)
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.vector_dataclass import EmbeddingCounts, SongVector, VectorMatch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LIB_ID = LibraryIdentity(name="test-lib", root_path="/test-lib")


def _make_ctx(**overrides: object) -> dict:
    """Build a minimal NavidromePersonalPlaylistContext dict."""
    base: dict = {
        "backbone_id": "backbones/1",
        "clusters": [
            {
                "label": "Rock",
                "centroid": [0.1, 0.2, 0.3],
                "track_count": 500,
                "total_weight": 0.6,
            },
            {
                "label": "Jazz",
                "centroid": [0.4, 0.5, 0.6],
                "track_count": 200,
                "total_weight": 0.4,
            },
        ],
        "max_songs": 50,
        "played_file_ids": [1, 2, 3],
        "played_tracks": [],
        "max_genre_playlists": 10,
        "half_life_days": 30.0,
    }
    base.update(overrides)
    return base


def _song_identity(song_id: int) -> SongIdentity:
    """Build a deterministic natural identity encoding ``song_id`` in its path."""
    return SongIdentity(library=_LIB_ID, normalized_path=f"rel/{song_id}.mp3")


def _fid_from_path(normalized_path: str) -> int:
    """Reverse the encoding in :func:`_song_identity`."""
    return int(normalized_path.removeprefix("rel/").removesuffix(".mp3"))


def _make_result(song_id: int) -> VectorMatch:
    """Build a typed ANN :class:`VectorMatch` for a song handle."""
    return VectorMatch(song=_song_identity(song_id), backbone="backbones/1", score=0.5)


def _make_song_vector(song_id: int, seed: int) -> SongVector:
    return SongVector(
        song=_song_identity(song_id),
        backbone="backbones/1",
        vector=(float(seed), float(seed) + 1.0),
        model_suite_hash=None,
        num_segments=None,
        segmentation_hash=None,
        genres=None,
    )


def _make_wire_item(key: str) -> dict:
    """Build a generic wire-keyed item for the dead-code interleave helper."""
    return {"file_id": key}


def _make_db(
    cold_count: int = 1000,
    search_results: list[list[VectorMatch]] | None = None,
    vectors: dict[int, SongVector] | None = None,
) -> MagicMock:
    """Build a mock Database with pre-configured ml/library namespaces.

    ``db.ml.embedding_counts`` returns typed :class:`EmbeddingCounts`; each call
    to ``db.ml.search_similar_vectors`` returns the next list (converted to a
    tuple) from ``search_results``, else an empty tuple.  Every result's natural
    ``SongIdentity`` reverses to its file handle through ``db.library``.
    Optional ``vectors`` seed ``db.ml.get_song_vector`` for the genre builder.
    """
    db = MagicMock()
    db.ml.embedding_counts = MagicMock(return_value=EmbeddingCounts(hot_count=0, cold_count=cold_count))
    db.ml.search_similar_vectors = MagicMock()
    if search_results is not None:
        db.ml.search_similar_vectors.side_effect = [tuple(lst) for lst in search_results]
    else:
        db.ml.search_similar_vectors.return_value = ()

    def _reverse(normalized_path: str, _library: object) -> SimpleNamespace | None:
        return SimpleNamespace(song_id=_fid_from_path(normalized_path))

    db.library.get_song_by_normalized_path = MagicMock(side_effect=_reverse)
    db.library.resolve_song_identity = MagicMock(side_effect=lambda song_id: _song_identity(song_id))
    vectors = vectors or {}

    def _get_song_vector(_backbone: str, song: SongIdentity) -> SongVector | None:
        return vectors.get(_fid_from_path(song.normalized_path))

    db.ml.get_song_vector = MagicMock(side_effect=_get_song_vector)
    return db


# ===================================================================
# Tests for _interleave_per_cluster()
# ===================================================================


@pytest.mark.unit
@pytest.mark.mocked
def test_interleave_empty_results_returns_empty() -> None:
    result = _interleave_per_cluster({}, {"A": 1.0}, target_size=10)
    assert result == []


@pytest.mark.unit
@pytest.mark.mocked
def test_interleave_target_size_zero_returns_empty() -> None:
    results = {"A": [_make_wire_item(1)]}
    result = _interleave_per_cluster(results, {"A": 1.0}, target_size=0)
    assert result == []


@pytest.mark.unit
@pytest.mark.mocked
def test_interleave_all_empty_clusters_returns_empty() -> None:
    results = {"A": [], "B": []}
    result = _interleave_per_cluster(results, {"A": 1.0, "B": 1.0}, target_size=10)
    assert result == []


@pytest.mark.unit
@pytest.mark.mocked
def test_interleave_single_cluster_returns_up_to_target() -> None:
    results = {"A": [_make_wire_item(f"f{i}") for i in range(20)]}
    result = _interleave_per_cluster(results, {"A": 1.0}, target_size=5)
    assert result == [f"f{i}" for i in range(5)]


@pytest.mark.unit
@pytest.mark.mocked
def test_interleave_single_cluster_fewer_than_target() -> None:
    results = {"A": [_make_wire_item("f1"), _make_wire_item("f2")]}
    result = _interleave_per_cluster(results, {"A": 1.0}, target_size=10)
    assert result == ["f1", "f2"]


@pytest.mark.unit
@pytest.mark.mocked
def test_interleave_proportional_weights_largest_remainder() -> None:
    """Verify largest-remainder slot allocation with known weights."""
    results = {
        "A": [_make_wire_item(f"a{i}") for i in range(10)],
        "B": [_make_wire_item(f"b{i}") for i in range(10)],
        "C": [_make_wire_item(f"c{i}") for i in range(10)],
    }
    weights = {"A": 0.5, "B": 0.3, "C": 0.2}
    result = _interleave_per_cluster(results, weights, target_size=10)

    a_count = sum(1 for x in result if x.startswith("a"))
    b_count = sum(1 for x in result if x.startswith("b"))
    c_count = sum(1 for x in result if x.startswith("c"))
    assert a_count == 5
    assert b_count == 3
    assert c_count == 2
    assert len(result) == 10


@pytest.mark.unit
@pytest.mark.mocked
def test_interleave_largest_remainder_distributes_leftover() -> None:
    """When floors don't sum to target, largest fractional remainders get +1."""
    results = {
        "A": [_make_wire_item(f"a{i}") for i in range(5)],
        "B": [_make_wire_item(f"b{i}") for i in range(5)],
    }
    weights = {"A": 0.5, "B": 0.5}
    result = _interleave_per_cluster(results, weights, target_size=5)
    assert len(result) == 5
    a_count = sum(1 for x in result if x.startswith("a"))
    b_count = sum(1 for x in result if x.startswith("b"))
    assert a_count + b_count == 5
    assert abs(a_count - b_count) == 1


@pytest.mark.unit
@pytest.mark.mocked
def test_interleave_zero_total_weight_even_split() -> None:
    """When all weights are zero, fallback to even split across sorted labels."""
    results = {
        "B": [_make_wire_item(f"b{i}") for i in range(5)],
        "A": [_make_wire_item(f"a{i}") for i in range(5)],
    }
    weights = {"A": 0.0, "B": 0.0}
    result = _interleave_per_cluster(results, weights, target_size=4)
    a_count = sum(1 for x in result if x.startswith("a"))
    b_count = sum(1 for x in result if x.startswith("b"))
    assert a_count == 2
    assert b_count == 2
    assert len(result) == 4


@pytest.mark.unit
@pytest.mark.mocked
def test_interleave_round_robin_descending_weight_order() -> None:
    """Round-robin should interleave in descending weight order."""
    results = {
        "A": [_make_wire_item(f"a{i}") for i in range(5)],
        "B": [_make_wire_item(f"b{i}") for i in range(5)],
    }
    weights = {"A": 0.7, "B": 0.3}
    result = _interleave_per_cluster(results, weights, target_size=4)

    assert result[0] == "a0"  # First from A (highest weight)
    assert result[1] == "b0"  # Then B
    assert len(result) == 4


@pytest.mark.unit
@pytest.mark.mocked
def test_interleave_clusters_exhausted_returns_partial() -> None:
    """When clusters run out before target_size, return what we have."""
    results = {
        "A": [_make_wire_item("a1")],
        "B": [_make_wire_item("b1")],
    }
    weights = {"A": 0.5, "B": 0.5}
    result = _interleave_per_cluster(results, weights, target_size=100)
    assert len(result) == 2
    assert set(result) == {"a1", "b1"}


@pytest.mark.unit
@pytest.mark.mocked
def test_interleave_no_mutation_of_input_lists() -> None:
    """Original result lists must not be modified."""
    original_a = [_make_wire_item(1), _make_wire_item(2)]
    original_b = [_make_wire_item(1), _make_wire_item(2)]
    results = {"A": deepcopy(original_a), "B": deepcopy(original_b)}
    weights = {"A": 0.5, "B": 0.5}

    _interleave_per_cluster(results, weights, target_size=4)

    assert results["A"] == original_a
    assert results["B"] == original_b


# ===================================================================
# Tests for build_familiar_playlist()
# ===================================================================


@pytest.mark.unit
@pytest.mark.mocked
def test_familiar_no_played_tracks_returns_empty() -> None:
    ctx = _make_ctx(played_file_ids=[])
    db = _make_db()
    result = build_familiar_playlist(db, ctx)
    assert result == []


@pytest.mark.unit
@pytest.mark.mocked
def test_familiar_empty_cold_collection_returns_empty() -> None:
    ctx = _make_ctx()
    db = _make_db(cold_count=0)
    result = build_familiar_playlist(db, ctx)
    assert result == []


@pytest.mark.unit
@pytest.mark.mocked
def test_familiar_normal_case_filters_to_played() -> None:
    """ANN results are filtered to only include played file_ids."""
    played = [1, 2, 3]
    ctx = _make_ctx(played_file_ids=played, max_songs=10)

    ann_c1 = [_make_result(1), _make_result(99), _make_result(2)]
    ann_c2 = [_make_result(3), _make_result(98)]
    db = _make_db(cold_count=1000, search_results=[ann_c1, ann_c2])

    result = build_familiar_playlist(db, ctx)

    assert len(result) == 1
    entry = result[0]
    assert entry["playlist_type"] == "familiar"
    assert entry["playlist_name"] == "Your Favorites"
    assert set(entry["file_ids"]).issubset({str(p) for p in played})
    assert len(entry["file_ids"]) > 0


@pytest.mark.unit
@pytest.mark.mocked
def test_familiar_no_played_in_ann_results_returns_empty_file_ids() -> None:
    """When no ANN results match played tracks, file_ids is empty but entry still returned."""
    ctx = _make_ctx(played_file_ids=[1], max_songs=10)

    ann_c1 = [_make_result(99), _make_result(98)]
    ann_c2 = [_make_result(97)]
    db = _make_db(cold_count=1000, search_results=[ann_c1, ann_c2])

    result = build_familiar_playlist(db, ctx)

    assert len(result) == 1
    assert result[0]["file_ids"] == []


@pytest.mark.unit
@pytest.mark.mocked
def test_familiar_multiple_clusters_proportional_mix() -> None:
    """Multiple clusters produce interleaved results proportional to weight."""
    played = list(range(100))
    ctx = _make_ctx(played_file_ids=played, max_songs=10)

    ann_c1 = [_make_result(i) for i in range(10)]
    ann_c2 = [_make_result(i) for i in range(10, 20)]
    db = _make_db(cold_count=1000, search_results=[ann_c1, ann_c2])

    result = build_familiar_playlist(db, ctx)

    assert len(result) == 1
    entry = result[0]
    assert len(entry["file_ids"]) == 10


# ===================================================================
# Tests for build_discovery_playlist()
# ===================================================================


@pytest.mark.unit
@pytest.mark.mocked
def test_discovery_empty_cold_collection_returns_empty() -> None:
    ctx = _make_ctx()
    db = _make_db(cold_count=0)
    result = build_discovery_playlist(db, ctx)
    assert result == []


@pytest.mark.unit
@pytest.mark.mocked
def test_discovery_normal_case_excludes_played() -> None:
    """ANN results exclude played file_ids."""
    played = [1, 2]
    ctx = _make_ctx(played_file_ids=played, max_songs=10)

    ann_c1 = [_make_result(1), _make_result(10), _make_result(11)]
    ann_c2 = [_make_result(2), _make_result(12)]
    db = _make_db(cold_count=1000, search_results=[ann_c1, ann_c2])

    result = build_discovery_playlist(db, ctx)

    assert len(result) == 1
    entry = result[0]
    assert entry["playlist_type"] == "discovery"
    assert entry["playlist_name"] == "Discover Weekly"
    assert 1 not in entry["file_ids"]
    assert 2 not in entry["file_ids"]
    assert len(entry["file_ids"]) > 0


@pytest.mark.unit
@pytest.mark.mocked
def test_discovery_all_results_are_played_returns_empty_file_ids() -> None:
    """When all ANN results are played tracks, file_ids is empty."""
    played = [1, 2, 3]
    ctx = _make_ctx(played_file_ids=played, max_songs=10)

    ann_c1 = [_make_result(1), _make_result(2)]
    ann_c2 = [_make_result(3)]
    db = _make_db(cold_count=1000, search_results=[ann_c1, ann_c2])

    result = build_discovery_playlist(db, ctx)

    assert len(result) == 1
    assert result[0]["file_ids"] == []


# ===================================================================
# Tests for build_hidden_gems_playlist()
# ===================================================================

TAGS_ARTIST_PATH = "nomarr.components.navidrome.playlist_builder_comp"


@pytest.mark.unit
@pytest.mark.mocked
def test_hidden_gems_empty_cold_collection_returns_empty() -> None:
    ctx = _make_ctx()
    db = _make_db(cold_count=0)

    with patch(
        f"{TAGS_ARTIST_PATH}.get_distinct_tag_values_for_files",
        new=MagicMock(return_value=["Artist A"]),
    ):
        result = build_hidden_gems_playlist(db, ctx)
    assert result == []


@pytest.mark.unit
@pytest.mark.mocked
def test_hidden_gems_no_known_artists_skips_artist_filter() -> None:
    """When no known artists, behaves like discovery (no artist exclusion)."""
    ctx = _make_ctx(played_file_ids=[1], max_songs=10)

    db = _make_db(cold_count=1000, search_results=[[_make_result(10), _make_result(11)], [_make_result(12)]])

    with (
        patch(f"{TAGS_ARTIST_PATH}.get_distinct_tag_values_for_files", new=MagicMock(return_value=[])),
        patch(f"{TAGS_ARTIST_PATH}.get_tag_values_grouped_by_file", new=MagicMock(return_value={})) as mock_grouped,
    ):
        result = build_hidden_gems_playlist(db, ctx)

    assert len(result) == 1
    entry = result[0]
    assert entry["playlist_type"] == "hidden_gems"
    assert entry["playlist_name"] == "Hidden Gems"
    mock_grouped.assert_not_called()
    assert "1" not in entry["file_ids"]
    assert len(entry["file_ids"]) > 0


@pytest.mark.unit
@pytest.mark.mocked
def test_hidden_gems_known_artists_excludes_artist_tracks() -> None:
    """Tracks by known artists are excluded from results."""
    ctx = _make_ctx(played_file_ids=[1], max_songs=10)

    ann_c1 = [_make_result(10), _make_result(11), _make_result(12)]
    ann_c2 = [_make_result(13)]
    db = _make_db(cold_count=1000, search_results=[ann_c1, ann_c2])

    with (
        patch(
            f"{TAGS_ARTIST_PATH}.get_distinct_tag_values_for_files",
            new=MagicMock(return_value=["Known Artist"]),
        ),
        patch(
            f"{TAGS_ARTIST_PATH}.get_tag_values_grouped_by_file",
            new=MagicMock(
                return_value={
                    10: {"Unknown Artist"},
                    11: {"Known Artist"},
                    12: {"Another Unknown"},
                    13: {"Yet Another"},
                }
            ),
        ),
    ):
        result = build_hidden_gems_playlist(db, ctx)

    assert len(result) == 1
    entry = result[0]
    assert "11" not in entry["file_ids"]
    assert "10" in entry["file_ids"]
    assert "12" in entry["file_ids"]
    assert "13" in entry["file_ids"]


@pytest.mark.unit
@pytest.mark.mocked
def test_hidden_gems_both_played_and_artist_exclusion() -> None:
    """Both played tracks and known-artist tracks are excluded."""
    ctx = _make_ctx(played_file_ids=[1, 2], max_songs=10)

    ann_c1 = [_make_result(1), _make_result(10), _make_result(11)]
    ann_c2 = [_make_result(2), _make_result(12)]
    db = _make_db(cold_count=1000, search_results=[ann_c1, ann_c2])

    with (
        patch(
            f"{TAGS_ARTIST_PATH}.get_distinct_tag_values_for_files",
            new=MagicMock(return_value=["Known Artist"]),
        ),
        patch(
            f"{TAGS_ARTIST_PATH}.get_tag_values_grouped_by_file",
            new=MagicMock(
                return_value={
                    10: {"Known Artist"},
                    11: {"Unknown"},
                    12: {"Other Unknown"},
                }
            ),
        ),
    ):
        result = build_hidden_gems_playlist(db, ctx)

    assert len(result) == 1
    entry = result[0]
    assert "1" not in entry["file_ids"]
    assert "2" not in entry["file_ids"]
    assert "10" not in entry["file_ids"]
    assert "11" in entry["file_ids"]
    assert "12" in entry["file_ids"]


# ===================================================================
# Tests for build_universal_playlist()
# ===================================================================


@pytest.mark.unit
@pytest.mark.mocked
def test_universal_empty_cold_collection_returns_empty() -> None:
    ctx = _make_ctx()
    db = _make_db(cold_count=0)
    result = build_universal_playlist(db, ctx)
    assert result == []


@pytest.mark.unit
@pytest.mark.mocked
def test_universal_normal_case_stride_sampling() -> None:
    """Stride sampling selects every Nth result from each cluster."""
    ctx = _make_ctx(max_songs=5)

    ann_c1 = [_make_result(i) for i in range(1, 21)]
    ann_c2 = [_make_result(i) for i in range(21, 41)]
    db = _make_db(cold_count=1000, search_results=[ann_c1, ann_c2])

    result = build_universal_playlist(db, ctx)

    assert len(result) == 1
    entry = result[0]
    assert entry["playlist_type"] == "universal"
    assert entry["playlist_name"] == "Your Mix"
    assert len(entry["file_ids"]) > 0


@pytest.mark.unit
@pytest.mark.mocked
def test_universal_shuffle_is_applied() -> None:
    """Results should be shuffled — verify by running multiple times and checking order differs."""
    ctx = _make_ctx(max_songs=20)

    ann_c1 = [_make_result(i) for i in range(1, 41)]
    ann_c2 = [_make_result(i) for i in range(41, 81)]

    results_sets = []
    for _ in range(5):
        db = _make_db(cold_count=1000, search_results=[ann_c1, ann_c2])
        result = build_universal_playlist(db, ctx)
        results_sets.append(tuple(result[0]["file_ids"]))

    unique_orders = set(results_sets)
    assert len(unique_orders) > 1, "Shuffle should produce different orderings across runs"


@pytest.mark.unit
@pytest.mark.mocked
def test_universal_empty_results_returns_empty_file_ids() -> None:
    """When ANN returns empty for all clusters, file_ids is empty."""
    ctx = _make_ctx(max_songs=10)
    db = _make_db(cold_count=1000, search_results=[[], []])
    result = build_universal_playlist(db, ctx)
    assert len(result) == 1
    assert result[0]["file_ids"] == []


# ===================================================================
# Tests for build_genre_playlists()
# ===================================================================


@pytest.mark.unit
@pytest.mark.mocked
def test_genre_no_clusters_returns_empty() -> None:
    ctx = _make_ctx(clusters=[])
    db = _make_db()
    result = build_genre_playlists(db, ctx)
    assert result == []


@pytest.mark.unit
@pytest.mark.mocked
def test_genre_empty_cold_collection_returns_empty() -> None:
    ctx = _make_ctx()
    db = _make_db(cold_count=0)
    result = build_genre_playlists(db, ctx)
    assert result == []


@pytest.mark.unit
@pytest.mark.mocked
def test_genre_no_played_tracks_returns_empty() -> None:
    """When played_tracks is empty, genre playlists returns empty."""
    ctx = _make_ctx()
    ctx["played_tracks"] = []
    db = _make_db(cold_count=1000)
    result = build_genre_playlists(db, ctx)
    assert result == []


# ===================================================================
# Genre playlist builder — targeted unit tests
# ===================================================================


def test_genre_min_songs_constant_is_reasonable() -> None:
    """_GENRE_MIN_SONGS must be a positive integer (minimum viable playlist size)."""
    assert _GENRE_MIN_SONGS >= 1


def test_genre_max_cap_constant_is_25() -> None:
    """_MAX_GENRE_PLAYLISTS_CAP limits playlist count to 25."""
    assert _MAX_GENRE_PLAYLISTS_CAP == 25


@pytest.mark.unit
@pytest.mark.mocked
def test_genre_empty_no_tracks_returns_empty() -> None:
    """When played_tracks is empty, genre playlists are empty."""
    ctx = _make_ctx(clusters=[{"label": "Rock", "centroid": [0.1], "track_count": 100, "total_weight": 1.0}])
    ctx["played_tracks"] = []
    ctx["played_file_ids"] = []
    db = _make_db()
    result = build_genre_playlists(db, ctx)
    assert result == []


@pytest.mark.unit
@pytest.mark.mocked
def test_genre_builds_playlist_from_played_tracks() -> None:
    """Genre builder resolves played vectors, builds centroid, searches, adapts results.

    Three played tracks tagged ``Rock`` seed the genre centroid; the cold
    search returns ≥ ``_GENRE_MIN_SONGS`` matches; results are adapted to file
    handles and capped at ``max_songs``.
    """
    played = [1, 2, 3]
    ctx = _make_ctx(
        played_file_ids=played,
        max_songs=50,
        played_tracks=[{"file_id": fid, "playcount": 5, "last_played": 100_000_000} for fid in played],
    )
    vectors = {fid: _make_song_vector(fid, seed=fid) for fid in played}
    genre_map = {fid: {"Rock"} for fid in played}
    # > _GENRE_MIN_SONGS matches from the cold search.
    search = [_make_result(i) for i in range(1000, 1000 + _GENRE_MIN_SONGS + 20)]
    db = _make_db(cold_count=1000, search_results=[search], vectors=vectors)

    with patch(
        f"{TAGS_ARTIST_PATH}.get_tag_values_grouped_by_file",
        new=MagicMock(return_value=genre_map),
    ):
        result = build_genre_playlists(db, ctx)

    assert len(result) == 1
    entry = result[0]
    assert entry["playlist_type"] == "genre_rock"
    assert entry["playlist_name"] == "Your Rock Mix"
    assert len(entry["file_ids"]) == ctx["max_songs"]
    assert all(pid in entry["file_ids"] for pid in map(str, range(1000, 1050)))


@pytest.mark.unit
@pytest.mark.mocked
def test_genre_below_min_songs_is_skipped() -> None:
    """A genre whose search returns fewer than _GENRE_MIN_SONGS is skipped."""
    played = [1, 2, 3]
    ctx = _make_ctx(
        played_file_ids=played,
        max_songs=50,
        played_tracks=[{"file_id": fid, "playcount": 5, "last_played": 100_000_000} for fid in played],
    )
    vectors = {fid: _make_song_vector(fid, seed=fid) for fid in played}
    genre_map = {fid: {"Rock"} for fid in played}
    # Far fewer than _GENRE_MIN_SONGS matches.
    search = [_make_result(i) for i in range(1000, 1005)]
    db = _make_db(cold_count=1000, search_results=[search], vectors=vectors)

    with patch(
        f"{TAGS_ARTIST_PATH}.get_tag_values_grouped_by_file",
        new=MagicMock(return_value=genre_map),
    ):
        result = build_genre_playlists(db, ctx)

    assert result == []
