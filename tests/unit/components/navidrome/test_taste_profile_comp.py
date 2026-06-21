"""Unit tests for taste profile computation component.

Tests cover:
- ``_compute_recency_weights`` (pure function)
- ``_compute_weighted_centroid`` (pure function)
- ``compute_taste_profile`` (requires mocking DB/component calls)
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from nomarr.components.navidrome.taste_profile_comp import (
    _compute_recency_weights,
    _compute_weighted_centroid,
    compute_taste_profile,
)

# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------


def _make_play(
    file_id: str | None,
    playcount: int = 1,
    last_played: int | None = 1_000_000,
) -> dict:
    """Build a ``TrackPlayData`` dict."""
    return {
        "file_id": file_id,
        "playcount": playcount,
        "last_played": last_played,
    }


def _make_vector(seed: int, dim: int = 64) -> list[float]:
    """Return a deterministic unit-norm vector via numpy RNG."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float64)
    norm = np.linalg.norm(v)
    if norm > 0:
        v = v / norm
    return v.tolist()


def _make_db() -> MagicMock:
    """Create a mock Database."""
    return MagicMock()


def _make_vector_doc(file_id: str, seed: int) -> dict:
    """Build a mock vector document with a deterministic vector."""
    return {"file_id": file_id, "vector": _make_vector(seed)}


# ---------------------------------------------------------------------------
# Tests: _compute_recency_weights
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestComputeRecencyWeights:
    """Tests for the private ``_compute_recency_weights`` helper."""

    def test_all_weights_positive(self) -> None:
        """All returned weights are positive for valid plays."""
        now = 2_000_000_000_000
        plays = [
            _make_play("f1", playcount=1, last_played=now - 86_400_000),  # 1 day ago
            _make_play("f2", playcount=5, last_played=now - 86_400_000 * 10),
            _make_play("f3", playcount=10, last_played=now - 86_400_000 * 30),
        ]
        weights = _compute_recency_weights(plays, now, 30.0)
        assert all(w > 0 for w in weights)

    def test_none_last_played_uses_fallback(self) -> None:
        """``last_played=None`` uses ``fallback = half_life_days * 2``."""
        now = 2_000_000_000_000
        play = _make_play("f1", playcount=1, last_played=None)
        weights = _compute_recency_weights([play], now, 30.0)
        # decay_lambda = ln(2) / 30
        # days_since = 30 * 2 = 60
        # w = log(2) * exp(-ln(2)/30 * 60) = log(2) * exp(-2*ln2) = log(2) / 4
        expected = math.log(2) / 4
        assert len(weights) == 1
        assert weights[0] == pytest.approx(expected, rel=1e-12)

    def test_more_recent_higher_weight(self) -> None:
        """More recent plays produce higher weights (same playcount)."""
        now = 2_000_000_000_000
        recent = _make_play("f1", playcount=5, last_played=now - 86_400_000)  # 1 day ago
        old = _make_play("f2", playcount=5, last_played=now - 86_400_000 * 60)  # 60 days ago
        weights = _compute_recency_weights([recent, old], now, 30.0)
        assert weights[0] > weights[1]

    def test_higher_playcount_higher_weight(self) -> None:
        """Higher playcount produces higher weight (same recency)."""
        now = 2_000_000_000_000
        low = _make_play("f1", playcount=1, last_played=now - 86_400_000)  # 1 day ago
        high = _make_play("f2", playcount=99, last_played=now - 86_400_000)  # 1 day ago
        weights = _compute_recency_weights([low, high], now, 30.0)
        assert weights[1] > weights[0]


