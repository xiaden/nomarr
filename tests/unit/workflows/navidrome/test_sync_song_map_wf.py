"""Unit tests for sync_song_map workflow and NavidromeSongMapOperations."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.workflows.navidrome.sync_song_map_wf import _remap_path, sync_song_map


@pytest.mark.unit
class TestRemapPath:
    """Verify path prefix remapping logic."""

    def test_matching_prefix_replaced(self) -> None:
        """Path with matching prefix gets remapped."""
        prefix_map = [("/music", "/media/library")]
        result = _remap_path("/music/Artist/Album/track.mp3", prefix_map)
        assert result == "/media/library/Artist/Album/track.mp3"

    def test_first_matching_prefix_wins(self) -> None:
        """When multiple prefixes match, the first one wins."""
        prefix_map = [("/music", "/media/lib1"), ("/music/special", "/media/lib2")]
        result = _remap_path("/music/special/track.mp3", prefix_map)
        assert result == "/media/lib1/special/track.mp3"

    def test_no_match_returns_original(self) -> None:
        """Path with no matching prefix is returned unchanged."""
        prefix_map = [("/other", "/media/other")]
        result = _remap_path("/music/track.mp3", prefix_map)
        assert result == "/music/track.mp3"

    def test_empty_prefix_map(self) -> None:
        """Empty prefix map returns path unchanged."""
        result = _remap_path("/music/track.mp3", [])
        assert result == "/music/track.mp3"

    def test_exact_prefix_match(self) -> None:
        """Prefix that matches entire path works."""
        prefix_map = [("/music/track.mp3", "/new/path.mp3")]
        result = _remap_path("/music/track.mp3", prefix_map)
        assert result == "/new/path.mp3"


@pytest.mark.unit
class TestSyncSongMapWorkflow:
    """Verify the full sync workflow with mocked SubsonicClient and Database."""

    def _make_mock_client(self, albums: list[dict], album_details: dict[str, dict]) -> MagicMock:
        """Create a mock SubsonicClient."""
        client = MagicMock()

        def get_album_list2(type: str, size: int, offset: int) -> list[dict]:
            if offset >= len(albums):
                return []
            return albums[offset : offset + size]

        client.get_album_list2.side_effect = get_album_list2
        client.get_album.side_effect = lambda album_id: album_details.get(album_id, {"song": []})
        return client

    def _make_mock_db(self, path_to_doc: dict[str, dict]) -> MagicMock:
        """Create a mock Database."""
        db = MagicMock()
        db.library_files.get_files_by_paths_bulk.return_value = path_to_doc
        db.navidrome_song_map.upsert_batch.return_value = 0  # count set dynamically
        return db

    def test_full_sync_resolves_songs(self) -> None:
        """sync_song_map walks albums, remaps paths, and upserts mappings."""
        albums = [{"id": "al-1"}, {"id": "al-2"}]
        album_details = {
            "al-1": {
                "song": [
                    {"id": "s-1", "path": "/music/Artist/track1.mp3"},
                    {"id": "s-2", "path": "/music/Artist/track2.mp3"},
                ],
            },
            "al-2": {
                "song": [
                    {"id": "s-3", "path": "/music/Other/track3.mp3"},
                ],
            },
        }
        client = self._make_mock_client(albums, album_details)

        path_to_doc = {
            "/media/lib/Artist/track1.mp3": {"_id": "library_files/f1"},
            "/media/lib/Artist/track2.mp3": {"_id": "library_files/f2"},
            "/media/lib/Other/track3.mp3": {"_id": "library_files/f3"},
        }
        db = self._make_mock_db(path_to_doc)

        # Track what gets upserted
        upserted_batches: list[list[dict]] = []

        def capture_upsert(batch: list[dict]) -> int:
            upserted_batches.append(batch)
            return len(batch)

        db.navidrome_song_map.upsert_batch.side_effect = capture_upsert

        prefix_map = [("/music", "/media/lib")]
        result = sync_song_map(client, prefix_map, db)

        assert result["total_songs"] == 3
        assert result["resolved"] == 3
        assert result["unresolved"] == 0
        assert result["duration_ms"] >= 0

        # Verify all 3 songs were upserted
        all_upserted = [m for batch in upserted_batches for m in batch]
        assert len(all_upserted) == 3
        nd_ids = {m["nd_id"] for m in all_upserted}
        assert nd_ids == {"s-1", "s-2", "s-3"}

    def test_unresolved_songs_counted(self) -> None:
        """Songs with no matching Nomarr file are counted as unresolved."""
        albums = [{"id": "al-1"}]
        album_details = {
            "al-1": {
                "song": [
                    {"id": "s-1", "path": "/music/track1.mp3"},
                    {"id": "s-2", "path": "/music/track2.mp3"},
                ],
            },
        }
        client = self._make_mock_client(albums, album_details)

        # Only one path resolves
        path_to_doc = {
            "/music/track1.mp3": {"_id": "library_files/f1"},
        }
        db = self._make_mock_db(path_to_doc)
        db.navidrome_song_map.upsert_batch.side_effect = lambda batch: len(batch)

        result = sync_song_map(client, [], db)

        assert result["total_songs"] == 2
        assert result["resolved"] == 1
        assert result["unresolved"] == 1

    def test_empty_library_returns_zeros(self) -> None:
        """Empty Navidrome library returns zero counts."""
        client = self._make_mock_client([], {})
        db = self._make_mock_db({})

        result = sync_song_map(client, [], db)

        assert result["total_songs"] == 0
        assert result["resolved"] == 0
        assert result["unresolved"] == 0

    def test_pagination_walks_all_pages(self) -> None:
        """sync_song_map paginates through albums until empty page."""
        # 3 albums but page size is 500, so all in one page
        albums = [{"id": f"al-{i}"} for i in range(3)]
        album_details = {
            f"al-{i}": {"song": [{"id": f"s-{i}", "path": f"/music/track{i}.mp3"}]}
            for i in range(3)
        }
        client = self._make_mock_client(albums, album_details)

        path_to_doc = {
            f"/music/track{i}.mp3": {"_id": f"library_files/f{i}"} for i in range(3)
        }
        db = self._make_mock_db(path_to_doc)
        db.navidrome_song_map.upsert_batch.side_effect = lambda batch: len(batch)

        result = sync_song_map(client, [], db)

        assert result["total_songs"] == 3
        assert result["resolved"] == 3
        # Should have called getAlbumList2 twice (once with data, once empty)
        assert client.get_album_list2.call_count == 2

    def test_songs_without_path_skipped(self) -> None:
        """Songs missing the path attribute are silently skipped."""
        albums = [{"id": "al-1"}]
        album_details = {
            "al-1": {
                "song": [
                    {"id": "s-1", "path": "/music/track1.mp3"},
                    {"id": "s-2"},  # No path
                    {"id": "", "path": "/music/track3.mp3"},  # No id
                ],
            },
        }
        client = self._make_mock_client(albums, album_details)

        path_to_doc = {"/music/track1.mp3": {"_id": "library_files/f1"}}
        db = self._make_mock_db(path_to_doc)
        db.navidrome_song_map.upsert_batch.side_effect = lambda batch: len(batch)

        result = sync_song_map(client, [], db)

        assert result["total_songs"] == 1  # Only s-1 has both id and path
        assert result["resolved"] == 1
