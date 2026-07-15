"""Tests for nomarr.components.navidrome.playlist_builder_comp module."""

from __future__ import annotations

from copy import deepcopy
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

# ---------------------------------------------------------------------------
# Module-level patch so all tests automatically get a mocked get_cold_namespace.
# ---------------------------------------------------------------------------
_get_cold_patch = patch("nomarr.components.navidrome.playlist_builder_comp.get_cold_namespace")
mock_get_cold = _get_cold_patch.start()


def teardown_module() -> None:
    _get_cold_patch.stop()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(**overrides: object) -> dict:
    """Build a minimal NavidromePersonalPlaylistContext dict."""
    base: dict = {
        "backbone_id": "backbones/1",
        "library_key": "lib1",
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
        "played_file_ids": ["f1", "f2", "f3"],
        "played_tracks": [],
        "max_genre_playlists": 10,
        "half_life_days": 30.0,
    }
    base.update(overrides)
    return base


def _make_result(file_id: str) -> dict:
    """Build a minimal ANN result dict."""
    return {"file_id": file_id}


def _make_cold_ops(doc_count: int, ann_results: list[list[dict]] | None = None) -> MagicMock:
    """Build a mock cold namespace ops object.

    Args:
        doc_count: Value returned by ``cold_ops.count()``.
        ann_results: If provided, each call to ``ann_search`` returns the
            next list from this sequence.  If exhausted, returns [].

    """
    cold_ops = MagicMock()
    cold_ops.count.return_value = doc_count
    if ann_results is not None:
        cold_ops.ann_search.side_effect = ann_results
    else:
        cold_ops.ann_search.return_value = []
    return cold_ops


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
    results = {"A": [_make_result("f1")]}
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
    results = {"A": [_make_result(f"f{i}") for i in range(20)]}
    result = _interleave_per_cluster(results, {"A": 1.0}, target_size=5)
    assert result == [f"f{i}" for i in range(5)]


@pytest.mark.unit
@pytest.mark.mocked
def test_interleave_single_cluster_fewer_than_target() -> None:
    results = {"A": [_make_result("f1"), _make_result("f2")]}
    result = _interleave_per_cluster(results, {"A": 1.0}, target_size=10)
    assert result == ["f1", "f2"]


@pytest.mark.unit
@pytest.mark.mocked
def test_interleave_proportional_weights_largest_remainder() -> None:
    """Verify largest-remainder slot allocation with known weights."""
    # 3 clusters, weights 0.5, 0.3, 0.2 → target_size=10
    # exact quotas: 5.0, 3.0, 2.0 → floors: 5, 3, 2 → sum=10 → no remainder
    results = {
        "A": [_make_result(f"a{i}") for i in range(10)],
        "B": [_make_result(f"b{i}") for i in range(10)],
        "C": [_make_result(f"c{i}") for i in range(10)],
    }
    weights = {"A": 0.5, "B": 0.3, "C": 0.2}
    result = _interleave_per_cluster(results, weights, target_size=10)

    # Count allocations
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
    # 2 clusters, weights 0.5, 0.5 → target_size=5
    # exact quotas: 2.5, 2.5 → floors: 2, 2 → sum=4 → remainder=1
    # Both have 0.5 fractional part; tiebreak by weight (equal) → first sorted gets it
    results = {
        "A": [_make_result(f"a{i}") for i in range(5)],
        "B": [_make_result(f"b{i}") for i in range(5)],
    }
    weights = {"A": 0.5, "B": 0.5}
    result = _interleave_per_cluster(results, weights, target_size=5)
    assert len(result) == 5
    # One cluster gets 3, the other 2
    a_count = sum(1 for x in result if x.startswith("a"))
    b_count = sum(1 for x in result if x.startswith("b"))
    assert a_count + b_count == 5
    assert abs(a_count - b_count) == 1