# ---------------------------------------------------------------------------
# Tests: _compute_weighted_centroid
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestComputeWeightedCentroid:
    """Tests for the private ``_compute_weighted_centroid`` helper."""

    def test_l2_norm_is_one(self) -> None:
        """Returned vector has L2 norm ≈ 1.0 for non-degenerate input."""
        vectors = [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ]
        weights = [1.0, 1.0]
        centroid = _compute_weighted_centroid(vectors, weights)
        norm = math.sqrt(sum(v * v for v in centroid))
        assert norm == pytest.approx(1.0, abs=1e-9)

    def test_equal_weights_produce_arithmetic_mean(self) -> None:
        """Equal weights produce the arithmetic mean (normalized)."""
        vectors = [
            [3.0, 0.0, 0.0],
            [0.0, 4.0, 0.0],
            [0.0, 0.0, 5.0],
        ]
        weights = [1.0, 1.0, 1.0]
        centroid = _compute_weighted_centroid(vectors, weights)
        # arithmetic mean = [1, 4/3, 5/3]
        # L2 norm = sqrt(1 + 16/9 + 25/9) = sqrt(50/9) = sqrt(50)/3
        # normalized centroid = [3/sqrt(50), 4/sqrt(50), 5/sqrt(50)]
        norm_factor = math.sqrt(50)
        expected = [3.0 / norm_factor, 4.0 / norm_factor, 5.0 / norm_factor]
        assert centroid == pytest.approx(expected, rel=1e-9)

    def test_unequal_weights_shift_centroid(self) -> None:
        """Unequal weights shift centroid toward the heavier-weighted vector."""
        vectors = [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ]
        weights = [10.0, 1.0]
        centroid = _compute_weighted_centroid(vectors, weights)
        # Heavier weight on vector A → first dimension should dominate
        assert centroid[0] > centroid[1]

    def test_zero_vectors_no_crash(self) -> None:
        """All zero vectors produce a zero vector (no division-by-zero crash)."""
        vectors = [
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
        ]
        weights = [1.0, 1.0]
        centroid = _compute_weighted_centroid(vectors, weights)
        assert centroid == [0.0, 0.0, 0.0]


