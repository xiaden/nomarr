"""Tests for find_similar_tracks workflow."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.workflows.navidrome.find_similar_tracks_wf import find_similar_tracks

SEED = {"title": "Seed", "artist": "Artist", "album": "Album"}


@pytest.fixture(autouse=True)
def helper_shims(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bridge workflow component calls to the mock DB surface."""

    monkeypatch.setattr(
        "nomarr.workflows.navidrome.find_similar_tracks_wf.resolve_seed_descriptor_to_file",
        lambda db, seed_descriptor: db._resolve_seed_descriptor_to_file(seed_descriptor),
    )
    monkeypatch.setattr(
        "nomarr.workflows.navidrome.find_similar_tracks_wf.get_file_library_key",
        lambda db, file_id: db.library_files.get_file_library_key(file_id),
    )
    monkeypatch.setattr(
        "nomarr.workflows.navidrome.find_similar_tracks_wf.get_files_by_ids_with_tags",
        lambda db, file_ids: db.library_files.get_files_by_ids_with_tags(file_ids),
    )
    monkeypatch.setattr(
        "nomarr.workflows.navidrome.find_similar_tracks_wf.get_cold_track_vector",
        lambda db, file_id, backbone_id, library_key: db._get_cold_track_vector(file_id, backbone_id, library_key),
    )
    monkeypatch.setattr(
        "nomarr.workflows.navidrome.find_similar_tracks_wf.search_similar_cold_track_vectors",
        lambda db, backbone_id, library_key, seed_vector, result_limit, vector_group_size, vector_search_thoroughness: (
            db._search_similar_cold_track_vectors(
                backbone_id=backbone_id,
                library_key=library_key,
                seed_vector=seed_vector,
                result_limit=result_limit,
                vector_group_size=vector_group_size,
                vector_search_thoroughness=vector_search_thoroughness,
            )
        ),
    )


def _make_db(
    *,
    seed_file_id: str | None = "library_files/seed-file",
    seed_resolution_status: str = "",
    seed_vector: list[float] | None = None,
    ann_results: list[dict] | None = None,
    file_docs: list[dict] | None = None,
) -> MagicMock:
    """Build a mock Database with pre-configured return values."""
    if seed_vector is None:
        seed_vector = [0.1, 0.2, 0.3]
    if ann_results is None:
        ann_results = []
    if file_docs is None:
        file_docs = []

    db = MagicMock()
    db._resolve_seed_descriptor_to_file = MagicMock(return_value=(seed_file_id, seed_resolution_status))
    db._get_cold_track_vector = MagicMock(
        return_value={"vector_n": seed_vector, "file_id": seed_file_id} if seed_file_id else None,
    )
    db._search_similar_cold_track_vectors = MagicMock(return_value=ann_results)
    db.library_files.get_files_by_ids_with_tags.return_value = file_docs
    db.library_files.get_file_library_key.return_value = "test_lib"
    return db


class TestFindSimilarTracksHappyPath:
    """Tests for successful descriptor-based similarity flow."""

    @pytest.mark.unit
    def test_returns_portable_descriptors(self) -> None:
        db = _make_db(
            ann_results=[
                {"file_id": "library_files/seed-file", "score": 1.0},
                {"file_id": "library_files/match-1", "score": 0.95},
            ],
            file_docs=[
                {
                    "_id": "library_files/match-1",
                    "_key": "match-1",
                    "title": "Song A",
                    "artist": "Artist A",
                    "album": "Album A",
                    "duration_seconds": 201.2,
                    "year": 2024,
                    "tags": [
                        {"key": "album_artist", "value": "Album Artist A"},
                        {"key": "tracknumber", "value": "3"},
                        {"key": "discnumber", "value": "1"},
                        {"key": "musicbrainz_trackid", "value": "mb-track"},
                        {"key": "musicbrainz_recordingid", "value": "mb-recording"},
                    ],
                }
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
        assert result["musicbrainz_track_id"] == "mb-track"
        assert result["musicbrainz_recording_id"] == "mb-recording"
        assert result["nomarr_file_key"] == "match-1"
        assert result["score"] == 0.95

    @pytest.mark.unit
    def test_respects_count_limit(self) -> None:
        ann = [{"file_id": f"library_files/f{i}", "score": 0.9 - i * 0.01} for i in range(10)]
        docs = [{"_id": f"library_files/f{i}", "title": f"S{i}", "artist": "A", "album": "B", "tags": []} for i in range(10)]
        db = _make_db(ann_results=ann, file_docs=docs)

        results = find_similar_tracks(SEED, count=3, backbone_id="effnet", db=db)

        assert len(results) == 3

    @pytest.mark.unit
    def test_fetches_count_plus_self(self) -> None:
        db = _make_db(ann_results=[])

        find_similar_tracks(SEED, count=25, backbone_id="effnet", db=db)

        call_limit = db._search_similar_cold_track_vectors.call_args.kwargs["result_limit"]
        assert call_limit == 26

    @pytest.mark.unit
    def test_does_not_use_navidrome_song_map_table(self) -> None:
        db = _make_db(
            ann_results=[{"file_id": "library_files/match-1", "score": 0.95}],
            file_docs=[{"_id": "library_files/match-1", "title": "Song A", "artist": "Artist A", "album": "Album A", "tags": []}],
        )
        db.navidrome_tracks = MagicMock()

        find_similar_tracks(SEED, count=10, backbone_id="effnet", db=db)

        assert db.navidrome_tracks.mock_calls == []


class TestFindSimilarTracksErrors:
    """Tests for error conditions in descriptor flow."""

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
        db = _make_db(seed_file_id="library_files/seed-file")
        db._get_cold_track_vector.return_value = None

        with pytest.raises(ValueError, match="No vector embedding found"):
            find_similar_tracks(SEED, count=10, backbone_id="effnet", db=db)


class TestFindSimilarTracksEdgeCases:
    """Tests for edge conditions."""

    @pytest.mark.unit
    def test_empty_ann_results(self) -> None:
        db = _make_db(ann_results=[])

        results = find_similar_tracks(SEED, count=10, backbone_id="effnet", db=db)

        assert results == []

    @pytest.mark.unit
    def test_missing_metadata_defaults(self) -> None:
        db = _make_db(
            ann_results=[{"file_id": "library_files/sparse", "score": 0.9}],
            file_docs=[{"_id": "library_files/sparse", "tags": []}],
        )

        results = find_similar_tracks(SEED, count=10, backbone_id="effnet", db=db)

        assert len(results) == 1
        assert results[0]["title"] == ""
        assert results[0]["artist"] == ""
        assert results[0]["album"] == ""
        assert results[0]["album_artist"] == ""
        assert results[0]["duration_ms"] is None
