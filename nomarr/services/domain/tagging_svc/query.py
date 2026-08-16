"""Tag query and lookup operations for TaggingService."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from nomarr.components.library.library_records_comp import list_library_records
from nomarr.components.library.library_song_query_comp import count_songs_by_tag, search_songs_by_tag
from nomarr.components.library.library_song_state_comp import count_pending_tag_writes
from nomarr.components.library.search_files_comp import get_unique_tag_values
from nomarr.components.library.song_tags_comp import get_song_tags_with_path
from nomarr.components.tagging.tag_query_comp import (
    count_songs_for_tag,
    count_tags_by_name,
    get_tag_songs_with_metadata,
    get_unique_mood_values,
    list_tags_by_name,
)
from nomarr.components.tagging.tag_stats_comp import get_unique_names
from nomarr.helpers.dto.library_dto import (
    FileTag,
    FileTagsResult,
    SearchFilesResult,
    TagCleanupResult,
    UniqueTagKeysResult,
    map_song_with_tags_to_dto,
)
from nomarr.helpers.dto.tag_curation_dto import CommitResult, TagListResult, TagSongItem, TagValueItem
from nomarr.workflows.library.cleanup_orphaned_tags_wf import cleanup_orphaned_tags_workflow

if TYPE_CHECKING:
    from nomarr.helpers.dto.library_dto import WriteTagsResult
    from nomarr.persistence.db import Database


class _TaggingQueryService(Protocol):
    """Protocol describing the composed service surface used by query methods."""

    db: Database

    def write_tags_to_files(
        self,
        library_id: int,
        batch_size: int = 100,
        namespace: str = "nom",
    ) -> WriteTagsResult: ...


class TaggingQueryMixin:
    """Mixin providing tag query methods."""

    db: Database

    def list_tag_values(
        self,
        name: str | None = None,
        prefix: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> TagListResult:
        """List tag values with pagination, optionally filtered by name and prefix.

        Args:
            name: Tag name to filter by (e.g., "genre"). None = all names.
            prefix: Substring search on tag value.
            limit: Max results per page.
            offset: Pagination offset.

        Returns:
            TagListResult with tags list and total count.

        """
        raw_tags = list_tags_by_name(self.db, name=name, limit=limit, offset=offset, search=prefix)
        total = count_tags_by_name(self.db, name=name, search=prefix)

        tags: list[TagValueItem] = [
            TagValueItem(
                id=t["id"],
                name=t["name"],
                value=str(t["value"]),
                song_count=t.get("song_count", 0),
            )
            for t in raw_tags
        ]
        return TagListResult(tags=tags, total=total)

    def get_tag_songs(
        self,
        tag_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Get songs linked to a tag with metadata.

        Args:
            tag_id: Tag id
            limit: Max results
            offset: Pagination offset

        Returns:
            Dict with songs list and total count.

        """
        raw_songs = get_tag_songs_with_metadata(self.db, int(tag_id), limit=limit, offset=offset)
        total = count_songs_for_tag(self.db, int(tag_id))

        songs: list[TagSongItem] = [
            TagSongItem(
                file_id=s["file_id"],
                title=s.get("title", ""),
                artist=s.get("artist", ""),
                album=s.get("album", ""),
                path=s.get("path", ""),
            )
            for s in raw_songs
        ]
        return {"songs": songs, "total": total}

    def get_pending_commit_count(self) -> int:
        """Count files with pending tag writes (tags_not_written state).

        Returns:
            Number of files that have been tagged in the database but
            have not yet had their tags written to the audio file.

        """
        return count_pending_tag_writes(self.db)

    def commit_pending_tags(self: _TaggingQueryService, library_id: str | None = None) -> CommitResult:
        """Commit pending tag writes by writing tags for affected libraries.

        Args:
            library_id: Optional library id to scope. If None, finds libraries
                        with pending files.

        Returns:
            CommitResult with started flag and pending file count.

        """
        pending = count_pending_tag_writes(self.db)
        if pending == 0:
            return CommitResult(started=False, pending_files=0)

        if library_id:
            self.write_tags_to_files(int(library_id))
        else:
            libraries = list_library_records(self.db, include_scan=False)
            for lib in libraries:
                self.write_tags_to_files(lib.id)

        return CommitResult(started=True, pending_files=pending)

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

    def get_song_tags(self, song_id: int, nomarr_only: bool = False) -> FileTagsResult:
        """Return the tags currently stored for a single song.

        Args:
            song_id: The song identifier.
            nomarr_only: Whether to only include ``nom:`` namespace tags.

        Returns:
            A :class:`FileTagsResult` containing the song's stored tags.

        Raises:
            ValueError: If the song does not exist.
        """
        result = get_song_tags_with_path(self.db, int(song_id), nomarr_only=nomarr_only)
        if not result:
            raise ValueError(f"Song with ID {song_id} not found")
        tags = [
            FileTag(
                key=tag["key"],
                value=str(tag["value"]),
                tag_type=tag["type"],
                is_nomarr=tag["is_nomarr_tag"],
            )
            for tag in result["tags"]
        ]
        return FileTagsResult(file_id=int(song_id), path=result["path"], tags=tags)

    def cleanup_orphaned_tags(self, dry_run: bool = False) -> TagCleanupResult:
        """Clean up orphaned tags from the database.

        Args:
            dry_run: If True, count orphaned tags but don't delete them

        Returns:
            TagCleanupResult DTO with orphaned_count and deleted_count

        """
        result = cleanup_orphaned_tags_workflow(self.db, dry_run=dry_run)
        return TagCleanupResult(
            orphaned_count=result["orphaned_count"],
            deleted_count=result["deleted_count"],
        )

    def search_songs_by_tag(
        self,
        tag_key: str,
        target_value: float | str,
        limit: int = 100,
        offset: int = 0,
    ) -> SearchFilesResult:
        """Search files by tag value with distance sorting (float) or exact match (string).

        Args:
            tag_key: Tag key to search (e.g., "nom:bpm", "genre")
            target_value: Target value (float for distance sort, string for exact match)
            limit: Maximum number of results
            offset: Pagination offset

        Returns:
            SearchFilesResult with matched files

        """
        files = search_songs_by_tag(self.db, tag_key, target_value, limit, offset)
        total = count_songs_by_tag(self.db, tag_key, target_value)
        files_with_tags = [map_song_with_tags_to_dto(f) for f in files]
        return SearchFilesResult(songs=files_with_tags, total=total, limit=limit, offset=offset)