# ---------------------------------------------------------------------------
# Tests: compute_taste_profile — early return & basic success
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.mocked
class TestComputeTasteProfile:
    """Tests for the main ``compute_taste_profile`` function."""

    # -- early return paths --

    def test_empty_top_plays_returns_none(self) -> None:
        """Empty ``top_plays`` list returns ``None``."""
        db = _make_db()
        result = compute_taste_profile(
            db,
            "user1",
            [],
            "backbone/1",
            half_life_days=30.0,
            top_n=200,
        )
        assert result is None

    def test_all_plays_have_none_file_id(self) -> None:
        """All plays have ``file_id=None`` → returns ``None``."""
        db = _make_db()
        plays = [_make_play(file_id=None, playcount=1, last_played=1000) for _ in range(5)]
        result = compute_taste_profile(
            db,
            "user1",
            plays,
            "backbone/1",
        )
        assert result is None

    def test_no_vectors_found_returns_none(self) -> None:
        """Resolved plays but cold ops return empty → ``None``."""
        db = _make_db()
        plays = [_make_play(f"f{i}", 1, 1000) for i in range(3)]
        cold_mock = MagicMock()
        cold_mock.get_vectors_by_file_ids.return_value = []

        with patch(
            "nomarr.components.navidrome.taste_profile_comp.get_cold_namespace",
            return_value=cold_mock,
        ):
            result = compute_taste_profile(
                db,
                "user1",
                plays,
                "backbone/1",
            )
        assert result is None

    # -- basic success paths --

    def test_single_genre_one_cluster(self) -> None:
        """Single genre with ≥3 tracks → 1 cluster with matching label."""
        db = _make_db()
        plays = [_make_play(f"f{i}", 5, 100_000_000) for i in range(3)]
        vector_docs = [_make_vector_doc(f"f{i}", i) for i in range(3)]

        cold_mock = MagicMock()
        cold_mock.get_vectors_by_file_ids.return_value = vector_docs
        genre_map = {f"f{i}": {"Rock"} for i in range(3)}

        with (
            patch(
                "nomarr.components.navidrome.taste_profile_comp.get_cold_namespace",
                return_value=cold_mock,
            ),
            patch(
                "nomarr.components.navidrome.taste_profile_comp.get_tag_values_grouped_by_file",
                return_value=genre_map,
            ),
        ):
            result = compute_taste_profile(
                db,
                "user1",
                plays,
                "backbone/1",
            )

        assert result is not None
        assert len(result["clusters"]) == 1
        assert result["clusters"][0]["label"] == "Rock"
        assert result["clusters"][0]["track_count"] == 3
        assert result["user_id"] == "user1"
        assert result["backbone_id"] == "backbone/1"
        # library_key removed per ADR-036

    def test_multiple_genres_multiple_clusters(self) -> None:
        """Multiple genres each with ≥3 tracks → one cluster per genre."""
        db = _make_db()
        plays = [_make_play(f"r{i}", 5, 100_000_000) for i in range(3)] + [
            _make_play(f"j{i}", 5, 100_000_000) for i in range(3)
        ]
        vector_docs = [_make_vector_doc(f"r{i}", i) for i in range(3)] + [
            _make_vector_doc(f"j{i}", i + 100) for i in range(3)
        ]
        cold_mock = MagicMock()
        cold_mock.get_vectors_by_file_ids.return_value = vector_docs
        genre_map = {}
        for i in range(3):
            genre_map[f"r{i}"] = {"Rock"}
        for i in range(3):
            genre_map[f"j{i}"] = {"Jazz"}

        with (
            patch(
                "nomarr.components.navidrome.taste_profile_comp.get_cold_namespace",
                return_value=cold_mock,
            ),
            patch(
                "nomarr.components.navidrome.taste_profile_comp.get_tag_values_grouped_by_file",
                return_value=genre_map,
            ),
        ):
            result = compute_taste_profile(
                db,
                "user1",
                plays,
                "backbone/1",
            )

        assert result is not None
        labels = {c["label"] for c in result["clusters"]}
        assert labels == {"Rock", "Jazz"}
        assert len(result["clusters"]) == 2

    def test_genre_with_two_tracks_skipped(self) -> None:
        """Genre with only 2 tracks is skipped (not in returned clusters)."""
        db = _make_db()
        # Rock has 2 tracks (< 3) → skipped; Jazz has 3 tracks → included
        plays = [_make_play(f"r{i}", 5, 100_000_000) for i in range(2)] + [
            _make_play(f"j{i}", 5, 100_000_000) for i in range(3)
        ]
        vector_docs = [_make_vector_doc(f"r{i}", i) for i in range(2)] + [
            _make_vector_doc(f"j{i}", i + 100) for i in range(3)
        ]
        cold_mock = MagicMock()
        cold_mock.get_vectors_by_file_ids.return_value = vector_docs
        genre_map = {}
        for i in range(2):
            genre_map[f"r{i}"] = {"Rock"}
        for i in range(3):
            genre_map[f"j{i}"] = {"Jazz"}

        with (
            patch(
                "nomarr.components.navidrome.taste_profile_comp.get_cold_namespace",
                return_value=cold_mock,
            ),
            patch(
                "nomarr.components.navidrome.taste_profile_comp.get_tag_values_grouped_by_file",
                return_value=genre_map,
            ),
        ):
            result = compute_taste_profile(
                db,
                "user1",
                plays,
                "backbone/1",
            )

        assert result is not None
        labels = {c["label"] for c in result["clusters"]}
        assert labels == {"Jazz"}
        assert len(result["clusters"]) == 1

    def test_partial_vector_resolution(self) -> None:
        """Some resolved plays have vectors, others don't — only paired ones count."""
        plays = [
            _make_play(f"f{i}", 5, 1000 + i * 100)
            for i in range(10)  # 10 plays, all resolved
        ]
        # Only return vectors for first 7 plays
        vector_docs = [_make_vector_doc(f"f{i}", i) for i in range(7)]

        mock_cold_ops = MagicMock()
        mock_cold_ops.get_vectors_by_file_ids.return_value = list(vector_docs)
        mock_get_cold = patch(
            "nomarr.components.navidrome.taste_profile_comp.get_cold_namespace",
            return_value=mock_cold_ops,
        )
        mock_tags = patch(
            "nomarr.components.navidrome.taste_profile_comp.get_tag_values_grouped_by_file",
            return_value={f"f{i}": {"rock"} for i in range(10)},
        )

        with mock_get_cold, mock_tags:
            result = compute_taste_profile(
                MagicMock(),
                "user1",
                plays,
                "bb1",
                half_life_days=30,
                top_n=200,
            )

        assert result is not None
        # Only 7 of 10 should be paired (3 dropped for missing vectors)
        assert result["track_count"] == 7

    def test_vector_doc_missing_vector_key(self) -> None:
        """Vector docs without 'vector' key are silently skipped."""
        plays = [_make_play(f"f{i}", 5, 1000 + i * 100) for i in range(5)]

        mock_cold_ops = MagicMock()
        # One doc has no "vector" key
        mock_cold_ops.get_vectors_by_file_ids.return_value = [
            {"file_id": "f0", "vector": _make_vector(0)},
            {"file_id": "f1"},  # no vector key!
            {"file_id": "f2", "vector": _make_vector(2)},
            {"file_id": "f3", "vector": _make_vector(3)},
            {"file_id": "f4", "vector": _make_vector(4)},
        ]
        mock_get_cold = patch(
            "nomarr.components.navidrome.taste_profile_comp.get_cold_namespace",
            return_value=mock_cold_ops,
        )
        mock_tags = patch(
            "nomarr.components.navidrome.taste_profile_comp.get_tag_values_grouped_by_file",
            return_value={f"f{i}": {"rock"} for i in range(5)},
        )

        with mock_get_cold, mock_tags:
            result = compute_taste_profile(
                MagicMock(),
                "user1",
                plays,
                "bb1",
                half_life_days=30,
                top_n=200,
            )

        assert result is not None
        # f1 should be dropped (no vector key), so 4 tracks remain
        assert result["track_count"] == 4


