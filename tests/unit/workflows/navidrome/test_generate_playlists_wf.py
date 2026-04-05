"""Unit tests for ``generate_playlists_wf``."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from nomarr.workflows.navidrome.generate_playlists_wf import generate_playlists


def _make_db(plays: list[dict[str, object]] | None = None) -> MagicMock:
    """Create a mock Database with configurable play-history data."""
    db = MagicMock()
    db.navidrome_playcounts.get_top_plays.return_value = plays or []
    return db


def _profile() -> dict[str, object]:
    """Return a representative taste-profile payload."""
    return {
        "user_id": "user-1",
        "centroid": [0.1, 0.2, 0.3],
        "backbone_id": "effnet-discogs",
        "library_key": "lib-main",
        "track_count": 3,
        "generated_at_ms": 1,
    }


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
                    backbone_id="effnet-discogs",
                    library_key="lib-main",
                    enabled_types=["familiar"],
                    half_life_days=30.0,
                    top_n=200,
                    max_songs=50,
                    min_play_count=3,
                    min_songs=10,
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
        db = _make_db(
            plays=[
                {
                    "nd_id": "nd-1",
                    "file_id": "library_files/track-1",
                    "playcount": 5,
                    "last_played": 123,
                },
            ],
        )
        builder = MagicMock(return_value=[_playlist_entry("library_files/track-1")])
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
                    backbone_id="effnet-discogs",
                    library_key="lib-main",
                    enabled_types=["familiar"],
                    half_life_days=30.0,
                    top_n=200,
                    max_songs=50,
                    min_play_count=3,
                    min_songs=2,
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
                backbone_id="effnet-discogs",
                library_key="lib-main",
                enabled_types=["familiar"],
                half_life_days=30.0,
                top_n=200,
                max_songs=50,
                min_play_count=3,
                min_songs=10,
            )

        assert result == []
