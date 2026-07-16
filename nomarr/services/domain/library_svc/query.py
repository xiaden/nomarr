"""Library query operations.

This module handles:
- Library statistics
- File search and filtering
- Tag key/value discovery
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_file_query_comp import (
    count_files_by_tag,
    count_recently_tagged,
    get_all_library_paths,
    get_files_by_ids_with_tags,
    get_library_stats,
    get_recently_processed,
    get_tagged_file_paths,
    search_files_by_tag,
)
from nomarr.components.library.library_file_state_comp import (
    count_errored_files,
    get_errored_file_ids,
    get_uncalibrated_tagged_file_ids,
)
from nomarr.components.library.library_records_comp import get_library_record, list_library_records
from nomarr.components.library.library_scan_state_comp import get_libraries_in_axis_state
from nomarr.components.library.search_files_comp import (
    get_unique_tag_values,
    search_library_files,
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
from nomarr.helpers.dto.info_dto import WorkStatusResult
from nomarr.helpers.dto.library_dto import (
    ErroredFileItem,
    ErroredFilesResult,
    LibraryStatsResult,
    SearchFilesQuery,
    SearchFilesResult,
    UniqueTagKeysResult,
    map_file_with_tags_to_dto,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

    from .config import LibraryServiceConfig


class LibraryQueryMixin:
    """Mixin providing library query methods."""

    db: Database
    cfg: LibraryServiceConfig

    async def _get_library_or_error(self, library_id: str) -> dict[str, Any]:
        """Get a library by ID or raise an error."""
        result = await get_library_record(self.db, int(library_id))
        if result is None:
            msg = f"Library not found: {library_id}"
            raise ValueError(msg)
        return result

    async def get_library_stats(self) -> LibraryStatsResult:
        """Get library statistics (total files, total duration, etc.).

        Returns:
            LibraryStatsResult DTO

        """
        stats = await get_library_stats(self.db)
        return LibraryStatsResult(
            total_files=stats.get("total_files", 0),
            total_artists=stats.get("total_artists", 0),
            total_albums=stats.get("total_albums", 0),
            total_duration=stats.get("total_duration"),
            total_size=stats.get("total_size"),
            needs_tagging_count=stats.get("needs_tagging_count", 0),
        )

    async def get_all_library_paths(self) -> list[str]:
        """Get all file paths in the library.

        Returns:
            List of absolute file paths

        """
        return await get_all_library_paths(self.db)

    async def get_tagged_library_paths(self) -> list[str]:
        """Get all file paths that have been tagged (have tags in database).

        Returns:
            List of absolute file paths that have been tagged

        """
        return await get_tagged_file_paths(self.db)

    async def get_paths_needing_calibration(self) -> list[str]:
        """Get tagged file paths that are not yet calibrated.

        Iterates all enabled libraries and collects uncalibrated-but-tagged
        file IDs, then resolves them to absolute paths.

        Returns:
            List of absolute file paths needing calibration.

        """
        libraries = await list_library_records(self.db, enabled_only=True)
        all_file_ids: list[int] = []
        for lib in libraries:
            file_ids = await get_uncalibrated_tagged_file_ids(self.db, lib.id)
            all_file_ids.extend(file_ids)
        if not all_file_ids:
            return []
        files = await get_files_by_ids_with_tags(self.db, all_file_ids)
        return [f["path"] for f in files if f.get("path")]

    async def search_files(self, query: SearchFilesQuery) -> SearchFilesResult:
        """Search library files with optional filters.

        Args:
            query: Search parameters including query_text, limit, offset,
                sort_by, sort_dir, and domain-specific filters.

        Returns:
            SearchFilesResult DTO with files (including tags), total count,
            limit, and offset.

        """
        files, total = await search_library_files(self.db, query)
        files_with_tags = [map_file_with_tags_to_dto(f) for f in files]
        return SearchFilesResult(files=files_with_tags, total=total, limit=query.limit, offset=query.offset)

    async def get_files_by_ids(self, file_ids: list[str]) -> SearchFilesResult:
        """Get files by IDs with their tags.

        Used for batch lookup (e.g., when browsing songs for an entity).

        Args:
            file_ids: List of file _ids to fetch

        Returns:
            SearchFilesResult with files matching the IDs

        """
        files = await get_files_by_ids_with_tags(self.db, [int(fid) for fid in file_ids])
        files_with_tags = [map_file_with_tags_to_dto(f) for f in files]
        return SearchFilesResult(files=files_with_tags, total=len(files), limit=len(file_ids), offset=0)

    async def search_files_by_tag(
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
        files = await search_files_by_tag(self.db, tag_key, target_value, limit, offset)
        total = await count_files_by_tag(self.db, tag_key, target_value)
        files_with_tags = [map_file_with_tags_to_dto(f) for f in files]
        return SearchFilesResult(files=files_with_tags, total=total, limit=limit, offset=offset)

    async def get_unique_tag_keys(self, nomarr_only: bool = False) -> UniqueTagKeysResult:
        """Get all unique tag keys across the library.

        Args:
            nomarr_only: If True, only return Nomarr-generated tag keys.

        Returns:
            UniqueTagKeysResult DTO with tag_keys list and total count.

        """
        keys = await get_unique_names(self.db, nomarr_only)
        return UniqueTagKeysResult(tag_keys=keys, count=len(keys), calibration=None, library_id=None)

    async def get_unique_tag_values(self, tag_key: str, nomarr_only: bool = False) -> UniqueTagKeysResult:
        """Get all unique values for a specific tag key.

        Args:
            tag_key: Tag key to query (e.g., "genre", "nom:mood-strict").
            nomarr_only: If True, only return Nomarr-generated tag values.

        Returns:
            UniqueTagKeysResult DTO with tag_keys list and total count.

        """
        values = await get_unique_tag_values(self.db, tag_key, nomarr_only)
        return UniqueTagKeysResult(tag_keys=values, count=len(values), calibration=None, library_id=None)

    async def get_unique_mood_values(self, mood_tier: str = "mood-strict", limit: int = 100) -> UniqueTagKeysResult:
        """Get unique individual mood values extracted from tuple string tags.

        Args:
            mood_tier: Mood tier to filter by (e.g., "mood-strict", "mood-broad").
            limit: Maximum number of results to return.

        Returns:
            UniqueTagKeysResult DTO with tag_keys list and total count.

        """
        values = await get_unique_mood_values(self.db, mood_tier=mood_tier, limit=limit)
        return UniqueTagKeysResult(tag_keys=values, count=len(values), calibration=None, library_id=None)

    async def get_work_status(self) -> WorkStatusResult:
        """Get unified work status for the system.

        Returns status of:
        - Scanning: Any library currently being scanned
        - Processing: ML inference on audio files (pending/processed counts)
        - Velocity: Rolling 5-minute processing rate from actual timestamps

        This method is designed for frontend polling to show activity indicators.

        Returns:
            WorkStatusResult DTO with scanning and processing status

        """
        libraries = await list_library_records(self.db, enabled_only=False)
        stats = await self.get_library_stats()
        recently_tagged = await count_recently_tagged(self.db)

        # Build per-axis pipeline states for all libraries
        scan_not_set = await get_libraries_in_axis_state(self.db, SCAN_STATE_FIELD, SCAN_NOT_SCANNED)
        scan_ing_set = await get_libraries_in_axis_state(self.db, SCAN_STATE_FIELD, SCAN_IN_PROGRESS)
        ml_set = await get_libraries_in_axis_state(self.db, ML_STATE_FIELD, ML_NOT_PROCESSED)
        cal_set = await get_libraries_in_axis_state(self.db, CAL_STATE_FIELD, CAL_NOT_CALIBRATED)
        tw_set = await get_libraries_in_axis_state(self.db, WRITE_STATE_FIELD, WRITE_NOT_WRITTEN)

        pipeline_states: dict[str, dict[str, str]] = {}
        for lib in libraries:
            lib_id = str(lib.id)

            if lib_id in scan_ing_set:
                scan_state = SCAN_IN_PROGRESS
            elif lib_id in scan_not_set:
                scan_state = SCAN_NOT_SCANNED
            else:
                scan_state = "scanned"

            pipeline_states[lib_id] = {
                SCAN_STATE_FIELD: scan_state,
                ML_STATE_FIELD: "not_ML_processed" if lib_id in ml_set else "ML_processed",
                CAL_STATE_FIELD: "not_calibrated" if lib_id in cal_set else "calibrated",
                WRITE_STATE_FIELD: "not_written" if lib_id in tw_set else "written",
            }

        return compute_work_status(
            libraries,
            stats,
            recently_tagged,
            pipeline_states,
            library_docs=libraries,
        )

    async def get_recently_processed(
        self,
        limit: int = 20,
        library_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get recently processed files.

        Args:
            limit: Maximum number of files to return.
            library_id: Optional library _id to filter by.

        Returns:
            List of {file_id, path, title, artist, album, scanned_at}
            sorted by scanned_at DESC.

        """
        return await get_recently_processed(self.db, limit=limit, library_id=int(library_id) if library_id is not None else None)

    async def get_errored_files(self, library_id: str) -> ErroredFilesResult:
        """Get errored files for a library with basic metadata.

        Args:
            library_id: Library key to query

        Returns:
            ErroredFilesResult with file list and total count

        Raises:
            ValueError: If library does not exist

        """
        await self._get_library_or_error(library_id)
        total = await count_errored_files(self.db, int(library_id))
        errored_ids = await get_errored_file_ids(self.db, int(library_id))
        files_raw = await get_files_by_ids_with_tags(self.db, errored_ids)
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