# ---------------------------------------------------------------------------
# Tests: compute_taste_profile — untagged cluster logic
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.mocked
class TestUntaggedCluster:
    """Tests for the untagged cluster logic in ``compute_taste_profile``."""

    def test_untagged_above_threshold_includes_cluster(self) -> None:
        """Untagged fraction >5% and ≥3 tracks → includes 'untagged' cluster."""
        db = _make_db()
        # 46 tagged + 4 untagged = 50 total → 4/50 = 8% > 5%, 4 >= 3
        tagged_count = 46
        untagged_count = 4
        plays = [_make_play(f"t{i}", 5, 100_000_000) for i in range(tagged_count)] + [
            _make_play(f"u{i}", 5, 100_000_000) for i in range(untagged_count)
        ]
        vector_docs = [_make_vector_doc(f"t{i}", i) for i in range(tagged_count)] + [
            _make_vector_doc(f"u{i}", i + 1000) for i in range(untagged_count)
        ]
        cold_mock = MagicMock()
        cold_mock.get_vectors_by_file_ids.return_value = vector_docs
        genre_map = {f"t{i}": {"Rock"} for i in range(tagged_count)}

        with (
            patch(
                "nomarr.components.navidrome.taste_profile_comp.get_cold_namespace",
                return_value=cold_mock,
            ),
            patch(
                "nomarr.components.navidrome.taste_profile_comp.get_tag_values_grouped_by_file",
                return_value=genre_map,
            ),
        ):
            result = compute_taste_profile(
                db,
                "user1",
                plays,
                "backbone/1",
            )

        assert result is not None
        labels = {c["label"] for c in result["clusters"]}
        assert "untagged" in labels

    def test_untagged_below_threshold_no_cluster(self) -> None:
        """Untagged fraction ≤5% → no 'untagged' cluster."""
        db = _make_db()
        # 48 tagged + 2 untagged = 50 total → 2/50 = 4% ≤ 5%
        tagged_count = 48
        untagged_count = 2
        plays = [_make_play(f"t{i}", 5, 100_000_000) for i in range(tagged_count)] + [
            _make_play(f"u{i}", 5, 100_000_000) for i in range(untagged_count)
        ]
        vector_docs = [_make_vector_doc(f"t{i}", i) for i in range(tagged_count)] + [
            _make_vector_doc(f"u{i}", i + 1000) for i in range(untagged_count)
        ]
        cold_mock = MagicMock()
        cold_mock.get_vectors_by_file_ids.return_value = vector_docs
        genre_map = {f"t{i}": {"Rock"} for i in range(tagged_count)}

        with (
            patch(
                "nomarr.components.navidrome.taste_profile_comp.get_cold_namespace",
                return_value=cold_mock,
            ),
            patch(
                "nomarr.components.navidrome.taste_profile_comp.get_tag_values_grouped_by_file",
                return_value=genre_map,
            ),
        ):
            result = compute_taste_profile(
                db,
                "user1",
                plays,
                "backbone/1",
            )

        assert result is not None
        labels = {c["label"] for c in result["clusters"]}
        assert "untagged" not in labels

    def test_untagged_less_than_three_no_cluster(self) -> None:
        """Untagged <3 tracks → no 'untagged' cluster regardless of fraction."""
        db = _make_db()
        # 3 tagged + 2 untagged = 5 total → 2/5 = 40% > 5%, but 2 < 3
        tagged_count = 3
        untagged_count = 2
        plays = [_make_play(f"t{i}", 5, 100_000_000) for i in range(tagged_count)] + [
            _make_play(f"u{i}", 5, 100_000_000) for i in range(untagged_count)
        ]
        vector_docs = [_make_vector_doc(f"t{i}", i) for i in range(tagged_count)] + [
            _make_vector_doc(f"u{i}", i + 1000) for i in range(untagged_count)
        ]
        cold_mock = MagicMock()
        cold_mock.get_vectors_by_file_ids.return_value = vector_docs
        genre_map = {f"t{i}": {"Rock"} for i in range(tagged_count)}

        with (
            patch(
                "nomarr.components.navidrome.taste_profile_comp.get_cold_namespace",
                return_value=cold_mock,
            ),
            patch(
                "nomarr.components.navidrome.taste_profile_comp.get_tag_values_grouped_by_file",
                return_value=genre_map,
            ),
        ):
            result = compute_taste_profile(
                db,
                "user1",
                plays,
                "backbone/1",
            )

        assert result is not None
        labels = {c["label"] for c in result["clusters"]}
        assert "untagged" not in labels


