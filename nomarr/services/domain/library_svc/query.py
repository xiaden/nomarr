"""Library query operations.

This module handles:
- Library statistics
- File search and filtering
- Tag key/value discovery
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.helpers.dto.library_dto import (
    LibraryStatsResult,
    SearchFilesResult,
    UniqueTagKeysResult,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

    from .config import LibraryServiceConfig


class LibraryQueryMixin:
    """Mixin providing library query methods."""

    db: Database
    cfg: LibraryServiceConfig

    def get_library_stats(self) -> LibraryStatsResult:
        """
        Get library statistics (total files, total duration, etc.).

        Returns:
            LibraryStatsResult DTO
        """
        stats = self.db.library_files.get_library_stats()
        return LibraryStatsResult(
            total_files=stats.get("total_files", 0),
            total_artists=stats.get("total_artists", 0),
            total_albums=stats.get("total_albums", 0),
            total_duration=stats.get("total_duration"),
            total_size=stats.get("total_size"),
            needs_tagging_count=stats.get("needs_tagging_count", 0),
        )

    def get_all_library_paths(self) -> list[str]:
        """
        Get all file paths in the library.

        Returns:
            List of absolute file paths
        """
        return self.db.library_files.get_all_library_paths()

    def get_tagged_library_paths(self) -> list[str]:
        """
        Get all file paths that have been tagged (have tags in database).

        Returns:
            List of absolute file paths that have been tagged
        """
        return self.db.library_files.get_tagged_file_paths()

    def search_files(
        self,
        q: str = "",
        artist: str | None = None,
        album: str | None = None,
        tag_key: str | None = None,
        tag_value: str | None = None,
        tagged_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> SearchFilesResult:
        """Search library files with optional filters."""
        from nomarr.components.library.search_files_comp import search_library_files
        from nomarr.services.domain._library_mapping import map_file_with_tags_to_dto

        files, total = search_library_files(self.db, q, artist, album, tag_key, tag_value, tagged_only, limit, offset)
        files_with_tags = [map_file_with_tags_to_dto(f) for f in files]
        return SearchFilesResult(files=files_with_tags, total=total, limit=limit, offset=offset)

    def get_files_by_ids(self, file_ids: list[str]) -> SearchFilesResult:
        """Get files by IDs with their tags.

        Used for batch lookup (e.g., when browsing songs for an entity).

        Args:
            file_ids: List of file _ids to fetch

        Returns:
            SearchFilesResult with files matching the IDs
        """
        from nomarr.services.domain._library_mapping import map_file_with_tags_to_dto

        files = self.db.library_files.get_files_by_ids_with_tags(file_ids)
        files_with_tags = [map_file_with_tags_to_dto(f) for f in files]
        return SearchFilesResult(files=files_with_tags, total=len(files), limit=len(file_ids), offset=0)

    def get_unique_tag_keys(self, nomarr_only: bool = False) -> UniqueTagKeysResult:
        """Get all unique tag keys across the library."""
        from nomarr.components.library.search_files_comp import get_unique_tag_keys

        keys = get_unique_tag_keys(self.db, nomarr_only)
        return UniqueTagKeysResult(tag_keys=keys, count=len(keys), calibration=None, library_id=None)

    def get_unique_tag_values(self, tag_key: str, nomarr_only: bool = False) -> UniqueTagKeysResult:
        """Get all unique values for a specific tag key."""
        from nomarr.components.library.search_files_comp import get_unique_tag_values

        values = get_unique_tag_values(self.db, tag_key, nomarr_only)
        return UniqueTagKeysResult(tag_keys=values, count=len(values), calibration=None, library_id=None)
