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
from nomarr.components.library.scan_lifecycle_comp import get_libraries_in_pipeline_state
from nomarr.components.library.search_files_comp import (
    get_unique_tag_keys,
    get_unique_tag_values,
    search_library_files,
)
from nomarr.components.library.work_status_comp import compute_work_status
from nomarr.components.tagging.tag_query_comp import get_unique_mood_values
from nomarr.helpers.constants.pipeline_states import (
    PIPELINE_APPLYING,
    PIPELINE_AWAITING_CALIBRATION,
    PIPELINE_CALIBRATING,
    PIPELINE_DONE,
    PIPELINE_IDLE,
    PIPELINE_ML_RUNNING,
    PIPELINE_SCANNING,
    PIPELINE_TOO_SMALL,
    PIPELINE_WRITE_READY,
    PIPELINE_WRITING,
)
from nomarr.helpers.dto.info_dto import WorkStatusResult
from nomarr.helpers.dto.library_dto import (
    ErroredFileItem,
    ErroredFilesResult,
    LibraryStatsResult,
    SearchFilesQuery,
    SearchFilesResult,
    UniqueTagKeysResult,
)
from nomarr.services.domain._library_mapping import map_file_with_tags_to_dto

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

    from .config import LibraryServiceConfig


_PIPELINE_STATE_DOC_IDS: tuple[str, ...] = (
    PIPELINE_IDLE,
    PIPELINE_SCANNING,
    PIPELINE_ML_RUNNING,
    PIPELINE_TOO_SMALL,
    PIPELINE_AWAITING_CALIBRATION,
    PIPELINE_CALIBRATING,
    PIPELINE_APPLYING,
    PIPELINE_WRITE_READY,
    PIPELINE_WRITING,
    PIPELINE_DONE,
)


class LibraryQueryMixin:
    """Mixin providing library query methods."""

    db: Database
    cfg: LibraryServiceConfig

    def _get_library_or_error(self, library_id: str) -> dict[str, Any]:
        """Get a library by ID or raise an error."""
        result = get_library_record(self.db, library_id)
        if result is None:
            msg = f"Library not found: {library_id}"
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
        libraries = list_library_records(self.db, enabled_only=True)
        all_file_ids: list[str] = []
        for lib in libraries:
            file_ids = get_uncalibrated_tagged_file_ids(self.db, lib["_id"])
            all_file_ids.extend(file_ids)
        if not all_file_ids:
            return []
        files = get_files_by_ids_with_tags(self.db, all_file_ids)
        return [f["path"] for f in files if f.get("path")]

    def search_files(self, query: SearchFilesQuery) -> SearchFilesResult:
        """Search library files with optional filters."""
        files, total = search_library_files(self.db, query)
        files_with_tags = [map_file_with_tags_to_dto(f) for f in files]
        return SearchFilesResult(files=files_with_tags, total=total, limit=query.limit, offset=query.offset)

    def get_files_by_ids(self, file_ids: list[str]) -> SearchFilesResult:
        """Get files by IDs with their tags.

        Used for batch lookup (e.g., when browsing songs for an entity).

        Args:
            file_ids: List of file _ids to fetch

        Returns:
            SearchFilesResult with files matching the IDs

        """
        files = get_files_by_ids_with_tags(self.db, file_ids)
        files_with_tags = [map_file_with_tags_to_dto(f) for f in files]
        return SearchFilesResult(files=files_with_tags, total=len(files), limit=len(file_ids), offset=0)

    def search_files_by_tag(
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
        files = search_files_by_tag(self.db, tag_key, target_value, limit, offset)
        total = count_files_by_tag(self.db, tag_key, target_value)
        files_with_tags = [map_file_with_tags_to_dto(f) for f in files]
        return SearchFilesResult(files=files_with_tags, total=total, limit=limit, offset=offset)

    def get_unique_tag_keys(self, nomarr_only: bool = False) -> UniqueTagKeysResult:
        """Get all unique tag keys across the library."""
        keys = get_unique_tag_keys(self.db, nomarr_only)
        return UniqueTagKeysResult(tag_keys=keys, count=len(keys), calibration=None, library_id=None)

    def get_unique_tag_values(self, tag_key: str, nomarr_only: bool = False) -> UniqueTagKeysResult:
        """Get all unique values for a specific tag key."""
        values = get_unique_tag_values(self.db, tag_key, nomarr_only)
        return UniqueTagKeysResult(tag_keys=values, count=len(values), calibration=None, library_id=None)

    def get_unique_mood_values(self, mood_tier: str = "mood-strict", limit: int = 100) -> UniqueTagKeysResult:
        """Get unique individual mood values extracted from tuple string tags."""
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
        pipeline_states: dict[str, str] = {}
        for state_doc_id in _PIPELINE_STATE_DOC_IDS:
            state_key = state_doc_id.rsplit("/", 1)[-1]
            for library_id in get_libraries_in_pipeline_state(self.db, state_doc_id):
                pipeline_states[library_id] = state_key

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
        return get_recently_processed(self.db, limit=limit, library_id=library_id)

    def get_errored_files(self, library_id: str) -> ErroredFilesResult:
        """Get errored files for a library with basic metadata.

        Args:
            library_id: Library key to query

        Returns:
            ErroredFilesResult with file list and total count

        Raises:
            ValueError: If library does not exist

        """
        self._get_library_or_error(library_id)
        total = count_errored_files(self.db, library_id)
        errored_ids = get_errored_file_ids(self.db, library_id)
        files_raw = get_files_by_ids_with_tags(self.db, errored_ids)
        files: list[ErroredFileItem] = [
            ErroredFileItem(
                _id=f["_id"],
                path=f["path"],
                duration_seconds=f.get("duration_seconds"),
                artist=f.get("artist"),
                title=f.get("title"),
            )
            for f in files_raw
        ]
        return ErroredFilesResult(files=files, total=total)