@pytest.mark.unit
@pytest.mark.mocked
def test_interleave_zero_total_weight_even_split() -> None:
    """When all weights are zero, fallback to even split across sorted labels."""
    results = {
        "B": [_make_result(f"b{i}") for i in range(5)],
        "A": [_make_result(f"a{i}") for i in range(5)],
    }
    weights = {"A": 0.0, "B": 0.0}
    result = _interleave_per_cluster(results, weights, target_size=4)
    # Even split: 2 each, sorted order: A, B
    a_count = sum(1 for x in result if x.startswith("a"))
    b_count = sum(1 for x in result if x.startswith("b"))
    assert a_count == 2
    assert b_count == 2
    assert len(result) == 4


@pytest.mark.unit
@pytest.mark.mocked
def test_interleave_round_robin_descending_weight_order() -> None:
    """Round-robin should interleave in descending weight order."""
    # A has weight 0.7, B has weight 0.3
    # target_size=4 → A gets 3, B gets 1 (exact: 2.8, 1.2 → floors 2,1 → rem 1 → A gets +1)
    results = {
        "A": [_make_result(f"a{i}") for i in range(5)],
        "B": [_make_result(f"b{i}") for i in range(5)],
    }
    weights = {"A": 0.7, "B": 0.3}
    result = _interleave_per_cluster(results, weights, target_size=4)

    # First round: A first (highest weight), then B
    # Round-robin order: A, B, A, B, ... but B has only 1 slot
    # So: A, B, A, A (B exhausted after 1)
    assert result[0] == "a0"  # First from A (highest weight)
    assert result[1] == "b0"  # Then B
    assert len(result) == 4


@pytest.mark.unit
@pytest.mark.mocked
def test_interleave_clusters_exhausted_returns_partial() -> None:
    """When clusters run out before target_size, return what we have."""
    results = {
        "A": [_make_result("a1")],
        "B": [_make_result("b1")],
    }
    weights = {"A": 0.5, "B": 0.5}
    result = _interleave_per_cluster(results, weights, target_size=100)
    assert len(result) == 2
    assert set(result) == {"a1", "b1"}


@pytest.mark.unit
@pytest.mark.mocked
def test_interleave_no_mutation_of_input_lists() -> None:
    """Original result lists must not be modified."""
    original_a = [_make_result("a1"), _make_result("a2")]
    original_b = [_make_result("b1"), _make_result("b2")]
    results = {"A": deepcopy(original_a), "B": deepcopy(original_b)}
    weights = {"A": 0.5, "B": 0.5}

    _interleave_per_cluster(results, weights, target_size=4)

    # Caller's lists should be unchanged
    assert results["A"] == original_a
    assert results["B"] == original_b


# ===================================================================
# Tests for build_familiar_playlist()
# ===================================================================


@pytest.mark.unit
@pytest.mark.mocked
def test_familiar_no_played_tracks_returns_empty() -> None:
    ctx = _make_ctx(played_file_ids=[])
    db = MagicMock()
    result = build_familiar_playlist(db, ctx)
    assert result == []


@pytest.mark.unit
@pytest.mark.mocked
def test_familiar_empty_cold_collection_returns_empty() -> None:
    ctx = _make_ctx()
    db = MagicMock()
    mock_get_cold.return_value = _make_cold_ops(doc_count=0)

    result = build_familiar_playlist(db, ctx)
    assert result == []


@pytest.mark.unit
@pytest.mark.mocked
def test_familiar_normal_case_filters_to_played() -> None:
    """ANN results are filtered to only include played file_ids."""
    played = ["f1", "f2", "f3"]
    ctx = _make_ctx(played_file_ids=played, max_songs=10)
    db = MagicMock()

    # ANN returns mix of played and unplayed
    ann_results_cluster1 = [_make_result("f1"), _make_result("f99"), _make_result("f2")]
    ann_results_cluster2 = [_make_result("f3"), _make_result("f98")]
    cold_ops = _make_cold_ops(doc_count=1000, ann_results=[ann_results_cluster1, ann_results_cluster2])
    mock_get_cold.return_value = cold_ops

    result = build_familiar_playlist(db, ctx)

    assert len(result) == 1
    entry = result[0]
    assert entry["playlist_type"] == "familiar"
    assert entry["playlist_name"] == "Your Favorites"
    # Only played file_ids should appear
    assert set(entry["file_ids"]).issubset(set(played))
    assert len(entry["file_ids"]) > 0


