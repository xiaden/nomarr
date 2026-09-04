"""Tests for the typed vector search service.

The service resolves integer file handles to a natural ``SongIdentity`` through
authoritative ``db.library``, calls the typed ``db.ml`` read intents (never an
integer storage id), filters/sorts on the clamped ``VectorMatch.score``, and
adapts each result's identity back to a transport ``file_id`` only at the
service/transport boundary.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.vector_dataclass import SongVector, VectorMatch
from nomarr.services.domain.vector_search_svc import (
    MissingSeedVectorError,
    VectorIndexUnavailableError,
    VectorSearchService,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

_LIB_ID = LibraryIdentity(name="Music", root_path="/music")
_SEED_ID = 1
_SEED_SONG = SongIdentity(library=_LIB_ID, normalized_path="songs/seed.mp3")
_FILE_BY_PATH = {
    "songs/seed.mp3": 1,
    "songs/a.mp3": 3,
    "songs/b.mp3": 2,
    "songs/c.mp3": 5,
}


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


def _make_db() -> Database:
    """Build a mock Database over the typed db.ml / db.library surface."""
    db = MagicMock()
    db.ml.has_vector_index.return_value = True
    db.library.resolve_song_identity.return_value = _SEED_SONG
    db.ml.get_song_vector.return_value = _sv(_SEED_SONG, (0.1, 0.2, 0.3))
    db.ml.search_similar_vectors.return_value = ()
    db.library.get_song_by_normalized_path.side_effect = lambda normalized_path, _library: (
        SimpleNamespace(song_id=_FILE_BY_PATH[normalized_path]) if normalized_path in _FILE_BY_PATH else None
    )
    return db


def _make_service(db: Database) -> VectorSearchService:
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
            service.search_similar_tracks(_SEED_ID, "effnet", limit=10)

        db.library.resolve_song_identity.assert_not_called()
        db.ml.get_song_vector.assert_not_called()

    def test_unresolved_file_handle_raises_missing_seed(self) -> None:
        db = _make_db()
        db.library.resolve_song_identity.return_value = None
        service = _make_service(db)

        with pytest.raises(MissingSeedVectorError, match="No vector found for file '1'"):
            service.search_similar_tracks(_SEED_ID, "effnet", limit=10)

        db.ml.search_similar_vectors.assert_not_called()

    def test_song_without_vector_raises_missing_seed(self) -> None:
        db = _make_db()
        db.ml.get_song_vector.return_value = None
        service = _make_service(db)

        with pytest.raises(MissingSeedVectorError, match="No vector found for file '1'"):
            service.search_similar_tracks(_SEED_ID, "effnet", limit=10)

        db.ml.search_similar_vectors.assert_not_called()


@pytest.mark.unit
class TestSearchSimilarTracksSuccess:
    """Typed search, transport adaptation, and no-storage-id guarantee."""

    def test_resolves_identity_and_searches_with_no_storage_id(self) -> None:
        db = _make_db()
        db.ml.search_similar_vectors.return_value = (_match("songs/seed.mp3", 0.9, (0.1, 0.2, 0.3)),)
        service = _make_service(db)

        results = service.search_similar_tracks(_SEED_ID, "effnet", limit=10)

        # Seed resolved to a SongIdentity (never an int) entering MlDb.
        db.library.resolve_song_identity.assert_called_once_with(_SEED_ID)
        db.ml.get_song_vector.assert_called_once_with("effnet", _SEED_SONG)
        assert isinstance(db.ml.get_song_vector.call_args.args[1], SongIdentity)
        db.ml.search_similar_vectors.assert_called_once_with(
            "effnet",
            (0.1, 0.2, 0.3),
            limit=10,
            include_vector=True,
        )
        assert results == [
            {"file_id": 1, "score": 0.9, "vector": [0.1, 0.2, 0.3]},
        ]

    def test_filters_and_sorts_transport_results(self) -> None:
        db = _make_db()
        db.ml.search_similar_vectors.return_value = (
            _match("songs/a.mp3", 0.7, (0.7, 0.3)),
            _match("songs/b.mp3", 0.4, (0.4, 0.6)),
            _match("songs/c.mp3", -0.1, (0.0, 1.0)),
        )
        service = _make_service(db)

        results = service.search_similar_tracks(_SEED_ID, "effnet", limit=10, min_score=0.6)

        assert results == [
            {"file_id": 3, "score": 0.7, "vector": [0.7, 0.3]},
        ]

    def test_zero_threshold_keeps_zero_similarity_and_negative_threshold_keeps_negative(self) -> None:
        db = _make_db()
        db.ml.search_similar_vectors.return_value = (
            _match("songs/a.mp3", 0.0, (0.0, 1.0)),
            _match("songs/b.mp3", -0.2, (1.0, 0.0)),
        )
        service = _make_service(db)

        zero_results = service.search_similar_tracks(_SEED_ID, "effnet", limit=10, min_score=0.0)
        negative_results = service.search_similar_tracks(_SEED_ID, "effnet", limit=10, min_score=-0.2)

        assert zero_results == [{"file_id": 3, "score": 0.0, "vector": [0.0, 1.0]}]
        assert negative_results == [
            {"file_id": 3, "score": 0.0, "vector": [0.0, 1.0]},
            {"file_id": 2, "score": -0.2, "vector": [1.0, 0.0]},
        ]

    def test_default_min_score_keeps_zero_drops_negative(self) -> None:
        db = _make_db()
        db.ml.search_similar_vectors.return_value = (
            _match("songs/a.mp3", 0.0, (0.0, 1.0)),
            _match("songs/b.mp3", -0.2, (1.0, 0.0)),
        )
        service = _make_service(db)

        results = service.search_similar_tracks(_SEED_ID, "effnet", limit=10)

        assert results == [
            {"file_id": 3, "score": 0.0, "vector": [0.0, 1.0]},
        ]

    def test_empty_matches_returns_empty(self) -> None:
        db = _make_db()
        service = _make_service(db)

        results = service.search_similar_tracks(_SEED_ID, "effnet", limit=10)

        assert results == []

    def test_skips_match_without_vector_payload(self) -> None:
        db = _make_db()
        db.ml.search_similar_vectors.return_value = (
            _match("songs/a.mp3", 0.9, None),
            _match("songs/b.mp3", 0.8, (0.1, 0.9)),
        )
        service = _make_service(db)

        results = service.search_similar_tracks(_SEED_ID, "effnet", limit=10)

        assert results == [
            {"file_id": 2, "score": 0.8, "vector": [0.1, 0.9]},
        ]


@pytest.mark.unit
class TestGetTrackVector:
    """Service track-vector method delegates to the typed workflow result."""

    def test_delegates_to_workflow_returning_song_vector(self, monkeypatch: pytest.MonkeyPatch) -> None:
        db = _make_db()
        service = _make_service(db)
        song_vector = _sv(_SEED_SONG, (0.5, 0.5))

        def _delegate(_db, _file_id, _backbone_id):
            return song_vector

        monkeypatch.setattr(
            "nomarr.workflows.vectors.get_track_vector_wf.get_track_vector",
            _delegate,
        )

        result = service.get_track_vector("effnet", _SEED_ID)

        assert result is song_vector
