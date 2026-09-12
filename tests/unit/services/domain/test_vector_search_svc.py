"""Tests for the typed vector search service.

The service accepts a semantic ``SongIdentity`` locator, reads the typed
``db.ml`` vector intents (never an integer storage id), and returns
``VectorMatch`` values carrying the matched locator. Consumers encode the
opaque ``nom1`` wire token only at the interface boundary.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.vector_dataclass import SongVector, VectorMatch
from nomarr.services.domain.vector_search_svc import (
    MissingSeedVectorError,
    VectorIndexUnavailableError,
    VectorSearchService,
)

_LIB_ID = LibraryIdentity(library_uuid="6313b0d3-d270-57a8-9e0d-21e8255107e3", name="Music", root_path="/music")
_SEED_SONG = SongIdentity(library=_LIB_ID, normalized_path="songs/seed.mp3")


def _sid(path: str) -> SongIdentity:
    return SongIdentity(library=_LIB_ID, normalized_path=path)


def _sv(song: SongIdentity, vector: tuple[float, ...]) -> SongVector:
    return SongVector(
        song=song,
        backbone="effnet",
        vector=vector,
        model_suite_hash="suite",
        num_segments=1,
        segmentation_hash=None,
        genres=None,
    )


def _make_db() -> MagicMock:
    """Build a mock Database over the typed db.ml surface."""
    db = MagicMock()
    db.ml.has_vector_index.return_value = True
    db.ml.get_song_vector.return_value = _sv(_SEED_SONG, (0.1, 0.2, 0.3))
    db.ml.search_similar_vectors.return_value = ()
    return db


def _make_service(db: MagicMock) -> VectorSearchService:
    return VectorSearchService(db=db, config_svc=MagicMock())


def _match(path: str, score: float, vector: tuple[float, ...] | None) -> VectorMatch:
    return VectorMatch(song=_sid(path), backbone="effnet", score=score, vector=vector)


@pytest.mark.unit
class TestSearchSimilarTracksErrors:
    """503-before-404 and missing-seed behavior."""

    def test_index_unavailable_raises_before_seed_lookup(self) -> None:
        db = _make_db()
        db.ml.has_vector_index.return_value = False
        service = _make_service(db)

        with pytest.raises(VectorIndexUnavailableError, match="No vector index available"):
            service.search_similar_tracks(_SEED_SONG, "effnet", limit=10)

        db.ml.get_song_vector.assert_not_called()

    def test_song_without_vector_raises_missing_seed(self) -> None:
        db = _make_db()
        db.ml.get_song_vector.return_value = None
        service = _make_service(db)

        with pytest.raises(MissingSeedVectorError, match="No vector found for backbone 'effnet'"):
            service.search_similar_tracks(_SEED_SONG, "effnet", limit=10)

        db.ml.search_similar_vectors.assert_not_called()

    def test_missing_seed_error_does_not_disclose_an_integer_handle(self) -> None:
        db = _make_db()
        db.ml.get_song_vector.return_value = None
        service = _make_service(db)

        with pytest.raises(MissingSeedVectorError) as exc_info:
            service.search_similar_tracks(_SEED_SONG, "effnet", limit=10)

        assert "1" not in str(exc_info.value)


@pytest.mark.unit
class TestSearchSimilarTracksSuccess:
    """Typed search and locator-carrying results."""

    def test_searches_with_semantic_locator_and_returns_matches(self) -> None:
        db = _make_db()
        match = _match("songs/seed.mp3", 0.9, (0.1, 0.2, 0.3))
        db.ml.search_similar_vectors.return_value = (match,)
        service = _make_service(db)

        results = service.search_similar_tracks(_SEED_SONG, "effnet", limit=10)

        db.ml.get_song_vector.assert_called_once_with("effnet", _SEED_SONG)
        assert isinstance(db.ml.get_song_vector.call_args.args[1], SongIdentity)
        db.ml.search_similar_vectors.assert_called_once_with(
            "effnet",
            (0.1, 0.2, 0.3),
            limit=10,
            min_score=0.0,
            include_vector=True,
        )
        assert results == [match]

    def test_filters_and_sorts_matches(self) -> None:
        db = _make_db()
        db.ml.search_similar_vectors.return_value = (
            _match("songs/a.mp3", 0.7, (0.7, 0.3)),
            _match("songs/b.mp3", 0.4, (0.4, 0.6)),
            _match("songs/c.mp3", -0.1, (0.0, 1.0)),
        )
        service = _make_service(db)

        results = service.search_similar_tracks(_SEED_SONG, "effnet", limit=10, min_score=0.6)

        assert results == [_match("songs/a.mp3", 0.7, (0.7, 0.3))]

    def test_zero_threshold_keeps_zero_similarity_and_negative_threshold_keeps_negative(self) -> None:
        db = _make_db()
        db.ml.search_similar_vectors.return_value = (
            _match("songs/a.mp3", 0.0, (0.0, 1.0)),
            _match("songs/b.mp3", -0.2, (1.0, 0.0)),
        )
        service = _make_service(db)

        zero_results = service.search_similar_tracks(_SEED_SONG, "effnet", limit=10, min_score=0.0)
        negative_results = service.search_similar_tracks(_SEED_SONG, "effnet", limit=10, min_score=-0.2)

        assert zero_results == [_match("songs/a.mp3", 0.0, (0.0, 1.0))]
        assert negative_results == [
            _match("songs/a.mp3", 0.0, (0.0, 1.0)),
            _match("songs/b.mp3", -0.2, (1.0, 0.0)),
        ]
        assert db.ml.search_similar_vectors.call_args_list[0].kwargs["min_score"] == 0.0
        assert db.ml.search_similar_vectors.call_args_list[1].kwargs["min_score"] == -0.2

    def test_default_min_score_keeps_zero_drops_negative(self) -> None:
        db = _make_db()
        db.ml.search_similar_vectors.return_value = (
            _match("songs/a.mp3", 0.0, (0.0, 1.0)),
            _match("songs/b.mp3", -0.2, (1.0, 0.0)),
        )
        service = _make_service(db)

        results = service.search_similar_tracks(_SEED_SONG, "effnet", limit=10)

        assert results == [_match("songs/a.mp3", 0.0, (0.0, 1.0))]

    def test_empty_matches_returns_empty(self) -> None:
        db = _make_db()
        service = _make_service(db)

        results = service.search_similar_tracks(_SEED_SONG, "effnet", limit=10)

        assert results == []

    def test_skips_match_without_vector_payload(self) -> None:
        db = _make_db()
        db.ml.search_similar_vectors.return_value = (
            _match("songs/a.mp3", 0.9, None),
            _match("songs/b.mp3", 0.8, (0.1, 0.9)),
        )
        service = _make_service(db)

        results = service.search_similar_tracks(_SEED_SONG, "effnet", limit=10)

        assert results == [_match("songs/b.mp3", 0.8, (0.1, 0.9))]


@pytest.mark.unit
class TestGetTrackVector:
    """Service track-vector method reads the typed db.ml vector by locator."""

    def test_reads_song_vector_by_locator(self) -> None:
        db = _make_db()
        song_vector = _sv(_SEED_SONG, (0.5, 0.5))
        db.ml.get_song_vector.return_value = song_vector
        service = _make_service(db)

        result = service.get_track_vector("effnet", _SEED_SONG)

        assert result is song_vector
        db.ml.get_song_vector.assert_called_once_with("effnet", _SEED_SONG)

    def test_returns_none_when_no_vector(self) -> None:
        db = _make_db()
        db.ml.get_song_vector.return_value = None
        service = _make_service(db)

        assert service.get_track_vector("effnet", _SEED_SONG) is None
