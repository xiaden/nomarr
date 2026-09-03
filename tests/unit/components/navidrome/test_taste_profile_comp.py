"""Unit tests for taste profile computation component.

Tests cover:
- ``_compute_recency_weights`` (pure function)
- ``_compute_weighted_centroid`` (pure function)
- ``compute_taste_profile`` (requires mocking DB/component calls)

The component now consumes the typed vector domain contract: each play's
``file_id`` is bridged through ``db.library.resolve_song_identity`` and its
embedding read via ``db.ml.get_song_vector`` returning a
:class:`~nomarr.helpers.dataclasses.vector_dataclass.SongVector`.  Tests mock
those authoritative methods with domain fixtures (``SongIdentity`` /
``SongVector``) — no raw persistence rows or ``song_id``/``embedding`` dict
keys.
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
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.vector_dataclass import SongVector

# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------

TAGS_PATH = "nomarr.components.navidrome.taste_profile_comp"

_LIB_ID = LibraryIdentity(name="test-lib", root_path="/test-lib")


def _make_play(
    file_id: int | None,
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


def _song_identity(fid: int) -> SongIdentity:
    """Build a deterministic natural identity encoding ``fid`` in its path."""
    return SongIdentity(library=_LIB_ID, normalized_path=f"rel/{fid}.mp3")


def _fid_from_song(song: SongIdentity) -> int:
    """Reverse the encoding in :func:`_song_identity`."""
    return int(song.normalized_path.removeprefix("rel/").removesuffix(".mp3"))


def _make_db() -> MagicMock:
    """Create a mock Database (identity/vector reads configured per-test)."""
    db = MagicMock()
    db.ml.get_song_vector = MagicMock(return_value=None)
    db.library.resolve_song_identity = MagicMock(return_value=None)
    return db


def _configure_typed_vectors(db: MagicMock, vectors: dict[int, list[float]]) -> None:
    """Bridge each configured ``fid`` to a typed :class:`SongVector`.

    ``db.library.resolve_song_identity`` returns the natural identity for any
    file handle; ``db.ml.get_song_vector`` returns a ``SongVector`` carrying the
    stored embedding only for handles present in ``vectors`` (absent => no
    embedding, mirroring the legacy empty-result behaviour).
    """

    def _resolve(fid: int) -> SongIdentity | None:
        return _song_identity(fid)

    def _get_song_vector(backbone: str, song: SongIdentity) -> SongVector | None:
        vec = vectors.get(_fid_from_song(song))
        if vec is None:
            return None
        return SongVector(
            song=song,
            backbone=backbone,
            vector=tuple(vec),
            model_suite_hash=None,
            num_segments=None,
            segmentation_hash=None,
            genres=None,
        )

    db.library.resolve_song_identity = MagicMock(side_effect=_resolve)
    db.ml.get_song_vector = MagicMock(side_effect=_get_song_vector)


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
            _make_play(1, playcount=1, last_played=now - 86_400_000),  # 1 day ago
            _make_play(2, playcount=5, last_played=now - 86_400_000 * 10),
            _make_play(3, playcount=10, last_played=now - 86_400_000 * 30),
        ]
        weights = _compute_recency_weights(plays, now, 30.0)
        assert all(w > 0 for w in weights)

    def test_none_last_played_uses_fallback(self) -> None:
        """``last_played=None`` uses ``fallback = half_life_days * 2``."""
        now = 2_000_000_000_000
        play = _make_play(1, playcount=1, last_played=None)
        weights = _compute_recency_weights([play], now, 30.0)
        expected = math.log(2) / 4
        assert len(weights) == 1
        assert weights[0] == pytest.approx(expected, rel=1e-12)

    def test_more_recent_higher_weight(self) -> None:
        """More recent plays produce higher weights (same playcount)."""
        now = 2_000_000_000_000
        recent = _make_play(1, playcount=5, last_played=now - 86_400_000)
        old = _make_play(2, playcount=5, last_played=now - 86_400_000 * 60)
        weights = _compute_recency_weights([recent, old], now, 30.0)
        assert weights[0] > weights[1]

    def test_higher_playcount_higher_weight(self) -> None:
        """Higher playcount produces higher weight (same recency)."""
        now = 2_000_000_000_000
        low = _make_play(1, playcount=1, last_played=now - 86_400_000)
        high = _make_play(2, playcount=99, last_played=now - 86_400_000)
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
        """Resolved plays but no file resolves to an embedding → ``None``."""
        db = _make_db()
        plays = [_make_play(i, 1, 1000) for i in range(1, 4)]
        _configure_typed_vectors(db, {})

        with patch(f"{TAGS_PATH}.get_tag_values_grouped_by_file", new=MagicMock(return_value={})):
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
        plays = [_make_play(i, 5, 100_000_000) for i in range(1, 4)]
        _configure_typed_vectors(db, {i: _make_vector(i) for i in range(1, 4)})
        genre_map = {i: {"Rock"} for i in range(1, 4)}

        with patch(f"{TAGS_PATH}.get_tag_values_grouped_by_file", new=MagicMock(return_value=genre_map)):
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

    def test_multiple_genres_multiple_clusters(self) -> None:
        """Two genres each with ≥3 tracks → 2 clusters sorted by weight."""
        db = _make_db()
        plays = [_make_play(i, 5, 100_000_000) for i in range(1, 4)] + [
            _make_play(i + 100, 20, 100_000_000) for i in range(1, 4)
        ]
        vectors: dict[int, list[float]] = {i: _make_vector(i) for i in range(1, 4)}
        vectors.update({i + 100: _make_vector(i + 100) for i in range(1, 4)})
        _configure_typed_vectors(db, vectors)
        genre_map: dict[int, set[str]] = {}
        for i in range(1, 4):
            genre_map[i] = {"Rock"}
        for i in range(1, 4):
            genre_map[i + 100] = {"Electronic"}

        with patch(f"{TAGS_PATH}.get_tag_values_grouped_by_file", new=MagicMock(return_value=genre_map)):
            result = compute_taste_profile(
                db,
                "user1",
                plays,
                "backbone/1",
            )

        assert result is not None
        assert len(result["clusters"]) == 2
        # Electronic has higher playcount → higher weight → sorted first
        labels = [c["label"] for c in result["clusters"]]
        assert labels[0] == "Electronic"
        assert labels[1] == "Rock"
        assert result["clusters"][0]["track_count"] == 3
        assert result["clusters"][1]["track_count"] == 3

    def test_genre_with_two_tracks_skipped(self) -> None:
        """Genre with only 2 tracks → skipped. 3-track genre included."""
        plays = [_make_play(i, 5, 100_000_000) for i in range(1, 3)] + [
            _make_play(i + 100, 5, 100_000_000) for i in range(1, 4)
        ]
        vectors: dict[int, list[float]] = {i: _make_vector(i) for i in range(1, 3)}
        vectors.update({i + 100: _make_vector(i + 100) for i in range(1, 4)})
        db = _make_db()
        _configure_typed_vectors(db, vectors)
        genre_map: dict[int, set[str]] = {}
        for i in range(1, 3):
            genre_map[i] = {"Rock"}
        for i in range(1, 4):
            genre_map[i + 100] = {"Electronic"}

        with patch(f"{TAGS_PATH}.get_tag_values_grouped_by_file", new=MagicMock(return_value=genre_map)):
            result = compute_taste_profile(
                db,
                "user1",
                plays,
                "backbone/1",
            )

        assert result is not None
        assert len(result["clusters"]) == 1
        assert result["clusters"][0]["label"] == "Electronic"

    def test_partial_vector_resolution(self) -> None:
        """Only 7 of 10 plays resolve to embeddings → only those 7 contribute."""
        plays = [_make_play(i, 5, 1000 + i * 100) for i in range(1, 11)]
        db = _make_db()
        _configure_typed_vectors(db, {i: _make_vector(i) for i in range(1, 8)})

        with patch(
            f"{TAGS_PATH}.get_tag_values_grouped_by_file",
            new=MagicMock(
                return_value={i: {"rock"} for i in range(1, 11)},
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
        assert result["clusters"][0]["track_count"] == 7

    def test_track_without_embedding_is_skipped(self) -> None:
        """A play whose file resolves but has no SongVector is silently skipped."""
        plays = [_make_play(i, 5, 1000 + i * 100) for i in range(1, 6)]

        db = _make_db()
        # Only files 1-2 carry an embedding; files 3-5 resolve but have none.
        _configure_typed_vectors(db, {i: _make_vector(i) for i in range(1, 3)})

        with patch(
            f"{TAGS_PATH}.get_tag_values_grouped_by_file",
            new=MagicMock(
                return_value={i: {"rock"} for i in range(1, 6)},
            ),
        ):
            result = compute_taste_profile(
                db,
                "user1",
                plays,
                "backbone/1",
            )

        # Only 2 plays carry vectors (<3) → no cluster
        assert result is None

    def test_unresolved_file_handle_is_skipped(self) -> None:
        """A play whose file_id does not resolve to an identity is skipped."""
        plays = [_make_play(i, 5, 1000 + i * 100) for i in range(1, 6)]

        db = _make_db()

        # resolve returns an identity for file 1 only (never for the rest).
        def _resolve(fid: int) -> SongIdentity | None:
            return _song_identity(fid) if fid == 1 else None

        db.library.resolve_song_identity = MagicMock(side_effect=_resolve)
        db.ml.get_song_vector = MagicMock(
            side_effect=lambda _backbone, song: SongVector(
                song=song,
                backbone=_backbone,
                vector=tuple(_make_vector(_fid_from_song(song))),
                model_suite_hash=None,
                num_segments=None,
                segmentation_hash=None,
                genres=None,
            )
        )

        with patch(
            f"{TAGS_PATH}.get_tag_values_grouped_by_file",
            new=MagicMock(
                return_value={i: {"rock"} for i in range(1, 6)},
            ),
        ):
            result = compute_taste_profile(
                db,
                "user1",
                plays,
                "backbone/1",
            )

        # Only file 1 resolves → <3 paired → no cluster
        assert result is None

    # -- untagged cluster tests --

    def test_untagged_above_threshold_includes_cluster(self) -> None:
        """≥3 untagged tracks with embeddings → untagged cluster."""
        db = _make_db()
        plays = [_make_play(i, 5, 100_000_000) for i in range(1, 10)]
        _configure_typed_vectors(db, {i: _make_vector(i) for i in range(1, 10)})

        # Only 5 tracks have genre tags
        genre_map: dict[int, set[str]] = {}
        for i in range(1, 6):
            genre_map[i] = {"Rock"}

        with patch(f"{TAGS_PATH}.get_tag_values_grouped_by_file", new=MagicMock(return_value=genre_map)):
            result = compute_taste_profile(
                db,
                "user1",
                plays,
                "backbone/1",
            )

        assert result is not None
        labels = [c["label"] for c in result["clusters"]]
        assert "Rock" in labels
        assert "untagged" in labels

    def test_untagged_below_threshold_no_cluster(self) -> None:
        """Only 2 untagged tracks (<3) → no untagged cluster."""
        db = _make_db()
        plays = [_make_play(i, 5, 100_000_000) for i in range(1, 6)]
        _configure_typed_vectors(db, {i: _make_vector(i) for i in range(1, 6)})

        genre_map: dict[int, set[str]] = {}
        for i in range(1, 4):
            genre_map[i] = {"Rock"}

        with patch(f"{TAGS_PATH}.get_tag_values_grouped_by_file", new=MagicMock(return_value=genre_map)):
            result = compute_taste_profile(
                db,
                "user1",
                plays,
                "backbone/1",
            )

        assert result is not None
        labels = [c["label"] for c in result["clusters"]]
        assert "untagged" not in labels

    def test_untagged_less_than_three_no_cluster(self) -> None:
        """<3 untagged tracks → no untagged cluster regardless of threshold."""
        db = _make_db()
        plays = [_make_play(i, 5, 100_000_000) for i in range(1, 5)]
        _configure_typed_vectors(db, {i: _make_vector(i) for i in range(1, 5)})

        genre_map: dict[int, set[str]] = {}
        for i in range(1, 3):
            genre_map[i] = {"Rock"}

        with patch(f"{TAGS_PATH}.get_tag_values_grouped_by_file", new=MagicMock(return_value=genre_map)):
            result = compute_taste_profile(
                db,
                "user1",
                plays,
                "backbone/1",
            )

        labels = [c["label"] for c in result["clusters"]] if result else []
        assert "untagged" not in labels

    def test_cluster_capping(self) -> None:
        """15 genres but pp_max_clusters=5 → top 5 clusters only."""
        db = _make_db()
        genres = [f"Genre{g}" for g in range(1, 16)]
        plays = []
        vectors: dict[int, list[float]] = {}
        genre_map: dict[int, set[str]] = {}
        seed = 0
        fid = 1
        for genre in genres:
            for _t in range(1, 4):
                plays.append(_make_play(fid, playcount=fid, last_played=100_000_000))
                vectors[fid] = _make_vector(seed)
                genre_map[fid] = {genre}
                seed += 1
                fid += 1

        _configure_typed_vectors(db, vectors)

        with patch(f"{TAGS_PATH}.get_tag_values_grouped_by_file", new=MagicMock(return_value=genre_map)):
            result = compute_taste_profile(
                db,
                "user1",
                plays,
                "backbone/1",
                pp_max_clusters=5,
            )

        assert result is not None
        assert len(result["clusters"]) == 5

    def test_all_genres_skipped_returns_none(self) -> None:
        """All genres have <3 tracks → no clusters → ``None``."""
        plays = [
            _make_play(1, 5, 100_000_000),
            _make_play(2, 5, 100_000_000),
            _make_play(3, 5, 100_000_000),
            _make_play(4, 5, 100_000_000),
            _make_play(5, 5, 100_000_000),
            _make_play(6, 5, 100_000_000),
        ]
        db = _make_db()
        _configure_typed_vectors(db, {i: _make_vector(i) for i in range(1, 7)})
        genre_map = {1: {"A"}, 2: {"B"}, 3: {"C"}, 4: {"D"}, 5: {"E"}, 6: {"F"}}

        with patch(f"{TAGS_PATH}.get_tag_values_grouped_by_file", new=MagicMock(return_value=genre_map)):
            result = compute_taste_profile(
                db,
                "user1",
                plays,
                "backbone/1",
            )

        assert result is None

    def test_multi_tag_determinism(self) -> None:
        """Two genres = 6 tracks total → both included as one cluster each."""
        plays = [_make_play(i, 5, 100_000_000) for i in range(1, 4)] + [
            _make_play(i + 100, 5, 100_000_000) for i in range(1, 4)
        ]
        vectors: dict[int, list[float]] = {i: _make_vector(i) for i in range(1, 4)}
        vectors.update({i + 100: _make_vector(i + 100) for i in range(1, 4)})
        db = _make_db()
        _configure_typed_vectors(db, vectors)
        genre_map = {1: {"Jazz"}, 2: {"Jazz"}, 3: {"Jazz"}, 101: {"Funk"}, 102: {"Funk"}, 103: {"Funk"}}

        with patch(f"{TAGS_PATH}.get_tag_values_grouped_by_file", new=MagicMock(return_value=genre_map)):
            result = compute_taste_profile(
                db,
                "user1",
                plays,
                "backbone/1",
            )

        assert result is not None
        labels = {c["label"] for c in result["clusters"]}
        assert "Jazz" in labels
        assert "Funk" in labels
