"""Tests for the typed cold-tier vector retrieve component.

The component resolves integer file handles to a natural ``SongIdentity``
through ``db.library`` and consumes the typed ``db.ml`` read intents
(``embedding_counts`` / ``get_song_vector`` / ``search_similar_vectors``),
returning domain :class:`SongVector` / :class:`VectorMatch` values — never raw
persistence rows or storage keys.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.components.ml.vectors.ml_vector_retrieve_comp import (
    get_cold_track_vector,
    search_similar_cold_track_vectors,
)
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.vector_dataclass import EmbeddingCounts, SongVector, VectorMatch

_LIB_ID = LibraryIdentity(name="Music", root_path="/music")
_SEED_SONG = SongIdentity(library=_LIB_ID, normalized_path="songs/seed.mp3")


def _make_db() -> MagicMock:
    """Build a mock Database exposing the typed db.ml / db.library surface."""
    db = MagicMock()
    db.ml.embedding_counts.return_value = EmbeddingCounts(hot_count=0, cold_count=300)
    db.library.resolve_song_identity.return_value = _SEED_SONG
    db.ml.get_song_vector.return_value = SongVector(
        song=_SEED_SONG,
        backbone="effnet",
        vector=(0.1, 0.2, 0.3),
        model_suite_hash="suite",
        num_segments=1,
        segmentation_hash=None,
        genres=None,
    )
    db.ml.search_similar_vectors.return_value = (
        VectorMatch(song=_SEED_SONG, backbone="effnet", score=0.9, vector=(0.1, 0.2, 0.3)),
    )
    return db


@pytest.mark.unit
class TestGetColdTrackVector:
    """get_cold_track_vector resolves identity and reads a typed SongVector."""

    def test_returns_none_when_cold_tier_empty(self) -> None:
        db = _make_db()
        db.ml.embedding_counts.return_value = EmbeddingCounts(hot_count=0, cold_count=0)

        result = get_cold_track_vector(db, 1, "effnet")

        assert result is None
        db.library.resolve_song_identity.assert_not_called()
        db.ml.get_song_vector.assert_not_called()

    def test_returns_none_when_file_handle_unresolved(self) -> None:
        db = _make_db()
        db.library.resolve_song_identity.return_value = None

        result = get_cold_track_vector(db, 999, "effnet")

        assert result is None
        db.ml.get_song_vector.assert_not_called()

    def test_returns_none_when_song_has_no_vector(self) -> None:
        db = _make_db()
        db.ml.get_song_vector.return_value = None

        result = get_cold_track_vector(db, 1, "effnet")

        assert result is None
        db.ml.get_song_vector.assert_called_once_with("effnet", _SEED_SONG)

    def test_resolves_and_reads_cold_vector(self) -> None:
        db = _make_db()
        db.library.resolve_song_identity.return_value = _SEED_SONG

        result = get_cold_track_vector(db, 1, "effnet")

        assert result is not None
        assert isinstance(result, SongVector)
        assert result.song == _SEED_SONG
        assert result.vector == (0.1, 0.2, 0.3)
        db.library.resolve_song_identity.assert_called_once_with(1)
        db.ml.get_song_vector.assert_called_once_with("effnet", _SEED_SONG)


@pytest.mark.unit
class TestSearchSimilarColdTrackVectors:
    """search_similar_cold_track_vectors returns typed VectorMatch values."""

    def test_returns_empty_when_cold_tier_empty(self) -> None:
        db = _make_db()
        db.ml.embedding_counts.return_value = EmbeddingCounts(hot_count=0, cold_count=0)

        result = search_similar_cold_track_vectors(db, "effnet", [0.1, 0.2, 0.3], result_limit=11)

        assert result == ()
        db.ml.search_similar_vectors.assert_not_called()

    def test_queries_typed_search_when_cold_has_content(self) -> None:
        db = _make_db()
        expected = (VectorMatch(song=_SEED_SONG, backbone="effnet", score=0.9),)
        db.ml.search_similar_vectors.return_value = expected

        result = search_similar_cold_track_vectors(db, "effnet", [0.1, 0.2, 0.3], result_limit=11)

        assert result == expected
        db.ml.search_similar_vectors.assert_called_once_with(
            "effnet",
            [0.1, 0.2, 0.3],
            limit=11,
            include_vector=False,
        )

    def test_include_vector_is_explicit_and_propagates(self) -> None:
        db = _make_db()

        search_similar_cold_track_vectors(
            db,
            "effnet",
            (0.1, 0.2, 0.3),
            result_limit=5,
            include_vector=True,
        )

        db.ml.search_similar_vectors.assert_called_once_with(
            "effnet",
            (0.1, 0.2, 0.3),
            limit=5,
            include_vector=True,
        )