# ---------------------------------------------------------------------------
# Tests: compute_taste_profile — capping, multi-tag, edge cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.mocked
class TestTasteProfileEdgeCases:
    """Tests for capping, multi-tag determinism, and all-skipped edge case."""

    def test_cluster_capping(self) -> None:
        """15 genres with ≥3 tracks, ``pp_max_clusters=5`` → 5 clusters."""
        db = _make_db()
        genres = [f"Genre{g}" for g in range(15)]
        plays = []
        vector_docs = []
        genre_map = {}
        seed = 0
        for genre in genres:
            for t in range(3):
                fid = f"{genre.lower()}_t{t}"
                plays.append(_make_play(fid, 5, 100_000_000))
                vector_docs.append(_make_vector_doc(fid, seed))
                seed += 1
                genre_map[fid] = {genre}

        cold_mock = MagicMock()
        cold_mock.get_vectors_by_file_ids.return_value = vector_docs

        with (
            patch(
                "nomarr.components.navidrome.taste_profile_comp.get_cold_namespace",
                return_value=cold_mock,
            ),
            patch(
                "nomarr.components.navidrome.taste_profile_comp.get_tag_values_grouped_by_file",
                return_value=genre_map,
            ),
        ):
            result = compute_taste_profile(
                db,
                "user1",
                plays,
                "backbone/1",
                pp_max_clusters=5,
            )

        assert result is not None
        assert len(result["clusters"]) == 5
        # Verify sorted by total_weight descending
        weights = [c["total_weight"] for c in result["clusters"]]
        assert weights == sorted(weights, reverse=True)

    def test_all_genres_skipped_returns_none(self) -> None:
        """All genres have <3 tracks and no untagged → returns ``None``."""
        db = _make_db()
        # 2 tracks per genre, 2 genres = 4 tracks total
        plays = [_make_play(f"r{i}", 5, 100_000_000) for i in range(2)] + [
            _make_play(f"j{i}", 5, 100_000_000) for i in range(2)
        ]
        vector_docs = [_make_vector_doc(f"r{i}", i) for i in range(2)] + [
            _make_vector_doc(f"j{i}", i + 100) for i in range(2)
        ]
        cold_mock = MagicMock()
        cold_mock.get_vectors_by_file_ids.return_value = vector_docs
        genre_map = {
            "r0": {"Rock"},
            "r1": {"Rock"},
            "j0": {"Jazz"},
            "j1": {"Jazz"},
        }

        with (
            patch(
                "nomarr.components.navidrome.taste_profile_comp.get_cold_namespace",
                return_value=cold_mock,
            ),
            patch(
                "nomarr.components.navidrome.taste_profile_comp.get_tag_values_grouped_by_file",
                return_value=genre_map,
            ),
        ):
            result = compute_taste_profile(
                db,
                "user1",
                plays,
                "backbone/1",
            )

        assert result is None

    def test_multi_tag_determinism(self) -> None:
        """Multi-tagged track assigned to first sorted genre (alphabetical)."""
        db = _make_db()
        # f0 has {"Rock", "Pop"} → primary = "Pop" (first sorted)
        # f1, f2 have {"Pop"} → Pop has 3 tracks → cluster
        # f3, f4, f5 have {"Jazz"} → Jazz has 3 tracks → cluster
        plays = [
            _make_play("f0", 5, 100_000_000),
            _make_play("f1", 5, 100_000_000),
            _make_play("f2", 5, 100_000_000),
            _make_play("f3", 5, 100_000_000),
            _make_play("f4", 5, 100_000_000),
            _make_play("f5", 5, 100_000_000),
        ]
        vector_docs = [_make_vector_doc(f"f{i}", i) for i in range(6)]
        cold_mock = MagicMock()
        cold_mock.get_vectors_by_file_ids.return_value = vector_docs
        genre_map = {
            "f0": {"Rock", "Pop"},
            "f1": {"Pop"},
            "f2": {"Pop"},
            "f3": {"Jazz"},
            "f4": {"Jazz"},
            "f5": {"Jazz"},
        }

        with (
            patch(
                "nomarr.components.navidrome.taste_profile_comp.get_cold_namespace",
                return_value=cold_mock,
            ),
            patch(
                "nomarr.components.navidrome.taste_profile_comp.get_tag_values_grouped_by_file",
                return_value=genre_map,
            ),
        ):
            result = compute_taste_profile(
                db,
                "user1",
                plays,
                "backbone/1",
            )

        assert result is not None
        labels = {c["label"] for c in result["clusters"]}
        # Pop cluster must exist (proves f0 assigned to "Pop", not "Rock")
        assert "Pop" in labels
        assert "Jazz" in labels
