"""Crawl Navidrome song inventory via Subsonic API.

Walks Navidrome's album list and collects song metadata (ID, path, play
counts) for use by the sync workflow.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from nomarr.components.navidrome.subsonic_client_comp import SubsonicClient

logger = logging.getLogger(__name__)

_ALBUM_PAGE_SIZE = 500
_PROGRESS_LOG_INTERVAL = 100


class CrawledSong(TypedDict):
    """Song data collected from Subsonic album crawl."""

    nd_id: str
    nd_path: str
    play_count: int
    last_played_ms: int


def crawl_navidrome_songs(client: SubsonicClient) -> list[CrawledSong]:
    """Walk all Navidrome albums and collect song data.

    Paginates through ``getAlbumList2`` (alphabetical), fetches each album's
    songs via ``getAlbum``, and collects ``(nd_id, path, playCount, played)``
    from each ``Child`` element.

    Args:
        client: Authenticated Subsonic API client.

    Returns:
        List of crawled songs with Navidrome IDs, paths, and play data.

    """
    all_songs: list[CrawledSong] = []
    offset = 0
    album_count = 0

    while True:
        albums = client.get_album_list2("alphabeticalByName", _ALBUM_PAGE_SIZE, offset)
        if not albums:
            break

        for album in albums:
            album_id = album.get("id", "")
            if not album_id:
                continue

            album_detail = client.get_album(album_id)
            songs: list[dict[str, Any]] = album_detail.get("song", [])

            for song in songs:
                song_id = song.get("id", "")
                song_path = song.get("path", "")
                if song_id and song_path:
                    all_songs.append(
                        CrawledSong(
                            nd_id=song_id,
                            nd_path=song_path,
                            play_count=song.get("playCount", 0) or 0,
                            last_played_ms=_parse_played_to_ms(song.get("played", "")),
                        ),
                    )

            album_count += 1
            if album_count % _PROGRESS_LOG_INTERVAL == 0:
                logger.info(
                    "crawl_navidrome_songs: Processed %d albums (%d songs so far)",
                    album_count,
                    len(all_songs),
                )

        offset += len(albums)

    logger.info("crawl_navidrome_songs: Collected %d songs from %d albums", len(all_songs), album_count)
    return all_songs


def remap_path(nd_path: str, prefix_map: list[tuple[str, str]]) -> str:
    """Apply path prefix remapping from Navidrome to Nomarr format.

    Tries each (navidrome_prefix, nomarr_prefix) pair in order.
    Returns the original path unchanged if no prefix matches.
    """
    for nd_prefix, nomarr_prefix in prefix_map:
        if nd_path.startswith(nd_prefix):
            return nomarr_prefix + nd_path[len(nd_prefix) :]
    return nd_path


def _parse_played_to_ms(played: str) -> int:
    """Convert Subsonic ``played`` datetime string to epoch milliseconds.

    Returns 0 if the string is empty or unparseable.
    """
    if not played:
        return 0
    try:
        dt = datetime.fromisoformat(played)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return int(dt.timestamp() * 1000)
    except (ValueError, OSError):
        return 0
