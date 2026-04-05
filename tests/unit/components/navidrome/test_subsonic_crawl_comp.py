"""Unit tests for subsonic_crawl_comp: crawl_navidrome_songs."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from nomarr.components.navidrome.subsonic_crawl_comp import crawl_navidrome_songs

# ---------------------------------------------------------------------------
# crawl_navidrome_songs
# ---------------------------------------------------------------------------


def _make_mock_client(
    albums: list[dict[str, Any]],
    album_details: dict[str, dict[str, Any]],
) -> MagicMock:
    """Create a mock SubsonicClient with paginated album walking."""
    client = MagicMock()

    def get_album_list2(type_: str, size: int, offset: int) -> list[dict[str, Any]]:
        if offset >= len(albums):
            return []
        return albums[offset : offset + size]

    client.get_album_list2.side_effect = get_album_list2
    client.get_album.side_effect = lambda album_id: album_details.get(album_id, {"song": []})
    return client


@pytest.mark.unit
class TestCrawlNavidromeSongs:
    """Tests for the album crawl function."""

    def test_collects_songs_from_albums(self) -> None:
        albums = [{"id": "al-1"}, {"id": "al-2"}]
        album_details: dict[str, dict[str, Any]] = {
            "al-1": {
                "song": [
                    {"id": "s-1", "path": "/music/t1.mp3", "playCount": 5, "played": "2025-06-01T10:00:00Z"},
                    {"id": "s-2", "path": "/music/t2.mp3"},
                ],
            },
            "al-2": {
                "song": [
                    {"id": "s-3", "path": "/music/t3.mp3", "playCount": 0},
                ],
            },
        }
        client = _make_mock_client(albums, album_details)

        result = crawl_navidrome_songs(client)

        assert len(result) == 3
        assert result[0]["nd_id"] == "s-1"
        assert result[0]["play_count"] == 5
        assert result[0]["last_played_ms"] > 0
        assert result[1]["nd_id"] == "s-2"
        assert result[1]["play_count"] == 0
        assert result[2]["nd_id"] == "s-3"

    def test_skips_songs_without_id_or_path(self) -> None:
        albums = [{"id": "al-1"}]
        album_details: dict[str, dict[str, Any]] = {
            "al-1": {
                "song": [
                    {"id": "s-1", "path": "/music/t1.mp3"},
                    {"id": "s-2"},  # No path
                    {"id": "", "path": "/music/t3.mp3"},  # No id
                ],
            },
        }
        client = _make_mock_client(albums, album_details)

        result = crawl_navidrome_songs(client)

        assert len(result) == 1
        assert result[0]["nd_id"] == "s-1"

    def test_empty_library(self) -> None:
        client = _make_mock_client([], {})
        result = crawl_navidrome_songs(client)
        assert result == []

    def test_pagination_walks_all_pages(self) -> None:
        albums = [{"id": f"al-{i}"} for i in range(3)]
        album_details = {f"al-{i}": {"song": [{"id": f"s-{i}", "path": f"/music/t{i}.mp3"}]} for i in range(3)}
        client = _make_mock_client(albums, album_details)

        result = crawl_navidrome_songs(client)

        assert len(result) == 3
        # Called twice: once with data, once empty
        assert client.get_album_list2.call_count == 2
