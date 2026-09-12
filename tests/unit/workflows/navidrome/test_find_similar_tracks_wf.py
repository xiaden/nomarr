"""Tests for the typed ``find_similar_tracks`` workflow.

The workflow consumes typed :class:`SongVector` / :class:`VectorMatch` values
(never raw persistence keys), resolves the seed descriptor to an opaque
``nom1`` locator, excludes the seed track by comparing natural ``SongIdentity``,
and enriches matched identities through the shared descriptor builder. No
generated integer id crosses the workflow.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.vector_dataclass import SongVector, VectorMatch
from nomarr.helpers.song_locator_codec import encode_song_locator
from nomarr.workflows.navidrome.find_similar_tracks_wf import find_similar_tracks

if TYPE_CHECKING:
    from nomarr.components.navidrome.descriptor_match_comp import TrackDescriptor

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

_LIB_ID = LibraryIdentity(library_uuid="6313b0d3-d270-47a8-9e0d-21e8255107e3", name="Music", root_path="/music")


def _sid(path: str) -> SongIdentity:
    return SongIdentity(library=_LIB_ID, normalized_path=path)


_SEED_SONG = _sid("songs/seed.mp3")
_SEED_TOKEN = encode_song_locator(_SEED_SONG)


def _descriptor(path: str, **overrides: object) -> TrackDescriptor:
    base: TrackDescriptor = {
        "title": "Song",
        "artist": "Artist",
        "album": "Album",
        "album_artist": "",
        "duration_ms": None,
        "track_number": None,
        "disc_number": None,
        "year": None,
        "nomarr_file_key": path,
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


def _seed_vector(song: SongIdentity = _SEED_SONG) -> SongVector:
    return SongVector(
        song=song,
        backbone="effnet",
        vector=(0.1, 0.2, 0.3),
        model_suite_hash="suite",
        num_segments=1,
        segmentation_hash=None,
        genres=None,
    )


def _make_db(
    *,
    seed_token: str | None = _SEED_TOKEN,
    seed_resolution_status: str = "",
    seed_song_vector: SongVector | None,
    descriptor_map: dict[SongIdentity, TrackDescriptor] | None = None,
) -> MagicMock:
    db = MagicMock()
    db.ml.get_song_vector.return_value = seed_song_vector
    db._seed_token = seed_token
    db._seed_resolution_status = seed_resolution_status
    db._descriptor_map = descriptor_map or {}
    return db


# Shared mutable state the fixture's search shim reads for per-test matches.
_captured_state: dict[str, object] = {"search": {}, "ann_matches": ()}


@pytest.fixture(autouse=True)
def comp_shims(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route workflow component calls onto the mock DB surface."""
    _captured_state["ann_matches"] = ()
    _captured_state["search"] = {}

    def _resolve(db, seed_descriptor):  # type: ignore[no-untyped-def]
        return db._seed_token, db._seed_resolution_status

    def _search(db, *, backbone_id, seed_vector, result_limit):  # type: ignore[no-untyped-def]
        _captured_state["search"] = {"result_limit": result_limit}
        return _captured_state["ann_matches"]

    def _descriptor_for_locator(db, locator):  # type: ignore[no-untyped-def]
        return db._descriptor_map.get(locator)

    monkeypatch.setattr(
        "nomarr.workflows.navidrome.find_similar_tracks_wf.resolve_seed_descriptor_to_file",
        _resolve,
    )
    monkeypatch.setattr(
        "nomarr.workflows.navidrome.find_similar_tracks_wf.search_similar_cold_track_vectors",
        _search,
    )
    monkeypatch.setattr(
        "nomarr.workflows.navidrome.find_similar_tracks_wf.descriptor_for_locator",
        _descriptor_for_locator,
    )