@pytest.mark.unit
@pytest.mark.mocked
def test_familiar_no_played_in_ann_results_returns_empty_file_ids() -> None:
    """When no ANN results match played tracks, file_ids is empty but entry still returned."""
    ctx = _make_ctx(played_file_ids=["f1"], max_songs=10)
    db = MagicMock()

    # ANN returns only unplayed tracks
    ann_results = [[_make_result("f99"), _make_result("f98")], [_make_result("f97")]]
    cold_ops = _make_cold_ops(doc_count=1000, ann_results=ann_results)
    mock_get_cold.return_value = cold_ops

    result = build_familiar_playlist(db, ctx)

    assert len(result) == 1
    assert result[0]["file_ids"] == []


@pytest.mark.unit
@pytest.mark.mocked
def test_familiar_multiple_clusters_proportional_mix() -> None:
    """Multiple clusters produce interleaved results proportional to weight."""
    played = [f"f{i}" for i in range(100)]
    ctx = _make_ctx(played_file_ids=played, max_songs=10)
    db = MagicMock()

    # Cluster 1 (weight 0.6): 6 played results
    # Cluster 2 (weight 0.4): 4 played results
    ann_c1 = [_make_result(f"f{i}") for i in range(10)]
    ann_c2 = [_make_result(f"f{i}") for i in range(10, 20)]
    cold_ops = _make_cold_ops(doc_count=1000, ann_results=[ann_c1, ann_c2])
    mock_get_cold.return_value = cold_ops

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
    db = MagicMock()
    mock_get_cold.return_value = _make_cold_ops(doc_count=0)

    result = build_discovery_playlist(db, ctx)
    assert result == []


@pytest.mark.unit
@pytest.mark.mocked
def test_discovery_normal_case_excludes_played() -> None:
    """ANN results exclude played file_ids."""
    played = ["f1", "f2"]
    ctx = _make_ctx(played_file_ids=played, max_songs=10)
    db = MagicMock()

    # ANN returns mix; played should be excluded
    ann_c1 = [_make_result("f1"), _make_result("f10"), _make_result("f11")]
    ann_c2 = [_make_result("f2"), _make_result("f12")]
    cold_ops = _make_cold_ops(doc_count=1000, ann_results=[ann_c1, ann_c2])
    mock_get_cold.return_value = cold_ops

    result = build_discovery_playlist(db, ctx)

    assert len(result) == 1
    entry = result[0]
    assert entry["playlist_type"] == "discovery"
    assert entry["playlist_name"] == "Discover Weekly"
    # Played tracks must NOT appear
    assert "f1" not in entry["file_ids"]
    assert "f2" not in entry["file_ids"]
    assert len(entry["file_ids"]) > 0


@pytest.mark.unit
@pytest.mark.mocked
def test_discovery_all_results_are_played_returns_empty_file_ids() -> None:
    """When all ANN results are played tracks, file_ids is empty."""
    played = ["f1", "f2", "f3"]
    ctx = _make_ctx(played_file_ids=played, max_songs=10)
    db = MagicMock()

    # All results are played
    ann_c1 = [_make_result("f1"), _make_result("f2")]
    ann_c2 = [_make_result("f3")]
    cold_ops = _make_cold_ops(doc_count=1000, ann_results=[ann_c1, ann_c2])
    mock_get_cold.return_value = cold_ops

    result = build_discovery_playlist(db, ctx)

    assert len(result) == 1
    assert result[0]["file_ids"] == []


# ===================================================================
# Tests for build_hidden_gems_playlist()
# ===================================================================


