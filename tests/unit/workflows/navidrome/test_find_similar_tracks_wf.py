"""Tests for the typed find_similar_tracks workflow.

The workflow consumes typed :class:`SongVector` / :class:`VectorMatch` values
(never raw persistence keys), excludes the seed track by comparing natural
``SongIdentity``, enriches matched identities back to file ids through
authoritative ``db.library``, and emits the direct clamped ``VectorMatch.score``
as the plugin-facing portable output.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.vector_dataclass import SongVector, VectorMatch
from nomarr.workflows.navidrome.find_similar_tracks_wf import find_similar_tracks

if TYPE_CHECKING:
    from nomarr.components.navidrome.descriptor_match_comp import TrackDescriptor
    from nomarr.persistence.db import Database

SEED: TrackDescriptor = {
    "title": "Seed",
    "artist": "Artist",
    "album": "Album",
    "album_artist": "",
    "duration_ms": None,
    "track_number": None,
    "disc_number": None,
    "year": None,
    "nomarr_file_key": None,
}

_LIB_ID = LibraryIdentity(name="Music", root_path="/music")
_IDS_BY_PATH = {
    "songs/seed.mp3": 1,
    "songs/a.mp3": 2,
    "songs/b.mp3": 3,
    "songs/match-1.mp3": 101,
    "songs/sparse.mp3": 5,
}
_SEED_SONG = SongIdentity(library=_LIB_ID, normalized_path="songs/seed.mp3")


def _sid(path: str) -> SongIdentity:
    return SongIdentity(library=_LIB_ID, normalized_path=path)


_DEFAULT_SEED_VECTOR = SongVector(
    song=_SEED_SONG,
    backbone="effnet",
    vector=(0.1, 0.2, 0.3),
    model_suite_hash="suite",
    num_segments=1,
    segmentation_hash=None,
    genres=None,
)


def _make_db(
    *,
    seed_file_id: str | None = "1",
    seed_resolution_status: str = "",
    seed_song_vector: SongVector | object | None = _DEFAULT_SEED_VECTOR,
    ann_matches: tuple[VectorMatch, ...] = (),
    file_docs: list[dict] | None = None,
) -> Database:
    """Build a mock Database over the typed component/db surface."""
    if seed_song_vector is _DEFAULT_SEED_VECTOR:
        seed_song_vector = _DEFAULT_SEED_VECTOR
    if file_docs is None:
        file_docs = []

    db = MagicMock()
    db._resolve_seed_descriptor_to_file = MagicMock(return_value=(seed_file_id, seed_resolution_status))
    db._get_cold_track_vector = MagicMock(return_value=seed_song_vector)
    db._search_similar_cold_track_vectors = MagicMock(return_value=ann_matches)
    db.library.get_songs_by_ids_with_tags.return_value = file_docs
    db.library.get_song_by_normalized_path.side_effect = lambda normalized_path, _library: (
        SimpleNamespace(song_id=_IDS_BY_PATH[normalized_path]) if normalized_path in _IDS_BY_PATH else None
    )
    return db


@pytest.fixture(autouse=True)
def comp_shims(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route workflow component calls to the mock DB surface."""

    def _resolve(db, seed_descriptor):  # type: ignore[no-untyped-def]
        return db._resolve_seed_descriptor_to_file(seed_descriptor)

    def _get_vector(db, file_id, backbone_id):  # type: ignore[no-untyped-def]
        return db._get_cold_track_vector(file_id, backbone_id)

    def _search(db, *, backbone_id, seed_vector, result_limit, include_vector=False):  # type: ignore[no-untyped-def]
        return db._search_similar_cold_track_vectors(
            backbone_id=backbone_id,
            seed_vector=seed_vector,
            result_limit=result_limit,
        )

    monkeypatch.setattr(
        "nomarr.workflows.navidrome.find_similar_tracks_wf.resolve_seed_descriptor_to_file",
        _resolve,
    )
    monkeypatch.setattr(
        "nomarr.workflows.navidrome.find_similar_tracks_wf.get_songs_by_ids_with_tags",
        lambda db, file_ids: db.library.get_songs_by_ids_with_tags(file_ids),
    )
    monkeypatch.setattr(
        "nomarr.workflows.navidrome.find_similar_tracks_wf.get_cold_track_vector",
        _get_vector,
    )
    monkeypatch.setattr(
        "nomarr.workflows.navidrome.find_similar_tracks_wf.search_similar_cold_track_vectors",
        _search,
    )


def _doc(file_id: int, *, tags: list[dict] | None = None, duration_seconds: float | None = None) -> dict:
    doc: dict = {"id": file_id}
    if tags is not None:
        doc["tags"] = tags
    if duration_seconds is not None:
        doc["duration_seconds"] = duration_seconds
    return doc


