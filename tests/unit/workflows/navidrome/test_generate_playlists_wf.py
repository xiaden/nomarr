"""Unit tests for ``generate_playlists_wf``."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.vector_dataclass import EmbeddingCounts, SongVector, VectorMatch
from nomarr.workflows.navidrome.generate_playlists_wf import generate_playlists

_LIB = LibraryIdentity(name="test-library", root_path="/music")


def _song_identity(file_id: int) -> SongIdentity:
    """Build the natural identity used by the typed vector facade fixture."""
    return SongIdentity(library=_LIB, normalized_path=f"track-{file_id}.flac")


def _typed_vector(file_id: int, backbone: str) -> SongVector:
    """Build a cold-tier domain vector without a persistence-row ``embedding`` key."""
    song = _song_identity(file_id)
    return SongVector(
        song=song,
        backbone=backbone,
        vector=(float(file_id), float(file_id + 1)),
        model_suite_hash="test-suite",
        num_segments=1,
        segmentation_hash=None,
        genres=("rock",),
    )


def _make_db() -> MagicMock:
    """Create a mock Database."""
    return MagicMock()


def _profile() -> dict[str, object]:
    """Return a representative taste-profile payload."""
    return {
        "user_id": "user-1",
        "clusters": [{"label": "rock", "centroid": [0.1, 0.2, 0.3], "track_count": 3, "total_weight": 1.5}],
        "backbone_id": "effnet-discogs",
        "track_count": 3,
        "generated_at_ms": 1,
    }


def _mock_plays(*file_ids: str) -> list[dict[str, object]]:
    """Return mock play history entries for the given file IDs."""
    return [
        {
            "nd_id": f"nd-{i}",
            "file_id": f"{'songs'}/{fid}",
            "playcount": 5,
            "last_played": 123,
        }
        for i, fid in enumerate(file_ids)
    ]


def _playlist_entry(*file_ids: str) -> dict[str, object]:
    """Return a representative playlist entry."""
    return {
        "playlist_type": "familiar",
        "playlist_name": "Familiar Favorites",
        "file_ids": list(file_ids),
    }


@pytest.mark.unit
@pytest.mark.mocked
class TestGeneratePlaylistsWorkflow:
    """Tests for the personal-playlist generation workflow."""

    def test_warning_logged_when_no_taste_profile(self, caplog: pytest.LogCaptureFixture) -> None:
        """Missing taste profile should emit a warning and return an empty list."""
        db = _make_db()
        workflow_logger = logging.getLogger("nomarr.workflows.navidrome.generate_playlists_wf")
        original_propagate = workflow_logger.propagate
        workflow_logger.propagate = True

        try:
            with (
                patch(
                    "nomarr.workflows.navidrome.generate_playlists_wf.compute_taste_profile",
                    return_value=None,
                ),
                caplog.at_level(logging.WARNING, logger="nomarr.workflows.navidrome.generate_playlists_wf"),
            ):
                result = generate_playlists(
                    db,
                    user_id="user-1",
                    top_plays=_mock_plays("track-1"),
                    backbone_id="effnet-discogs",
                    # library_key removed per ADR-036
                    enabled_types=["familiar"],
                    half_life_days=30.0,
                    top_n=200,
                    max_songs=50,
                    min_play_count=3,
                    min_songs=10,
                    pp_max_clusters=10,
                )
        finally:
            workflow_logger.propagate = original_propagate

        assert result == []
        assert any(
            record.levelno == logging.WARNING and "No taste profile" in record.getMessage() for record in caplog.records
        )

    def test_warning_logged_when_all_playlists_filtered_by_min_songs(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Filtering every generated playlist should emit a warning."""
        db = _make_db()
        builder = MagicMock(return_value=[_playlist_entry(f"{'songs'}/track-1")])
        workflow_logger = logging.getLogger("nomarr.workflows.navidrome.generate_playlists_wf")
        original_propagate = workflow_logger.propagate
        workflow_logger.propagate = True

        try:
            with (
                patch(
                    "nomarr.workflows.navidrome.generate_playlists_wf.compute_taste_profile",
                    return_value=_profile(),
                ),
                patch.dict(
                    "nomarr.workflows.navidrome.generate_playlists_wf._BUILDERS",
                    {"familiar": builder},
                    clear=False,
                ),
                caplog.at_level(
                    logging.WARNING,
                    logger="nomarr.workflows.navidrome.generate_playlists_wf",
                ),
            ):
                result = generate_playlists(
                    db,
                    user_id="user-1",
                    top_plays=_mock_plays("track-1"),
                    backbone_id="effnet-discogs",
                    # library_key removed per ADR-036
                    enabled_types=["familiar"],
                    half_life_days=30.0,
                    top_n=200,
                    max_songs=50,
                    min_play_count=3,
                    min_songs=2,
                    pp_max_clusters=10,
                )
        finally:
            workflow_logger.propagate = original_propagate

        assert result == []
        builder.assert_called_once()
        assert any(
            record.levelno == logging.WARNING
            and "All generated playlists were filtered out by min_songs" in record.getMessage()
            for record in caplog.records
        )

    def test_generates_playlist_from_typed_cold_vectors(self) -> None:
        """The workflow consumes typed vectors, not persistence-row embeddings."""
        db = _make_db()
        backbone = "effnet-discogs"
        file_ids = [101, 102, 103]
        identities = {fid: _song_identity(fid) for fid in file_ids}
        vectors = {fid: _typed_vector(fid, backbone) for fid in file_ids}
        db.library.resolve_song_identity.side_effect = identities.get
        db.ml.get_song_vector.side_effect = lambda _backbone, song: vectors.get(
            next(fid for fid, identity in identities.items() if identity == song),
        )
        db.ml.embedding_counts.return_value = EmbeddingCounts(hot_count=0, cold_count=3)
        db.ml.search_similar_vectors.return_value = tuple(
            VectorMatch(song=identities[fid], backbone=backbone, score=0.9) for fid in file_ids
        )
        db.library.get_song_by_normalized_path.side_effect = lambda path, _library: SimpleNamespace(
            song_id=next(fid for fid, identity in identities.items() if identity.normalized_path == path),
        )

        plays = [{"file_id": fid, "playcount": 5, "last_played": 123} for fid in file_ids]
        tags = {fid: {"rock"} for fid in file_ids}
        with patch(
            "nomarr.components.navidrome.taste_profile_comp.get_tag_values_grouped_by_file",
            return_value=tags,
        ):
            result = generate_playlists(
                db,
                user_id="user-1",
                top_plays=plays,
                backbone_id=backbone,
                enabled_types=["familiar"],
                half_life_days=30.0,
                top_n=200,
                max_songs=50,
                min_play_count=3,
                min_songs=1,
                pp_max_clusters=10,
            )

        assert result == [
            {
                "playlist_type": "familiar",
                "playlist_name": "Your Favorites",
                "file_ids": [str(fid) for fid in file_ids],
            }
        ]
        db.ml.get_song_vector.assert_called()

    def test_returns_empty_when_no_taste_profile(self) -> None:
        """Behavior should remain an empty list when no taste profile exists."""
        db = _make_db()

        with patch(
            "nomarr.workflows.navidrome.generate_playlists_wf.compute_taste_profile",
            return_value=None,
        ):
            result = generate_playlists(
                db,
                user_id="user-1",
                top_plays=_mock_plays("track-1"),
                backbone_id="effnet-discogs",
                # library_key removed per ADR-036
                enabled_types=["familiar"],
                half_life_days=30.0,
                top_n=200,
                max_songs=50,
                min_play_count=3,
                min_songs=10,
                pp_max_clusters=10,
            )

        assert result == []