class TestFindSimilarTracksHappyPath:
    """Successful descriptor-based similarity flow on typed matches."""

    @pytest.mark.unit
    def test_returns_portable_descriptors_excluding_seed(self) -> None:
        db = _make_db(
            seed_song_vector=_seed_vector(),
            descriptor_map={
                _sid("songs/a.mp3"): _descriptor(
                    "songs/a.mp3",
                    title="Song A",
                    artist="Artist A",
                    album="Album A",
                    album_artist="Album Artist A",
                    duration_ms=201200,
                    track_number=3,
                    disc_number=1,
                    year=2024,
                    nomarr_file_key="2",
                )
            },
        )
        _captured_state["ann_matches"] = (
            VectorMatch(song=_SEED_SONG, backbone="effnet", score=1.0),
            VectorMatch(song=_sid("songs/a.mp3"), backbone="effnet", score=0.0),
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
            seed_song_vector=_seed_vector(),
            descriptor_map={_sid("songs/b.mp3"): _descriptor("songs/b.mp3")},
        )
        _captured_state["ann_matches"] = (VectorMatch(song=_sid("songs/b.mp3"), backbone="effnet", score=-0.5),)

        results = find_similar_tracks(SEED, count=10, backbone_id="effnet", db=db)

        assert len(results) == 1
        assert results[0]["score"] == -0.5

    @pytest.mark.unit
    def test_respects_count_limit(self) -> None:
        ann = tuple(
            VectorMatch(song=_sid(f"songs/m{i}.mp3"), backbone="effnet", score=0.9 - i * 0.01) for i in range(10)
        )
        descriptor_map = {_sid(f"songs/m{i}.mp3"): _descriptor(f"songs/m{i}.mp3") for i in range(10)}
        db = _make_db(seed_song_vector=_seed_vector(), descriptor_map=descriptor_map)
        _captured_state["ann_matches"] = ann

        results = find_similar_tracks(SEED, count=3, backbone_id="effnet", db=db)

        assert len(results) == 3

    @pytest.mark.unit
    def test_fetches_count_plus_one(self) -> None:
        db = _make_db(seed_song_vector=_seed_vector())
        _captured_state["ann_matches"] = ()

        find_similar_tracks(SEED, count=25, backbone_id="effnet", db=db)

        assert _captured_state["search"]["result_limit"] == 26  # type: ignore[index]

    @pytest.mark.unit
    def test_does_not_use_navidrome_song_map_table(self) -> None:
        db = _make_db(
            seed_song_vector=_seed_vector(),
            descriptor_map={_sid("songs/match-1.mp3"): _descriptor("songs/match-1.mp3")},
        )
        _captured_state["ann_matches"] = (VectorMatch(song=_sid("songs/match-1.mp3"), backbone="effnet", score=0.5),)

        find_similar_tracks(SEED, count=10, backbone_id="effnet", db=db)

        assert db.app.mock_calls == []


class TestFindSimilarTracksErrors:
    """Error conditions in the descriptor flow."""

    @pytest.mark.unit
    def test_raises_when_seed_descriptor_not_resolved(self) -> None:
        db = _make_db(seed_token=None, seed_resolution_status="descriptor_unresolved", seed_song_vector=None)

        with pytest.raises(ValueError, match="Seed descriptor could not be resolved"):
            find_similar_tracks(SEED, count=10, backbone_id="effnet", db=db)

    @pytest.mark.unit
    def test_raises_when_seed_descriptor_ambiguous(self) -> None:
        db = _make_db(seed_token=None, seed_resolution_status="descriptor_ambiguous", seed_song_vector=None)

        with pytest.raises(ValueError, match="is ambiguous"):
            find_similar_tracks(SEED, count=10, backbone_id="effnet", db=db)

    @pytest.mark.unit
    def test_raises_when_no_vector_exists(self) -> None:
        db = _make_db(seed_song_vector=None)

        with pytest.raises(ValueError, match="No vector embedding found"):
            find_similar_tracks(SEED, count=10, backbone_id="effnet", db=db)


class TestFindSimilarTracksEdgeCases:
    """Edge conditions."""

    @pytest.mark.unit
    def test_empty_ann_matches(self) -> None:
        db = _make_db(seed_song_vector=_seed_vector())
        _captured_state["ann_matches"] = ()

        results = find_similar_tracks(SEED, count=10, backbone_id="effnet", db=db)

        assert results == []

    @pytest.mark.unit
    def test_missing_metadata_defaults(self) -> None:
        db = _make_db(
            seed_song_vector=_seed_vector(),
            descriptor_map={_sid("songs/sparse.mp3"): _descriptor("songs/sparse.mp3", title="", artist="", album="")},
        )
        _captured_state["ann_matches"] = (VectorMatch(song=_sid("songs/sparse.mp3"), backbone="effnet", score=0.5),)

        results = find_similar_tracks(SEED, count=10, backbone_id="effnet", db=db)

        assert len(results) == 1
        assert results[0]["title"] == ""
        assert results[0]["artist"] == ""
        assert results[0]["album"] == ""
        assert results[0]["album_artist"] == ""
        assert results[0]["duration_ms"] is None