class TestFindSimilarTracksHappyPath:
    """Successful descriptor-based similarity flow on typed matches."""

    @pytest.mark.unit
    def test_returns_portable_descriptors_excluding_seed(self) -> None:
        db = _make_db(
            ann_matches=(
                VectorMatch(song=_SEED_SONG, backbone="effnet", score=1.0),
                VectorMatch(song=_sid("songs/a.mp3"), backbone="effnet", score=0.0),
            ),
            file_docs=[
                _doc(
                    2,
                    duration_seconds=201.2,
                    tags=[
                        {"key": "title", "value": "Song A"},
                        {"key": "artist", "value": "Artist A"},
                        {"key": "album", "value": "Album A"},
                        {"key": "album_artist", "value": "Album Artist A"},
                        {"key": "tracknumber", "value": "3"},
                        {"key": "discnumber", "value": "1"},
                        {"key": "year", "value": "2024"},
                    ],
                )
            ],
        )

        results = find_similar_tracks(SEED, count=10, backbone_id="effnet", db=db)

        assert len(results) == 1
        result = results[0]
        assert result["title"] == "Song A"
        assert result["artist"] == "Artist A"
        assert result["album"] == "Album A"
        assert result["album_artist"] == "Album Artist A"
        assert result["duration_ms"] == 201200
        assert result["track_number"] == 3
        assert result["disc_number"] == 1
        assert result["year"] == 2024
        assert result["nomarr_file_key"] == "2"
        assert result["score"] == 0.0

    @pytest.mark.unit
    def test_direct_clamped_score_is_emitted_verbatim(self) -> None:
        db = _make_db(
            ann_matches=(VectorMatch(song=_sid("songs/b.mp3"), backbone="effnet", score=-0.5),),
            file_docs=[_doc(3, tags=[])],
        )

        results = find_similar_tracks(SEED, count=10, backbone_id="effnet", db=db)

        assert len(results) == 1
        assert results[0]["score"] == -0.5

    @pytest.mark.unit
    def test_respects_count_limit(self) -> None:
        ann = tuple(
            VectorMatch(song=_sid(f"songs/m{i}.mp3"), backbone="effnet", score=0.9 - i * 0.01) for i in range(10)
        )
        docs = [_doc(1000 + i, tags=[]) for i in range(10)]
        for i in range(10):
            _IDS_BY_PATH[f"songs/m{i}.mp3"] = 1000 + i
        db = _make_db(ann_matches=ann, file_docs=docs)

        results = find_similar_tracks(SEED, count=3, backbone_id="effnet", db=db)

        assert len(results) == 3

    @pytest.mark.unit
    def test_fetches_count_plus_one(self) -> None:
        db = _make_db(ann_matches=())

        find_similar_tracks(SEED, count=25, backbone_id="effnet", db=db)

        call_limit = db._search_similar_cold_track_vectors.call_args.kwargs["result_limit"]
        assert call_limit == 26

    @pytest.mark.unit
    def test_does_not_use_navidrome_song_map_table(self) -> None:
        db = _make_db(
            ann_matches=(VectorMatch(song=_sid("songs/match-1.mp3"), backbone="effnet", score=0.5),),
            file_docs=[_doc(101, tags=[])],
        )
        find_similar_tracks(SEED, count=10, backbone_id="effnet", db=db)

        assert db.app.mock_calls == []


class TestFindSimilarTracksErrors:
    """Error conditions in the descriptor flow."""

    @pytest.mark.unit
    def test_raises_when_seed_descriptor_not_resolved(self) -> None:
        db = _make_db(seed_file_id=None, seed_resolution_status="descriptor_unresolved")

        with pytest.raises(ValueError, match="Seed descriptor could not be resolved"):
            find_similar_tracks(SEED, count=10, backbone_id="effnet", db=db)

    @pytest.mark.unit
    def test_raises_when_seed_descriptor_ambiguous(self) -> None:
        db = _make_db(seed_file_id=None, seed_resolution_status="descriptor_ambiguous")

        with pytest.raises(ValueError, match="is ambiguous"):
            find_similar_tracks(SEED, count=10, backbone_id="effnet", db=db)

    @pytest.mark.unit
    def test_raises_when_no_vector_exists(self) -> None:
        db = _make_db(seed_file_id="1", seed_song_vector=None)

        with pytest.raises(ValueError, match="No vector embedding found"):
            find_similar_tracks(SEED, count=10, backbone_id="effnet", db=db)


class TestFindSimilarTracksEdgeCases:
    """Edge conditions."""

    @pytest.mark.unit
    def test_empty_ann_matches(self) -> None:
        db = _make_db(ann_matches=())

        results = find_similar_tracks(SEED, count=10, backbone_id="effnet", db=db)

        assert results == []

    @pytest.mark.unit
    def test_missing_metadata_defaults(self) -> None:
        db = _make_db(
            ann_matches=(VectorMatch(song=_sid("songs/sparse.mp3"), backbone="effnet", score=0.5),),
            file_docs=[_doc(5, tags=[])],
        )

        results = find_similar_tracks(SEED, count=10, backbone_id="effnet", db=db)

        assert len(results) == 1
        assert results[0]["title"] == ""
        assert results[0]["artist"] == ""
        assert results[0]["album"] == ""
        assert results[0]["album_artist"] == ""
        assert results[0]["duration_ms"] is None
