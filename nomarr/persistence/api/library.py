"""Library persistence facade — thin namespaced forwarder.

``LibraryDb`` is the caller-facing entry point for the library persistence
surface. It holds no logic of its own: every public method delegates to one
of four domain-identity sub-facades (``songs``, ``tags``, ``scans``,
``regions``) per DD-persistence-intent-facade-rebuild §Phase 1 (namespaced
forwarding). Callers keep using ``db.library.method()`` unchanged.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.orm import Session, scoped_session

    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dataclasses.library_domain_dataclasses import (
        LibraryFolder,
        LibraryPipelineState,
        LibraryScan,
        LibraryUpdate,
    )
    from nomarr.helpers.dataclasses.song_command_dataclass import (
        LibraryIdentity,
        SongIdentity,
    )
    from nomarr.helpers.dataclasses.song_dataclass import Song, SongTagMatch
    from nomarr.helpers.dataclasses.song_tag_dataclass import (
        RelinkResult,
        SongTagAssignment,
        TagCleanupResult,
        TagRef,
        TagUsage,
    )
    from nomarr.persistence.api.library_regions import LibraryRegionsDb
    from nomarr.persistence.api.library_scans import LibraryScansDb
    from nomarr.persistence.api.library_songs import LibrarySongsDb
    from nomarr.persistence.api.library_tags import LibraryTagsDb


class LibraryDb:
    """Caller-facing library persistence facade (namespaced forwarder).

    Delegates each public method to the matching sub-facade: ``songs``
    (song/folder domain), ``tags`` (tag/song-tag domain), ``scans`` (scan
    lifecycle), ``regions`` (library/pipeline-state domain).
    """

    def __init__(
        self,
        *,
        session: scoped_session[Session],
        songs: LibrarySongsDb,
        tags: LibraryTagsDb,
        scans: LibraryScansDb,
        regions: LibraryRegionsDb,
    ) -> None:
        self._session = session
        self._songs = songs
        self._tags = tags
        self._scans = scans
        self._regions = regions

    @property
    def songs(self) -> LibrarySongsDb:
        """Song and folder sub-facade."""
        return self._songs

    @property
    def tags(self) -> LibraryTagsDb:
        """Tag and song-tag edge sub-facade."""
        return self._tags

    @property
    def scans(self) -> LibraryScansDb:
        """Scan lifecycle sub-facade."""
        return self._scans

    @property
    def regions(self) -> LibraryRegionsDb:
        """Library and pipeline-state sub-facade."""
        return self._regions

    # ------------------------------------------------------------------
    # Library / pipeline-state forwarding (regions)
    # ------------------------------------------------------------------

    def create_library(self, library: Library) -> Library:
        """Create a library and return the persisted ``Library``.

        Timestamps are supplied by persistence when absent on the input.
        """
        return self._regions.create_library(library)

    def get_library(self, library: Library) -> Library | None:
        """Get a library by its natural ``(name, root_path)`` identity."""
        return self._regions.get_library(library)

    def get_library_by_name(self, name: str) -> Library | None:
        """Get a library by its name."""
        return self._regions.get_library_by_name(name)

    def list_libraries(self, *, enabled_only: bool = False) -> list[Library]:
        """List all libraries, optionally filtering to enabled only."""
        return self._regions.list_libraries(enabled_only=enabled_only)

    def update_library(self, library: Library, changes: LibraryUpdate) -> Library:
        """Apply a typed ``LibraryUpdate`` and return the updated ``Library``."""
        return self._regions.update_library(library, changes)

    def remove_library(self, library: Library) -> bool:
        """Delete a library, returning True if it was found and deleted."""
        return self._regions.remove_library(library)

    def get_pipeline_state(self, library: Library) -> LibraryPipelineState:
        """Return the pipeline state for a library (defaults when no rows)."""
        return self._regions.get_pipeline_state(library)

    def set_pipeline_axis(self, library: Library, axis: str, state: str) -> LibraryPipelineState:
        """Set one library pipeline axis and return the updated state."""
        return self._regions.set_pipeline_axis(library, axis, state)

    def get_libraries_in_axis_state(self, axis: str, state: str) -> list[Library]:
        """Return ``Library`` values whose pipeline axis equals ``state``."""
        return self._regions.get_libraries_in_axis_state(axis, state)

    def remove_pipeline_state(self, library: Library) -> None:
        """Remove all pipeline axes for a library."""
        self._regions.remove_pipeline_state(library)

    # ------------------------------------------------------------------
    # Song / folder forwarding (songs)
    # ------------------------------------------------------------------

    def get_song(self, song_id: int) -> Song | None:
        return self._songs.get_song(song_id)

    # Numeric-handle identity bridge (P3, song-tag correction) — non-tag
    # forwarders delegating to the song-side bridge on ``LibrarySongsDb``.

    def resolve_song_identity(self, song_id: int) -> SongIdentity | None:
        return self._songs.resolve_song_identity(song_id)

    def resolve_song_identities(self, song_ids: Sequence[int]) -> Mapping[int, SongIdentity]:
        return self._songs.resolve_song_identities(song_ids)

    def resolve_library_identity(self, library_id: int) -> LibraryIdentity | None:
        return self._songs.resolve_library_identity(library_id)

    def resolve_library_identities(self, library_ids: Sequence[int]) -> Mapping[int, LibraryIdentity]:
        return self._songs.resolve_library_identities(library_ids)

    def get_song_by_path(self, path: str, library: Library) -> Song | None:
        return self._songs.get_song_by_path(path, library)

    def get_song_by_normalized_path(self, normalized_path: str, library: Library) -> Song | None:
        return self._songs.get_song_by_normalized_path(normalized_path, library)

    def find_song_by_path_any_library(self, path: str) -> Song | None:
        return self._songs.find_song_by_path_any_library(path)

    def list_songs_by_ids(self, song_ids: list[int]) -> list[Song]:
        return self._songs.list_songs_by_ids(song_ids)

    def list_songs(self, library: Library, *, limit: int | None = None) -> list[Song]:
        return self._songs.list_songs(library, limit=limit)

    def count_songs(self, library: Library) -> int:
        return self._songs.count_songs(library)

    def get_library_ids_for_songs(self, song_ids: list[int]) -> dict[int, int]:
        return self._songs.get_library_ids_for_songs(song_ids)

    def count_recently_tagged(self, cutoff_ms: int) -> int:
        return self._songs.count_recently_tagged(cutoff_ms)

    def list_library_song_ids(self, library: Library, *, limit: int | None = None) -> list[int]:
        return self._songs.list_library_song_ids(library, limit=limit)

    def count_songs_for_library(self, library: Library) -> int:
        return self._songs.count_songs_for_library(library)

    def find_library_song_by_chromaprint(
        self,
        library: Library,
        chromaprint: str,
    ) -> Song | None:
        return self._songs.find_library_song_by_chromaprint(library, chromaprint)

    def add_song_to_library(self, library: Library, payload: dict) -> int:
        return self._songs.add_song_to_library(library, payload)

    def add_songs_to_library(
        self,
        library: Library,
        payloads: list[dict[str, Any]],
    ) -> list[int]:
        # Preserve the concurrent Song-domain facade migration; state
        # initialization is now an internal persistence intent.
        return self._songs.add_songs_to_library(library, payloads)

    def update_songs(
        self,
        library: Library,
        payloads: list[dict[str, Any]],
        *,
        remove_missing: bool = True,
    ) -> dict[str, int]:
        return self._songs.update_songs(library, payloads, remove_missing=remove_missing)

    def update_library_song_path(self, song_id: int, new_path: str) -> None:
        return self._songs.update_library_song_path(song_id, new_path)

    def update_library_song_scan_metadata(
        self,
        song_id: int,
        *,
        file_size: int,
        modified_time: int,
        duration_seconds: float | None = None,
        normalized_path: str | None = None,
    ) -> None:
        return self._songs.update_library_song_scan_metadata(
            song_id,
            file_size=file_size,
            modified_time=modified_time,
            duration_seconds=duration_seconds,
            normalized_path=normalized_path,
        )

    def update_library_song_modified_time(self, song_id: int, modified_time_ms: int) -> None:
        return self._songs.update_library_song_modified_time(song_id, modified_time_ms)

    def set_library_song_chromaprint(self, song_id: int, chromaprint: str) -> None:
        return self._songs.set_library_song_chromaprint(song_id, chromaprint)

    def update_library_song_last_tagged_at(self, song_id: int, tagged_at_ms: int) -> None:
        return self._songs.update_library_song_last_tagged_at(song_id, tagged_at_ms)

    def remove_song(self, song_id: int) -> None:
        return self._songs.remove_song(song_id)

    def remove_song_by_path(self, path: str, library: Library) -> None:
        return self._songs.remove_song_by_path(path, library)

    def list_existing_song_paths(self, library: Library, paths: list[str]) -> list[str]:
        return self._songs.list_existing_song_paths(library, paths)

    def get_folder(self, library: Library, folder_path: str) -> LibraryFolder | None:
        return self._songs.get_folder(library, folder_path)

    def list_folders_for_library(self, library: Library) -> list[LibraryFolder]:
        return self._songs.list_folders_for_library(library)

    def add_library_folder(self, library: Library, folder: LibraryFolder) -> LibraryFolder:
        return self._songs.add_library_folder(library, folder)

    def replace_library_folder(
        self,
        library: Library,
        folder_path: str,
        folder: LibraryFolder,
    ) -> LibraryFolder:
        return self._songs.replace_library_folder(library, folder_path, folder)

    def remove_library_folder(self, library: Library, folder_path: str) -> None:
        return self._songs.remove_library_folder(library, folder_path)

    def replace_library_folders(self, library: Library, folders: list[LibraryFolder]) -> None:
        return self._songs.replace_library_folders(library, folders)

    def list_songs_for_folder(
        self,
        library: Library,
        folder_rel_path: str,
    ) -> list[Song]:
        return self._songs.list_songs_for_folder(library, folder_rel_path)

    def list_tracks_for_matching(self, library: Library, *, limit: int | None = None) -> list[Song]:
        return self._songs.list_tracks_for_matching(library, limit=limit)

    # ------------------------------------------------------------------
    # Maintenance forwarding (songs)
    # ------------------------------------------------------------------

    def list_orphaned_song_ids(self) -> list[int]:
        return self._songs.list_orphaned_song_ids()

    def truncate_songs(self) -> None:
        return self._songs.truncate_songs()

    def truncate_song_links(self) -> None:
        return self._songs.truncate_song_links()

    def truncate_folder_links(self) -> None:
        return self._songs.truncate_folder_links()

    def truncate_folders(self) -> None:
        return self._songs.truncate_folders()

    # ------------------------------------------------------------------
    # Tag / song-tag forwarding (tags)
    # ------------------------------------------------------------------

    def get_tag(self, tag: TagRef) -> TagRef | None:
        return self._tags.get_tag(tag)

    def ensure_tag(self, tag: TagRef) -> TagRef:
        return self._tags.ensure_tag(tag)

    def list_tags_for_song(self, song: SongIdentity) -> tuple[SongTagAssignment, ...]:
        return self._tags.list_tags_for_song(song)

    def list_all_tag_names(self, limit: int) -> list[str]:
        return self._tags.list_all_tag_names(limit)

    def list_tags(
        self,
        *,
        name: str | None = None,
        search: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[TagRef, ...]:
        return self._tags.list_tags(name=name, search=search, limit=limit, offset=offset)

    def count_tags(self) -> int:
        return self._tags.count_tags()

    def count_tags_filtered(
        self,
        *,
        name: str | None = None,
        search: str | None = None,
    ) -> int:
        return self._tags.count_tags_filtered(name=name, search=search)

    def list_tags_with_song_count(
        self,
        *,
        name: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[TagUsage, ...]:
        return self._tags.list_tags_with_song_count(name=name, search=search, limit=limit, offset=offset)

    def list_genre_tags_for_songs(self, songs: Sequence[SongIdentity]) -> tuple[SongTagAssignment, ...]:
        return self._tags.list_genre_tags_for_songs(songs)

    def list_song_tags_for_songs(
        self,
        songs: Sequence[SongIdentity],
        *,
        name_starts_with: str | None = None,
    ) -> Mapping[SongIdentity, tuple[SongTagAssignment, ...]]:
        return self._tags.list_song_tags_for_songs(songs, name_starts_with=name_starts_with)

    def count_songs_by_tag(self, tag_key: str, target_value: str) -> int:
        return self._tags.count_songs_by_tag(tag_key, target_value)

    def count_songs_by_numeric_tag(self, tag_key: str, target_value: float | str) -> int:
        return self._tags.count_songs_by_numeric_tag(tag_key, target_value)

    def find_songs_with_numeric_tag(
        self,
        identity: TagRef,
        *,
        limit: int | None,
        offset: int = 0,
    ) -> tuple[SongTagMatch, ...]:
        return self._tags.find_songs_with_numeric_tag(
            identity,
            limit=limit,
            offset=offset,
        )

    def find_songs_with_tag(
        self,
        identity: TagRef,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> tuple[Song, ...]:
        return self._tags.find_songs_with_tag(identity, limit=limit, offset=offset)

    def find_songs_with_tag_contains(
        self,
        identity: TagRef,
        *,
        limit: int | None = None,
    ) -> tuple[Song, ...]:
        return self._tags.find_songs_with_tag_contains(identity, limit=limit)

    def find_songs_with_tag_pattern(
        self,
        tag_name: str,
        pattern: str,
        *,
        limit: int | None = None,
    ) -> tuple[Song, ...]:
        return self._tags.find_songs_with_tag_pattern(tag_name, pattern, limit=limit)

    def replace_song_tags(
        self,
        song: SongIdentity,
        assignments: Sequence[SongTagAssignment],
    ) -> None:
        return self._tags.replace_song_tags(song, assignments)

    def relink_tags(
        self,
        source: TagRef,
        target: TagRef,
        songs: Sequence[SongIdentity] | None = None,
    ) -> RelinkResult:
        return self._tags.relink_tags(source, target, songs=songs)

    def remove_song_tags(
        self,
        song: SongIdentity,
        identities: Sequence[TagRef] | None = None,
    ) -> None:
        return self._tags.remove_song_tags(song, identities)

    def list_tag_value_frequencies(self, tag_names: list[str], limit: int) -> dict[str, list[tuple[str, int]]]:
        return self._tags.list_tag_value_frequencies(tag_names, limit)

    # ------------------------------------------------------------------
    # Maintenance forwarding (tags)
    # ------------------------------------------------------------------

    def cleanup_orphaned_tags(self) -> TagCleanupResult:
        return self._tags.cleanup_orphaned_tags()

    def truncate_tags(self) -> None:
        return self._tags.truncate_tags()

    def truncate_song_tag_assignments(self) -> None:
        return self._tags.truncate_song_tag_assignments()

    # ------------------------------------------------------------------
    # Scan forwarding (scans)
    # ------------------------------------------------------------------

    def get_scan(self, library: Library) -> LibraryScan | None:
        """Return the latest scan summary for a domain ``Library``."""
        return self._scans.get_scan(library)

    def get_latest_successful_scan(self, library: Library) -> LibraryScan | None:
        """Return the latest completed scan for a library."""
        return self._scans.get_latest_successful_scan(library)

    def start_scan(self, library: Library, scan_type: str, started_at: int) -> LibraryScan:
        """Start a scan and return its domain summary, never its row id."""
        return self._scans.start_scan(library, scan_type, started_at)

    def record_scan_progress(
        self,
        library: Library,
        *,
        heartbeat_at: int,
        status: str | None = None,
        progress: int | None = None,
        total: int | None = None,
        scan_error: str | None = None,
    ) -> LibraryScan:
        return self._scans.record_scan_progress(
            library,
            heartbeat_at=heartbeat_at,
            status=status,
            progress=progress,
            total=total,
            scan_error=scan_error,
        )

    def complete_scan(self, library: Library, finished_at: int) -> LibraryScan:
        """Complete the current scan and return its domain summary."""
        return self._scans.complete_scan(library, finished_at)

    def remove_scan(self, library: Library) -> None:
        """Remove the latest scan for a domain ``Library``."""
        return self._scans.remove_scan(library)

    def truncate_scan_records(self) -> None:
        """Remove all scan history through the administrative scan intent."""
        return self._scans.truncate_scan_records()
