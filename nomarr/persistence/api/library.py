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
    from sqlalchemy.orm import Session, scoped_session

    from nomarr.helpers.dto.repo_dto import (
        LibraryFolderRow,
        LibraryRow,
        LibraryScanRow,
        SongRow,
        TagRow,
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

    def create_library(
        self,
        *,
        name: str,
        root_path: str,
        is_enabled: bool,
        watch_mode: str,
        file_write_mode: str,
        library_auto_write: bool,
        created_at: int,
        updated_at: int,
    ) -> int:
        """Create a library from the supported library properties."""
        return self._regions.create_library(
            name=name,
            root_path=root_path,
            is_enabled=is_enabled,
            watch_mode=watch_mode,
            file_write_mode=file_write_mode,
            library_auto_write=library_auto_write,
            created_at=created_at,
            updated_at=updated_at,
        )

    def get_library(self, library_id: int) -> LibraryRow | None:
        return self._regions.get_library(library_id)

    def get_library_by_name(self, name: str) -> LibraryRow | None:
        return self._regions.get_library_by_name(name)

    def list_libraries(self, *, enabled_only: bool = False) -> list[LibraryRow]:
        return self._regions.list_libraries(enabled_only=enabled_only)

    def list_library_keys(self) -> list[int]:
        return self._regions.list_library_keys()

    def update_library(self, library_id: int, fields: dict[str, object]) -> None:
        """Update all supplied library columns in one transaction."""
        self._regions.update_library(library_id, fields)

    def rename_library(self, library_id: int, name: str, *, updated_at: int) -> None:
        self._regions.rename_library(library_id, name, updated_at=updated_at)

    def change_library_root(self, library_id: int, root_path: str, *, updated_at: int) -> None:
        self._regions.change_library_root(library_id, root_path, updated_at=updated_at)

    def enable_library(self, library_id: int, is_enabled: bool, *, updated_at: int) -> None:
        self._regions.enable_library(library_id, is_enabled, updated_at=updated_at)

    def update_library_metadata(
        self,
        library_id: int,
        *,
        watch_mode: str | None = None,
        file_write_mode: str | None = None,
        library_auto_write: bool | None = None,
        updated_at: int,
    ) -> None:
        self._regions.update_library_metadata(
            library_id,
            watch_mode=watch_mode,
            file_write_mode=file_write_mode,
            library_auto_write=library_auto_write,
            updated_at=updated_at,
        )

    def get_pipeline_state(self, library_id: int) -> dict[str, str] | None:
        return self._regions.get_pipeline_state(library_id)

    def get_libraries_in_axis_state(self, axis_field: str, axis_value: str) -> list[int]:
        return self._regions.get_libraries_in_axis_state(axis_field, axis_value)

    def remove_library(self, library_id: int) -> bool:
        return self._regions.remove_library(library_id)

    # ------------------------------------------------------------------
    # Song / folder forwarding (songs)
    # ------------------------------------------------------------------

    def get_song(self, song_id: int) -> SongRow | None:
        return self._songs.get_song(song_id)

    def get_song_by_path(self, path: str, library_id: int) -> SongRow | None:
        return self._songs.get_song_by_path(path, library_id)

    def find_song_by_path_any_library(self, path: str) -> SongRow | None:
        return self._songs.find_song_by_path_any_library(path)

    def list_songs_by_ids(self, song_ids: list[int]) -> list[SongRow]:
        return self._songs.list_songs_by_ids(song_ids)

    def list_songs(self, library_id: int, *, limit: int | None = None) -> list[SongRow]:
        return self._songs.list_songs(library_id, limit=limit)

    def count_songs(self, library_id: int) -> int:
        return self._songs.count_songs(library_id)

    def get_library_ids_for_songs(self, song_ids: list[int]) -> dict[int, int]:
        return self._songs.get_library_ids_for_songs(song_ids)

    def count_recently_tagged(self, cutoff_ms: int) -> int:
        return self._songs.count_recently_tagged(cutoff_ms)

    def list_library_song_ids(self, library_id: int, *, limit: int | None = None) -> list[int]:
        return self._songs.list_library_song_ids(library_id, limit=limit)

    def count_songs_for_library(self, library_id: int) -> int:
        return self._songs.count_songs_for_library(library_id)

    def find_library_song_by_chromaprint(
        self,
        library_id: int,
        chromaprint: str,
    ) -> SongRow | None:
        return self._songs.find_library_song_by_chromaprint(library_id, chromaprint)

    def add_song_to_library(self, library_id: int, payload: dict) -> int:
        return self._songs.add_song_to_library(library_id, payload)

    def add_songs_to_library(
        self,
        library_id: int,
        payloads: list[dict[str, Any]],
        *,
        initial_state: str = "tagged",
    ) -> list[int]:
        return self._songs.add_songs_to_library(library_id, payloads, initial_state=initial_state)

    def update_songs(
        self,
        library_id: int,
        payloads: list[dict[str, Any]],
        *,
        remove_missing: bool = True,
    ) -> dict[str, int]:
        return self._songs.update_songs(library_id, payloads, remove_missing=remove_missing)

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

    def update_library_song_duration(self, song_id: int, duration_seconds: float) -> None:
        return self._songs.update_library_song_duration(song_id, duration_seconds)

    def update_library_song_metadata_cache(self, song_id: int, fields: dict[str, Any]) -> None:
        return self._songs.update_library_song_metadata_cache(song_id, fields)

    def remove_song(self, song_id: int) -> None:
        return self._songs.remove_song(song_id)

    def remove_song_by_path(self, path: str, library_id: int | None = None) -> None:
        return self._songs.remove_song_by_path(path, library_id)

    def list_existing_song_paths(self, paths: list[str]) -> list[str]:
        return self._songs.list_existing_song_paths(paths)

    def get_folder(self, folder_id: int) -> LibraryFolderRow | None:
        return self._songs.get_folder(folder_id)

    def list_folders_for_library(self, library_id: int) -> list[LibraryFolderRow]:
        return self._songs.list_folders_for_library(library_id)

    def add_library_folder(self, library_id: int, payload: dict[str, Any]) -> int:
        return self._songs.add_library_folder(library_id, payload)

    def replace_library_folder(self, library_id: int, folder_id: int, payload: dict[str, Any]) -> None:
        return self._songs.replace_library_folder(library_id, folder_id, payload)

    def remove_library_folder(self, library_id: int, folder_id: int) -> None:
        return self._songs.remove_library_folder(library_id, folder_id)

    def replace_library_folders(self, library_id: int, payloads: list[dict[str, Any]]) -> None:
        return self._songs.replace_library_folders(library_id, payloads)

    def list_songs_for_folder(
        self,
        library_id: int,
        folder_rel_path: str,
    ) -> list[SongRow]:
        return self._songs.list_songs_for_folder(library_id, folder_rel_path)

    def list_tracks_for_matching(self, library_id: int, *, limit: int | None = None) -> list[SongRow]:
        return self._songs.list_tracks_for_matching(library_id, limit=limit)

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

    def get_tag(self, tag_id: int) -> TagRow | None:
        return self._tags.get_tag(tag_id)

    def find_or_create_tag(self, name: str, value: str, namespace: str) -> int:
        return self._tags.find_or_create_tag(name, value, namespace)

    def list_tags_for_song(self, song_id: int) -> list[TagRow]:
        return self._tags.list_tags_for_song(song_id)

    def list_all_tag_names(self, limit: int) -> list[str]:
        return self._tags.list_all_tag_names(limit)

    def list_tags(
        self,
        *,
        name: str | None = None,
        value: Any = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[TagRow]:
        return self._tags.list_tags(name=name, value=value, limit=limit, offset=offset)

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
    ) -> list[dict]:
        return self._tags.list_tags_with_song_count(name=name, search=search, limit=limit, offset=offset)

    def list_tags_by_name(self, name: str, limit: int) -> list[TagRow]:
        return self._tags.list_tags_by_name(name, limit)

    def list_genre_tags_for_songs(self, song_ids: list[int]) -> list[TagRow]:
        return self._tags.list_genre_tags_for_songs(song_ids)

    def list_song_tags_for_songs(
        self,
        song_ids: list[int],
        *,
        name_starts_with: str | None = None,
    ) -> dict[int, list[TagRow]]:
        return self._tags.list_song_tags_for_songs(song_ids, name_starts_with=name_starts_with)

    def count_songs_by_tag(self, tag_key: str, target_value: str) -> int:
        return self._tags.count_songs_by_tag(tag_key, target_value)

    def search_songs_by_tag(
        self,
        tag_key: str,
        value: str,
        *,
        limit: int | None,
    ) -> list[SongRow]:
        return self._tags.search_songs_by_tag(tag_key, value, limit=limit)

    def search_songs_by_tag_contains(
        self,
        tag_key: str,
        value: str,
        *,
        limit: int | None,
    ) -> list[SongRow]:
        return self._tags.search_songs_by_tag_contains(tag_key, value, limit=limit)

    def search_songs_by_tag_pattern(
        self,
        tag_name: str,
        pattern: str,
        *,
        limit: int | None = None,
    ) -> list[SongRow]:
        return self._tags.search_songs_by_tag_pattern(tag_name, pattern, limit=limit)

    def list_song_ids_for_tag_id(self, tag_id: int, *, limit: int | None, offset: int = 0) -> list[int]:
        return self._tags.list_song_ids_for_tag_id(tag_id, limit=limit, offset=offset)

    def list_song_tag_edges(
        self,
        tag_ids: list[int],
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        return self._tags.list_song_tag_edges(tag_ids, limit=limit)

    def replace_song_tags(self, song_id: int, tags: list[dict]) -> None:
        return self._tags.replace_song_tags(song_id, tags)

    def replace_tag_references(self, source_tag_id: int, target_tag_id: int) -> None:
        return self._tags.replace_tag_references(source_tag_id, target_tag_id)

    def replace_selected_tag_references(
        self,
        song_ids: list[int],
        source_tag_id: int,
        target_tag_id: int,
    ) -> None:
        return self._tags.replace_selected_tag_references(song_ids, source_tag_id, target_tag_id)

    def remove_song_tags(self, song_id: int, tag_keys: list[int] | None = None) -> None:
        return self._tags.remove_song_tags(song_id, tag_keys)

    def list_tag_value_frequencies(self, tag_names: list[str], limit: int) -> dict[str, list[tuple[str, int]]]:
        return self._tags.list_tag_value_frequencies(tag_names, limit)

    # ------------------------------------------------------------------
    # Maintenance forwarding (tags)
    # ------------------------------------------------------------------

    def list_orphaned_tag_ids(self) -> list[int]:
        return self._tags.list_orphaned_tag_ids()

    def delete_tags_by_ids(self, tag_ids: list[int]) -> int:
        return self._tags.delete_tags_by_ids(tag_ids)

    def truncate_tags(self) -> None:
        return self._tags.truncate_tags()

    def truncate_song_tag_edges(self) -> None:
        return self._tags.truncate_song_tag_edges()

    # ------------------------------------------------------------------
    # Scan forwarding (scans)
    # ------------------------------------------------------------------

    def get_scan(self, library_id: int) -> LibraryScanRow | None:
        return self._scans.get_scan(library_id)

    def add_scan(self, library_id: int, payload: dict[str, Any]) -> int:
        return self._scans.add_scan(library_id, payload)

    def start_scan(self, library_id: int, scan_type: str, started_at: int) -> int:
        return self._scans.start_scan(library_id, scan_type, started_at)

    def record_scan_progress(
        self,
        library_id: int,
        *,
        heartbeat_at: int,
        status: str | None = None,
        progress: int | None = None,
        total: int | None = None,
        scan_error: str | None = None,
    ) -> None:
        return self._scans.record_scan_progress(
            library_id,
            heartbeat_at=heartbeat_at,
            status=status,
            progress=progress,
            total=total,
            scan_error=scan_error,
        )

    def complete_scan(self, library_id: int, finished_at: int) -> None:
        return self._scans.complete_scan(library_id, finished_at)

    def remove_scan(self, library_id: int) -> None:
        return self._scans.remove_scan(library_id)

    def truncate_scan_records(self) -> None:
        return self._scans.truncate_scan_records()