@pytest.mark.unit
@pytest.mark.mocked
def test_hidden_gems_empty_cold_collection_returns_empty() -> None:
    ctx = _make_ctx()
    db = MagicMock()
    db.tags.get_distinct_tag_values_for_files.return_value = {"Artist A"}
    mock_get_cold.return_value = _make_cold_ops(doc_count=0)

    result = build_hidden_gems_playlist(db, ctx)
    assert result == []


@pytest.mark.unit
@pytest.mark.mocked
def test_hidden_gems_no_known_artists_skips_artist_filter() -> None:
    """When no known artists, behaves like discovery (no artist exclusion)."""
    ctx = _make_ctx(played_file_ids=["f1"], max_songs=10)
    db = MagicMock()

    # No known artists
    db.tags.get_distinct_tag_values_for_files.return_value = set()

    ann_c1 = [_make_result("f10"), _make_result("f11")]
    ann_c2 = [_make_result("f12")]
    cold_ops = _make_cold_ops(doc_count=1000, ann_results=[ann_c1, ann_c2])
    mock_get_cold.return_value = cold_ops

    result = build_hidden_gems_playlist(db, ctx)

    assert len(result) == 1
    entry = result[0]
    assert entry["playlist_type"] == "hidden_gems"
    assert entry["playlist_name"] == "Hidden Gems"
    # Grouped tag query should NOT be called when no known artists
    db.tags.get_tag_values_grouped_by_file.assert_not_called()
    # Results should include non-played tracks
    assert "f1" not in entry["file_ids"]
    assert len(entry["file_ids"]) > 0


@pytest.mark.unit
@pytest.mark.mocked
def test_hidden_gems_known_artists_excludes_artist_tracks() -> None:
    """Tracks by known artists are excluded from results."""
    ctx = _make_ctx(played_file_ids=["f1"], max_songs=10)
    db = MagicMock()

    # Known artists from played tracks
    db.tags.get_distinct_tag_values_for_files.return_value = {"Known Artist"}

    # ANN returns candidates; some by known artist
    ann_c1 = [_make_result("f10"), _make_result("f11"), _make_result("f12")]
    ann_c2 = [_make_result("f13")]
    cold_ops = _make_cold_ops(doc_count=1000, ann_results=[ann_c1, ann_c2])
    mock_get_cold.return_value = cold_ops

    # f11 is by known artist, others are not
    db.tags.get_tag_values_grouped_by_file.return_value = {
        "f10": {"Unknown Artist"},
        "f11": {"Known Artist"},
        "f12": {"Another Unknown"},
        "f13": {"Yet Another"},
    }

    result = build_hidden_gems_playlist(db, ctx)

    assert len(result) == 1
    entry = result[0]
    # f11 should be excluded (known artist)
    assert "f11" not in entry["file_ids"]
    # f10, f12, f13 should be present
    assert "f10" in entry["file_ids"]
    assert "f12" in entry["file_ids"]
    assert "f13" in entry["file_ids"]


@pytest.mark.unit
@pytest.mark.mocked
def test_hidden_gems_both_played_and_artist_exclusion() -> None:
    """Both played tracks and known-artist tracks are excluded."""
    ctx = _make_ctx(played_file_ids=["f1", "f2"], max_songs=10)
    db = MagicMock()

    db.tags.get_distinct_tag_values_for_files.return_value = {"Known Artist"}

    # f1 is played, f10 is by known artist, f11 is clean
    ann_c1 = [_make_result("f1"), _make_result("f10"), _make_result("f11")]
    ann_c2 = [_make_result("f2"), _make_result("f12")]
    cold_ops = _make_cold_ops(doc_count=1000, ann_results=[ann_c1, ann_c2])
    mock_get_cold.return_value = cold_ops

    db.tags.get_tag_values_grouped_by_file.return_value = {
        "f10": {"Known Artist"},
        "f11": {"Unknown"},
        "f12": {"Other Unknown"},
    }

    result = build_hidden_gems_playlist(db, ctx)

    assert len(result) == 1
    entry = result[0]
    # Played tracks excluded
    assert "f1" not in entry["file_ids"]
    assert "f2" not in entry["file_ids"]
    # Known artist excluded
    assert "f10" not in entry["file_ids"]
    # Clean tracks included
    assert "f11" in entry["file_ids"]
    assert "f12" in entry["file_ids"]


