"""Tests for find_similar_tracks workflow."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.workflows.navidrome.find_similar_tracks_wf import find_similar_tracks

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_db(
    *,
    nd_lookup: str | None = "library_files/seed-file",
    seed_vector: list[float] | None = None,
    ann_results: list[dict] | None = None,
    nd_bulk_map: dict[str, str] | None = None,
    file_docs: list[dict] | None = None,
) -> MagicMock:
    """Build a mock Database with pre-configured return values."""
    if seed_vector is None:
        seed_vector = [0.1, 0.2, 0.3]
    if ann_results is None:
        ann_results = []
    if nd_bulk_map is None:
        nd_bulk_map = {}
    if file_docs is None:
        file_docs = []

    db = MagicMock()

    # navidrome_song_map
    db.navidrome_song_map.lookup_by_nd_id.return_value = nd_lookup

    # cold ops
    cold_ops = MagicMock()
    cold_ops.get_vector.return_value = {"vector_n": seed_vector, "file_id": nd_lookup} if nd_lookup else None
    cold_ops.search_similar.return_value = ann_results
    db.get_vectors_track_cold.return_value = cold_ops

    # bulk ND lookup
    db.navidrome_song_map.bulk_lookup_by_file_ids.return_value = nd_bulk_map

    # library files metadata
    db.library_files.get_files_by_ids_with_tags.return_value = file_docs

    return db


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


class TestFindSimilarTracksHappyPath:
    """Tests for the successful similarity search flow."""

    @pytest.mark.unit
    def test_returns_similar_tracks_with_metadata(self) -> None:
        """Full pipeline: seed → vector → ANN → ND resolve → metadata."""
        db = _make_db(
            nd_lookup="library_files/seed-file",
            seed_vector=[0.1, 0.2, 0.3],
            ann_results=[
                {"file_id": "library_files/seed-file", "score": 1.0},  # self-match
                {"file_id": "library_files/match-1", "score": 0.95},
                {"file_id": "library_files/match-2", "score": 0.88},
            ],
            nd_bulk_map={
                "library_files/match-1": "nd-id-1",
                "library_files/match-2": "nd-id-2",
            },
            file_docs=[
                {"_id": "library_files/match-1", "title": "Song A", "artist": "Artist A", "album": "Album A"},
                {"_id": "library_files/match-2", "title": "Song B", "artist": "Artist B", "album": "Album B"},
            ],
        )

        results = find_similar_tracks("nd-seed", count=10, backbone_id="effnet-discogs", db=db)

        assert len(results) == 2
        assert results[0]["nd_id"] == "nd-id-1"
        assert results[0]["name"] == "Song A"
        assert results[0]["score"] == 0.95
        assert results[1]["nd_id"] == "nd-id-2"
        assert results[1]["name"] == "Song B"

    @pytest.mark.unit
    def test_excludes_seed_track_from_results(self) -> None:
        """Seed file_id must not appear in output."""
        db = _make_db(
            ann_results=[
                {"file_id": "library_files/seed-file", "score": 1.0},
                {"file_id": "library_files/other", "score": 0.9},
            ],
            nd_bulk_map={"library_files/other": "nd-other"},
            file_docs=[{"_id": "library_files/other", "title": "Other", "artist": "A", "album": "B"}],
        )

        results = find_similar_tracks("nd-seed", count=10, backbone_id="effnet-discogs", db=db)

        assert len(results) == 1
        assert results[0]["nd_id"] == "nd-other"

    @pytest.mark.unit
    def test_respects_count_limit(self) -> None:
        """Output is trimmed to requested count."""
        ann = [{"file_id": f"library_files/f{i}", "score": 0.9 - i * 0.01} for i in range(10)]
        nd_map = {f"library_files/f{i}": f"nd-{i}" for i in range(10)}
        docs = [{"_id": f"library_files/f{i}", "title": f"S{i}", "artist": "A", "album": "B"} for i in range(10)]

        db = _make_db(ann_results=ann, nd_bulk_map=nd_map, file_docs=docs)

        results = find_similar_tracks("nd-seed", count=3, backbone_id="effnet-discogs", db=db)

        assert len(results) == 3

    @pytest.mark.unit
    def test_over_fetches_from_ann(self) -> None:
        """ANN search limit should be count * 2 + 1."""
        db = _make_db(ann_results=[])

        find_similar_tracks("nd-seed", count=25, backbone_id="effnet-discogs", db=db)

        cold_ops = db.get_vectors_track_cold.return_value
        cold_ops.search_similar.assert_called_once()
        call_limit = cold_ops.search_similar.call_args[0][1]
        assert call_limit == 51  # 25 * 2 + 1


# ---------------------------------------------------------------------------
# Error path tests
# ---------------------------------------------------------------------------


class TestFindSimilarTracksErrors:
    """Tests for error conditions in the similarity pipeline."""

    @pytest.mark.unit
    def test_raises_when_seed_not_in_song_map(self) -> None:
        """ValueError when Navidrome ID is not mapped."""
        db = _make_db(nd_lookup=None)

        with pytest.raises(ValueError, match="not found in song map"):
            find_similar_tracks("unknown-nd-id", count=10, backbone_id="effnet-discogs", db=db)

    @pytest.mark.unit
    def test_raises_when_no_vector_exists(self) -> None:
        """ValueError when seed file has no vector embedding."""
        db = _make_db(nd_lookup="library_files/seed-file")
        cold_ops = db.get_vectors_track_cold.return_value
        cold_ops.get_vector.return_value = None

        with pytest.raises(ValueError, match="No vector embedding found"):
            find_similar_tracks("nd-seed", count=10, backbone_id="effnet-discogs", db=db)


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestFindSimilarTracksEdgeCases:
    """Tests for edge conditions."""

    @pytest.mark.unit
    def test_empty_ann_results(self) -> None:
        """Returns empty list when ANN search finds nothing."""
        db = _make_db(ann_results=[])

        results = find_similar_tracks("nd-seed", count=10, backbone_id="effnet-discogs", db=db)

        assert results == []

    @pytest.mark.unit
    def test_partial_nd_mapping(self) -> None:
        """Only results with Navidrome mappings are returned."""
        db = _make_db(
            ann_results=[
                {"file_id": "library_files/mapped", "score": 0.9},
                {"file_id": "library_files/unmapped", "score": 0.85},
            ],
            nd_bulk_map={"library_files/mapped": "nd-mapped"},  # unmapped is missing
            file_docs=[{"_id": "library_files/mapped", "title": "Mapped", "artist": "A", "album": "B"}],
        )

        results = find_similar_tracks("nd-seed", count=10, backbone_id="effnet-discogs", db=db)

        assert len(results) == 1
        assert results[0]["nd_id"] == "nd-mapped"

    @pytest.mark.unit
    def test_all_results_unmapped(self) -> None:
        """Returns empty list when no ANN results have Navidrome mappings."""
        db = _make_db(
            ann_results=[{"file_id": "library_files/orphan", "score": 0.9}],
            nd_bulk_map={},  # nothing maps
        )

        results = find_similar_tracks("nd-seed", count=10, backbone_id="effnet-discogs", db=db)

        assert results == []

    @pytest.mark.unit
    def test_missing_metadata_uses_empty_strings(self) -> None:
        """If a file doc is missing fields, defaults to empty strings."""
        db = _make_db(
            ann_results=[{"file_id": "library_files/sparse", "score": 0.9}],
            nd_bulk_map={"library_files/sparse": "nd-sparse"},
            file_docs=[{"_id": "library_files/sparse"}],  # no title/artist/album
        )

        results = find_similar_tracks("nd-seed", count=10, backbone_id="effnet-discogs", db=db)

        assert len(results) == 1
        assert results[0]["name"] == ""
        assert results[0]["artist"] == ""
        assert results[0]["album"] == ""

    @pytest.mark.unit
    def test_backbone_id_passed_to_cold_ops(self) -> None:
        """Backbone ID is forwarded to get_vectors_track_cold."""
        db = _make_db(ann_results=[])

        find_similar_tracks("nd-seed", count=5, backbone_id="custom-backbone", db=db)

        db.get_vectors_track_cold.assert_called_once_with("custom-backbone")
