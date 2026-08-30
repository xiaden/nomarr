"""Library query operations.

This module handles:
- Library statistics
- File search and filtering
- Tag key/value discovery
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_records_comp import (
    get_library_record,
    list_all_libraries,
    list_library_records,
)
from nomarr.components.library.library_scan_state_comp import get_libraries_in_axis_state
from nomarr.components.library.library_song_query_comp import (
    count_recently_tagged,
    count_songs_by_tag,
    get_all_library_paths,
    get_library_stats,
    get_recently_processed,
    get_songs_by_ids_with_tags,
    get_tagged_file_paths,
    search_songs_by_tag,
)
from nomarr.components.library.library_song_state_comp import (
    count_errored_songs,
    get_errored_song_ids,
    get_uncalibrated_tagged_song_ids,
)
from nomarr.components.library.search_files_comp import (
    get_unique_tag_values,
    search_songs,
)
from nomarr.components.library.work_status_comp import compute_work_status
from nomarr.components.tagging.tag_query_comp import get_unique_mood_values
from nomarr.components.tagging.tag_stats_comp import get_unique_names
from nomarr.helpers.constants.pipeline_states import (
    CAL_NOT_CALIBRATED,
    CAL_STATE_FIELD,
    ML_NOT_PROCESSED,
    ML_STATE_FIELD,
    SCAN_IN_PROGRESS,
    SCAN_NOT_SCANNED,
    SCAN_STATE_FIELD,
    WRITE_NOT_WRITTEN,
    WRITE_STATE_FIELD,
)
from nomarr.helpers.dto.library_dto import (
    ErroredFileItem,
    ErroredFilesResult,
    LibraryStatsResult,
    SearchFilesQuery,
    SearchFilesResult,
    UniqueTagKeysResult,
    map_song_with_tags_to_dto,
)

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dto.info_dto import WorkStatusResult
    from nomarr.persistence.db import Database

    from .config import LibraryServiceConfig


class LibraryQueryMixin:
    """Mixin providing library query methods."""

    db: Database
    cfg: LibraryServiceConfig

    def _get_library_or_error(self, library: Library) -> Library:
        """Re-fetch a library by its natural identity or raise an error.

        Args:
            library: Domain ``Library`` (natural identity).

        Returns:
            The persisted domain ``Library`` value.

        Raises:
            ValueError: If the library does not exist.

        """
        result = get_library_record(self.db, library)
        if result is None:
            msg = f"Library not found: {library.name}"
            raise ValueError(msg)
        return result

    def get_library_stats(self) -> LibraryStatsResult:
        """Get library statistics (total files, total duration, etc.).

        Returns:
            LibraryStatsResult DTO

        """
        stats = get_library_stats(self.db)
        return LibraryStatsResult(
            total_files=stats.get("total_files", 0),
            total_artists=stats.get("total_artists", 0),
            total_albums=stats.get("total_albums", 0),
            total_duration=stats.get("total_duration"),
            total_size=stats.get("total_size"),
            needs_tagging_count=stats.get("needs_tagging_count", 0),
        )

    def get_all_library_paths(self) -> list[str]:
        """Get all file paths in the library.

        Returns:
            List of absolute file paths

        """
        return get_all_library_paths(self.db)

    def get_tagged_library_paths(self) -> list[str]:
        """Get all file paths that have been tagged (have tags in database).

        Returns:
            List of absolute file paths that have been tagged

        """
        return get_tagged_file_paths(self.db)

    def get_paths_needing_calibration(self) -> list[str]:
        """Get tagged file paths that are not yet calibrated.

        Iterates all enabled libraries and collects uncalibrated-but-tagged
        file IDs, then resolves them to absolute paths.

        Returns:
            List of absolute file paths needing calibration.

        """
        libraries = [lib for lib in list_all_libraries(self.db) if lib.is_enabled]
        all_file_ids: list[int] = []
        for lib in libraries:
            all_file_ids.extend(get_uncalibrated_tagged_song_ids(self.db, lib))
        if not all_file_ids:
            return []
        files = get_songs_by_ids_with_tags(self.db, all_file_ids)
        return [f["path"] for f in files if f.get("path")]

    def search_files(self, query: SearchFilesQuery) -> SearchFilesResult:
        """Search library files with optional filters.

        Args:
            query: Search parameters including query_text, limit, offset,
                sort_by, sort_dir, and domain-specific filters.

        Returns:
            SearchFilesResult DTO with files (including tags), total count,
            limit, and offset.

        """
        files, total = search_songs(self.db, query)
        files_with_tags = [map_song_with_tags_to_dto(f) for f in files]
        return SearchFilesResult(songs=files_with_tags, total=total, limit=query.limit, offset=query.offset)

    def get_files_by_ids(self, file_ids: list[int]) -> SearchFilesResult:
        """Get files by IDs with their tags.

        Used for batch lookup (e.g., when browsing songs for an entity).

        Args:
            file_ids: List of file _ids to fetch

        Returns:
            SearchFilesResult with files matching the IDs

        """
        files = get_songs_by_ids_with_tags(self.db, [int(fid) for fid in file_ids])
        files_with_tags = [map_song_with_tags_to_dto(f) for f in files]
        return SearchFilesResult(songs=files_with_tags, total=len(files), limit=len(file_ids), offset=0)

    def search_songs_by_tag(
        self,
        tag_key: str,
        target_value: float | str,
        limit: int = 100,
        offset: int = 0,
    ) -> SearchFilesResult:
        """Search files by tag value with distance sorting (float) or exact match (string).

        For float values: Returns files sorted by absolute distance from target value.
        For string values: Returns files with exact match on the tag value.

        Args:
            tag_key: Tag key to search (e.g., "nom:bpm", "genre")
            target_value: Target value (float for distance sort, string for exact match)
            limit: Maximum number of results
            offset: Pagination offset

        Returns:
            SearchFilesResult with matched files (includes distance for float searches)

        """
        files = search_songs_by_tag(self.db, tag_key, target_value, limit, offset)
        total = count_songs_by_tag(self.db, tag_key, target_value)
        files_with_tags = [map_song_with_tags_to_dto(f) for f in files]
        return SearchFilesResult(songs=files_with_tags, total=total, limit=limit, offset=offset)

    def get_unique_tag_keys(self, nomarr_only: bool = False) -> UniqueTagKeysResult:
        """Get all unique tag keys across the library.

        Args:
            nomarr_only: If True, only return Nomarr-generated tag keys.

        Returns:
            UniqueTagKeysResult DTO with tag_keys list and total count.

        """
        keys = get_unique_names(self.db, nomarr_only)
        return UniqueTagKeysResult(tag_keys=keys, count=len(keys), calibration=None, library_id=None)

    def get_unique_tag_values(self, tag_key: str, nomarr_only: bool = False) -> UniqueTagKeysResult:
        """Get all unique values for a specific tag key.

        Args:
            tag_key: Tag key to query (e.g., "genre", "nom:mood-strict").
            nomarr_only: If True, only return Nomarr-generated tag values.

        Returns:
            UniqueTagKeysResult DTO with tag_keys list and total count.

        """
        values = get_unique_tag_values(self.db, tag_key, nomarr_only)
        return UniqueTagKeysResult(tag_keys=values, count=len(values), calibration=None, library_id=None)

    def get_unique_mood_values(self, mood_tier: str = "mood-strict", limit: int = 100) -> UniqueTagKeysResult:
        """Get unique individual mood values extracted from tuple string tags.

        Args:
            mood_tier: Mood tier to filter by (e.g., "mood-strict", "mood-broad").
            limit: Maximum number of results to return.

        Returns:
            UniqueTagKeysResult DTO with tag_keys list and total count.

        """
        values = get_unique_mood_values(self.db, mood_tier=mood_tier, limit=limit)
        return UniqueTagKeysResult(tag_keys=values, count=len(values), calibration=None, library_id=None)

    def get_work_status(self) -> WorkStatusResult:
        """Get unified work status for the system.

        Returns status of:
        - Scanning: Any library currently being scanned
        - Processing: ML inference on audio files (pending/processed counts)
        - Velocity: Rolling 5-minute processing rate from actual timestamps

        This method is designed for frontend polling to show activity indicators.

        Returns:
            WorkStatusResult DTO with scanning and processing status

        """
        libraries = list_library_records(self.db, enabled_only=False)
        stats = self.get_library_stats()
        recently_tagged = count_recently_tagged(self.db)

        # Build per-axis pipeline states for all libraries, keyed by natural name.
        scan_not_names = {lib.name for lib in get_libraries_in_axis_state(self.db, SCAN_STATE_FIELD, SCAN_NOT_SCANNED)}
        scan_ing_names = {lib.name for lib in get_libraries_in_axis_state(self.db, SCAN_STATE_FIELD, SCAN_IN_PROGRESS)}
        ml_names = {lib.name for lib in get_libraries_in_axis_state(self.db, ML_STATE_FIELD, ML_NOT_PROCESSED)}
        cal_names = {lib.name for lib in get_libraries_in_axis_state(self.db, CAL_STATE_FIELD, CAL_NOT_CALIBRATED)}
        tw_names = {lib.name for lib in get_libraries_in_axis_state(self.db, WRITE_STATE_FIELD, WRITE_NOT_WRITTEN)}

        pipeline_states: dict[str, dict[str, str]] = {}
        for lib in libraries:
            name = lib.name

            if name in scan_ing_names:
                scan_state = SCAN_IN_PROGRESS
            elif name in scan_not_names:
                scan_state = SCAN_NOT_SCANNED
            else:
                scan_state = "scanned"

            pipeline_states[name] = {
                SCAN_STATE_FIELD: scan_state,
                ML_STATE_FIELD: "not_ML_processed" if name in ml_names else "ML_processed",
                CAL_STATE_FIELD: "not_calibrated" if name in cal_names else "calibrated",
                WRITE_STATE_FIELD: "not_written" if name in tw_names else "written",
            }

        return compute_work_status(
            libraries,
            stats,
            recently_tagged,
            pipeline_states,
            library_docs=libraries,
        )

    def get_recently_processed(
        self,
        limit: int = 20,
        library: Library | None = None,
    ) -> list[dict[str, Any]]:
        """Get recently processed files.

        Args:
            limit: Maximum number of files to return.
            library: Optional ``Library`` scope to filter by (natural identity).

        Returns:
            List of {file_id, path, title, artist, album, scanned_at}
            sorted by scanned_at DESC.

        """
        return get_recently_processed(self.db, limit=limit, library=library)

    def get_errored_files(self, library: Library) -> ErroredFilesResult:
        """Get errored files for a library with basic metadata.

        Args:
            library: Domain ``Library`` (natural identity).

        Returns:
            ErroredFilesResult with file list and total count.

        Raises:
            ValueError: If library does not exist.

        """
        self._get_library_or_error(library)
        total = count_errored_songs(self.db, library)
        errored_ids = get_errored_song_ids(self.db, library)
        files_raw = get_songs_by_ids_with_tags(self.db, errored_ids)
        files: list[ErroredFileItem] = [
            ErroredFileItem(
                id=f["id"],
                path=f["path"],
                duration_seconds=f.get("duration_seconds"),
                artist=f.get("artist"),
                title=f.get("title"),
            )
            for f in files_raw
        ]
        return ErroredFilesResult(files=files, total=total)
