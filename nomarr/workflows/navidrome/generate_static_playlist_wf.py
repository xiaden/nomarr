"""Generate a static M3U playlist from opaque ``nom1`` SongLocator tokens.

This workflow accepts a list of opaque ``nom1`` SongLocator tokens,
strictly decodes each to its ``{library_uuid, path}`` payload, and reads
the semantic ``Song`` and tag-derived metadata through the library facade
to generate M3U playlist content suitable for Navidrome import. Generated
integer ids never appear on this boundary.

Unlike smart playlists (.nsp) which are rule-based, this produces
a fixed, static playlist of specific tracks.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.infrastructure.path_comp import build_library_path_from_db, get_library_root
from nomarr.components.library.tag_hydration_comp import hydrate_songs_with_metadata
from nomarr.components.navidrome.m3u_comp import build_m3u, save_m3u
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dto.navidrome_dto import StaticPlaylistResult
from nomarr.helpers.song_locator_codec import SongLocatorFormatError, decode_song_locator

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.song_dataclass import Song
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)

_MAX_TRACKS = 200


def generate_static_playlist_workflow(
    db: Database,
    file_ids: list[str],
    playlist_name: str = "Vector Search Playlist",
    m3u_output_path: str = "",
) -> StaticPlaylistResult:
    """Generate a static M3U playlist from opaque ``nom1`` SongLocator tokens.

    Each token is strictly decoded to its ``{library_uuid, path}`` payload, the
    mutable ``SongIdentity`` locator is reconstructed, and the semantic ``Song``
    plus its ADR-045 tag-derived metadata is read through the library facade.
    Generated integer ids never appear on this boundary.

    When *m3u_output_path* is non-empty the M3U file is also written to
    ``{library_root}/{m3u_output_path}/{playlist_name}.m3u``.

    Args:
        db: Database instance for file lookup.
        file_ids: Opaque SongLocator tokens (max 200).
        playlist_name: Name for the playlist header.
        m3u_output_path: Sub-directory (relative to library root) for
            server-side M3U output.  Empty string disables file output.

    Returns:
        StaticPlaylistResult with M3U content, track count, missing tokens,
        and optionally the server-side save path.

    Raises:
        ValueError: If file_ids exceeds the 200 track limit.

    """
    if len(file_ids) > _MAX_TRACKS:
        msg = f"Cannot generate playlist with {len(file_ids)} tracks (max {_MAX_TRACKS})"
        raise ValueError(msg)

    if not file_ids:
        return StaticPlaylistResult(
            playlist_name=playlist_name,
            m3u_content="",
            track_count=0,
            missing_ids=[],
            saved_path=None,
        )

    # Step 1: Decode each opaque token to a mutable SongIdentity locator and
    # read its semantic Song through the facade. Malformed/unknown tokens are
    # collected as missing rather than erroring the whole playlist.
    songs: list[Song] = []
    locators: list[SongIdentity] = []
    resolved_tokens: list[str] = []
    missing_ids: list[str] = []
    for token in file_ids:
        if token in resolved_tokens:
            continue
        try:
            payload = decode_song_locator(token)
        except SongLocatorFormatError:
            missing_ids.append(token)
            continue
        locator = SongIdentity(
            library=LibraryIdentity(library_uuid=payload.library_uuid),
            normalized_path=payload.path,
        )
        song = db.library.get_song(locator)
        if song is None:
            missing_ids.append(token)
            continue
        resolved_tokens.append(token)
        songs.append(song)
        locators.append(locator)

    if missing_ids:
        logger.warning(
            "Static playlist: %d of %d locator tokens not found",
            len(missing_ids),
            len(file_ids),
        )

    hydrated = hydrate_songs_with_metadata(db, songs, locators)
    files: list[dict[str, Any]] = [
        {
            "id": token,
            "path": hydrated_song.song.path,
            "title": str(hydrated_song.metadata.get("title", "")),
            "artist": str(hydrated_song.metadata.get("artist", "")),
            "duration_seconds": hydrated_song.song.duration_seconds,
        }
        for token, hydrated_song in zip(resolved_tokens, hydrated, strict=True)
    ]

    # Step 2: Resolve the library root from the first file
    library_root = ""
    if files:
        first_path = str(files[0]["path"])
        library_path = build_library_path_from_db(first_path, db, check_disk=False)
        root = get_library_root(library_path, db)
        if root is not None:
            library_root = str(root)

    # Step 3: Build M3U content (relative paths)
    m3u_content = build_m3u(playlist_name, files, file_ids, library_root=library_root)

    # Step 4: Server-side save when configured
    saved_path: str | None = None
    if m3u_output_path and library_root:
        saved_path = save_m3u(library_root, m3u_output_path, playlist_name, m3u_content)

    return StaticPlaylistResult(
        playlist_name=playlist_name,
        m3u_content=m3u_content,
        track_count=len(files),
        missing_ids=missing_ids,
        saved_path=saved_path,
    )