# ===================================================================
# Tests for build_universal_playlist()
# ===================================================================


@pytest.mark.unit
@pytest.mark.mocked
def test_universal_empty_cold_collection_returns_empty() -> None:
    ctx = _make_ctx()
    db = MagicMock()
    mock_get_cold.return_value = _make_cold_ops(doc_count=0)

    result = build_universal_playlist(db, ctx)
    assert result == []


@pytest.mark.unit
@pytest.mark.mocked
def test_universal_normal_case_stride_sampling() -> None:
    """Stride sampling selects every Nth result from each cluster."""
    ctx = _make_ctx(max_songs=5)
    db = MagicMock()

    # 20 results per cluster → step = 20 // 5 = 4 → samples indices 0, 4, 8, 12, 16
    ann_c1 = [_make_result(f"a{i}") for i in range(20)]
    ann_c2 = [_make_result(f"b{i}") for i in range(20)]
    cold_ops = _make_cold_ops(doc_count=1000, ann_results=[ann_c1, ann_c2])
    mock_get_cold.return_value = cold_ops

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
    db = MagicMock()

    # Provide enough results that shuffle matters
    ann_c1 = [_make_result(f"a{i}") for i in range(40)]
    ann_c2 = [_make_result(f"b{i}") for i in range(40)]
    # Use return_value cycling since multiple calls happen across runs
    cold_ops = MagicMock()
    cold_ops.count.return_value = 1000
    cold_ops.ann_search.side_effect = [ann_c1, ann_c2] * 10  # Enough for 10 runs
    mock_get_cold.return_value = cold_ops

    # Run multiple times; at least one should differ in order
    results_sets = []
    for _ in range(5):
        result = build_universal_playlist(db, ctx)
        results_sets.append(tuple(result[0]["file_ids"]))

    # Not all runs should produce identical order (probabilistically near-certain with 20 items)
    unique_orders = set(results_sets)
    assert len(unique_orders) > 1, "Shuffle should produce different orderings across runs"


@pytest.mark.unit
@pytest.mark.mocked
def test_universal_empty_results_returns_empty_file_ids() -> None:
    """When ANN returns empty for all clusters, file_ids is empty."""
    ctx = _make_ctx(max_songs=10)
    db = MagicMock()

    cold_ops = _make_cold_ops(doc_count=1000, ann_results=[[], []])
    mock_get_cold.return_value = cold_ops

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
    db = MagicMock()
    result = build_genre_playlists(db, ctx)
    assert result == []


@pytest.mark.unit
@pytest.mark.mocked
def test_genre_empty_cold_collection_returns_empty() -> None:
    ctx = _make_ctx()
    db = MagicMock()
    mock_get_cold.return_value = _make_cold_ops(doc_count=0)

    result = build_genre_playlists(db, ctx)
    assert result == []


@pytest.mark.unit
@pytest.mark.mocked
def test_genre_cluster_below_min_songs_skipped() -> None:
    """Clusters with fewer than _GENRE_MIN_Songs results are skipped."""
    ctx = _make_ctx(max_songs=50)
    db = MagicMock()

    # Return fewer than _GENRE_MIN_SONGS (100) results
    few_results = [_make_result(f"f{i}") for i in range(50)]
    cold_ops = _make_cold_ops(doc_count=1000, ann_results=[few_results, few_results])
    mock_get_cold.return_value = cold_ops

    result = build_genre_playlists(db, ctx)

    # Both clusters should be skipped
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
    db = MagicMock()
    result = build_genre_playlists(db, ctx)
    assert result == []
