"""Unit tests for sync_navidrome_wf."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.navidrome.subsonic_crawl_comp import CrawledSong
from nomarr.workflows.navidrome.sync_navidrome_wf import sync_navidrome


@pytest.fixture(autouse=True)
def helper_shims(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bridge helper-based workflow imports to the historical db mock surface."""

    monkeypatch.setattr(
        "nomarr.workflows.navidrome.sync_navidrome_wf.bulk_upsert_navidrome_tracks",
        lambda db, nd_ids: db.navidrome_tracks.bulk_upsert_tracks(nd_ids),
    )
    monkeypatch.setattr(
        "nomarr.workflows.navidrome.sync_navidrome_wf.bulk_ensure_navidrome_file_links",
        lambda db, mappings: db.navidrome_tracks.bulk_ensure_file_links(mappings),
    )
    monkeypatch.setattr(
        "nomarr.workflows.navidrome.sync_navidrome_wf.bulk_upsert_navidrome_plays",
        lambda db, user_id, plays: db.navidrome_playcounts.bulk_upsert_plays(user_id, plays),
    )
    monkeypatch.setattr(
        "nomarr.workflows.navidrome.sync_navidrome_wf.list_navidrome_track_keys",
        lambda db: db.navidrome_tracks.get_all_track_keys(),
    )
    monkeypatch.setattr(
        "nomarr.workflows.navidrome.sync_navidrome_wf.delete_navidrome_tracks_cascade",
        lambda db, nd_ids: db.navidrome_tracks.delete_tracks_cascade(nd_ids),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(
    path_map: dict[str, dict[str, str]] | None = None,
    existing_track_keys: list[str] | None = None,
) -> MagicMock:
    """Create a mock Database with navidrome_tracks and navidrome_playcounts."""
    db = MagicMock()
    db.library_files.get_files_by_paths_bulk.return_value = path_map or {}
    db.navidrome_tracks.bulk_upsert_tracks.return_value = 0
    db.navidrome_tracks.bulk_ensure_file_links.return_value = None
    db.navidrome_tracks.get_all_track_keys.return_value = existing_track_keys or []
    db.navidrome_tracks.delete_tracks_cascade.return_value = 0
    db.navidrome_playcounts.bulk_upsert_plays.return_value = 0
    return db


def _song(nd_id: str, path: str, play_count: int = 0, last_played_ms: int = 0) -> CrawledSong:
    """Create a CrawledSong dict."""
    return CrawledSong(
        nd_id=nd_id,
        nd_path=path,
        play_count=play_count,
        last_played_ms=last_played_ms,
    )


_CRAWL_PATH = "nomarr.workflows.navidrome.sync_navidrome_wf.crawl_navidrome_songs"
_DETECT_PREFIX = "nomarr.workflows.navidrome.sync_navidrome_wf._detect_prefix"
_GET_FILES_BY_PATHS = "nomarr.workflows.navidrome.sync_navidrome_wf.get_files_by_paths_bulk"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSyncNavidrome:
    """Tests for the sync_navidrome workflow."""

    def test_full_sync_with_play_counts(self) -> None:
        """All songs resolve, play counts are captured."""
        songs = [
            _song("nd-1", "/nd/t1.mp3", play_count=5, last_played_ms=1000),
            _song("nd-2", "/nd/t2.mp3", play_count=0),
        ]
        db = _make_db(
            path_map={
                "/t1.mp3": {"_id": "library_files/f1"},
                "/t2.mp3": {"_id": "library_files/f2"},
            },
            existing_track_keys=["nd-1", "nd-2"],
        )
        db.navidrome_tracks.bulk_upsert_tracks.return_value = 2
        db.navidrome_playcounts.bulk_upsert_plays.return_value = 1

        client = MagicMock()

        with (
            patch(_CRAWL_PATH, return_value=songs),
            patch(_DETECT_PREFIX, return_value="/nd"),
            patch(_GET_FILES_BY_PATHS, return_value=db.library_files.get_files_by_paths_bulk.return_value),
        ):
            result = sync_navidrome(client, db, "user-1")

        assert isinstance(result, dict)
        assert result["total_songs"] == 2
        assert result["resolved"] == 2
        assert result["unresolved"] == 0
        assert result["tracks_upserted"] == 2
        assert result["play_edges_upserted"] == 1
        assert result["orphans_removed"] == 0
        assert result["duration_ms"] >= 0

        db.navidrome_playcounts.bulk_upsert_plays.assert_called_once()

    def test_unresolved_songs_counted(self) -> None:
        """Songs that don't resolve to Nomarr files are counted."""
        songs = [
            _song("nd-1", "/nd/t1.mp3"),
            _song("nd-2", "/nd/unknown.mp3"),
        ]
        db = _make_db(
            path_map={"/t1.mp3": {"_id": "library_files/f1"}},
            existing_track_keys=[],
        )
        db.navidrome_tracks.bulk_upsert_tracks.return_value = 2
        client = MagicMock()

        with (
            patch(_CRAWL_PATH, return_value=songs),
            patch(_DETECT_PREFIX, return_value="/nd"),
            patch(_GET_FILES_BY_PATHS, return_value=db.library_files.get_files_by_paths_bulk.return_value),
        ):
            result = sync_navidrome(client, db, "user-1")

        assert result["total_songs"] == 2
        assert result["resolved"] == 1
        assert result["unresolved"] == 1

    def test_empty_library(self) -> None:
        """No songs returns zero-filled result."""
        db = _make_db(existing_track_keys=[])
        client = MagicMock()

        with (
            patch(_CRAWL_PATH, return_value=[]),
            patch(_DETECT_PREFIX, return_value=""),
            patch(_GET_FILES_BY_PATHS, return_value=db.library_files.get_files_by_paths_bulk.return_value),
        ):
            result = sync_navidrome(client, db, "user-1")

        assert result["total_songs"] == 0
        assert result["resolved"] == 0
        assert result["tracks_upserted"] == 0
        assert result["play_edges_upserted"] == 0
        assert result["orphans_removed"] == 0

    def test_orphan_cleanup(self) -> None:
        """Tracks in DB but not in Navidrome are removed."""
        songs = [_song("nd-1", "/nd/t1.mp3")]
        db = _make_db(
            path_map={"/t1.mp3": {"_id": "library_files/f1"}},
            existing_track_keys=["nd-1", "nd-orphan-1", "nd-orphan-2"],
        )
        db.navidrome_tracks.bulk_upsert_tracks.return_value = 1
        db.navidrome_tracks.delete_tracks_cascade.return_value = 2
        client = MagicMock()

        with (
            patch(_CRAWL_PATH, return_value=songs),
            patch(_DETECT_PREFIX, return_value="/nd"),
            patch(_GET_FILES_BY_PATHS, return_value=db.library_files.get_files_by_paths_bulk.return_value),
        ):
            result = sync_navidrome(client, db, "user-1")

        assert result["orphans_removed"] == 2
        db.navidrome_tracks.delete_tracks_cascade.assert_called_once_with(
            ["nd-orphan-1", "nd-orphan-2"],
        )

    def test_no_orphan_deletion_when_empty(self) -> None:
        """delete_tracks_cascade is not called when there are no orphans."""
        songs = [_song("nd-1", "/nd/t1.mp3")]
        db = _make_db(
            path_map={"/t1.mp3": {"_id": "library_files/f1"}},
            existing_track_keys=["nd-1"],
        )
        db.navidrome_tracks.bulk_upsert_tracks.return_value = 1
        client = MagicMock()

        with (
            patch(_CRAWL_PATH, return_value=songs),
            patch(_DETECT_PREFIX, return_value="/nd"),
            patch(_GET_FILES_BY_PATHS, return_value=db.library_files.get_files_by_paths_bulk.return_value),
        ):
            result = sync_navidrome(client, db, "user-1")

        assert result["orphans_removed"] == 0
        db.navidrome_tracks.delete_tracks_cascade.assert_not_called()

    def test_play_edges_only_for_nonzero_counts(self) -> None:
        """Only songs with play_count > 0 produce play edges."""
        songs = [
            _song("nd-1", "/nd/t1.mp3", play_count=3, last_played_ms=9000),
            _song("nd-2", "/nd/t2.mp3", play_count=0),
            _song("nd-3", "/nd/t3.mp3", play_count=1, last_played_ms=5000),
        ]
        db = _make_db(
            path_map={
                "/t1.mp3": {"_id": "library_files/f1"},
                "/t2.mp3": {"_id": "library_files/f2"},
                "/t3.mp3": {"_id": "library_files/f3"},
            },
            existing_track_keys=[],
        )
        db.navidrome_tracks.bulk_upsert_tracks.return_value = 3
        db.navidrome_playcounts.bulk_upsert_plays.return_value = 2
        client = MagicMock()

        with (
            patch(_CRAWL_PATH, return_value=songs),
            patch(_DETECT_PREFIX, return_value="/nd"),
            patch(_GET_FILES_BY_PATHS, return_value=db.library_files.get_files_by_paths_bulk.return_value),
        ):
            result = sync_navidrome(client, db, "user-1")

        assert result["play_edges_upserted"] == 2
        # bulk_upsert_plays(user_id, plays) — plays is the second positional arg
        call_args: list[dict[str, Any]] = db.navidrome_playcounts.bulk_upsert_plays.call_args[0][1]
        nd_ids_with_plays = [e["nd_id"] for e in call_args]
        assert nd_ids_with_plays == ["nd-1", "nd-3"]
