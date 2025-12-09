"""
Library API response types.

External API contracts for library endpoints.
These are Pydantic models that transform internal DTOs into API responses.

Architecture:
- These types are owned by the interface layer
- They define what external clients see (REST API shapes)
- They transform internal DTOs via .from_dto() classmethods
- Services and lower layers should NOT import from this module
"""

from __future__ import annotations

from pydantic import BaseModel
from typing_extensions import Self

from nomarr.helpers.dto.library_dto import (
    LibraryDict,
    LibraryStatsResult,
    StartScanResult,
)

# ──────────────────────────────────────────────────────────────────────
# Library Response Types (DTO → Pydantic mappings)
# ──────────────────────────────────────────────────────────────────────


class LibraryResponse(BaseModel):
    """
    Single library response.

    Maps directly to LibraryDict DTO from helpers/dto/library_dto.py
    """

    id: int
    name: str
    root_path: str
    is_enabled: bool
    is_default: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_dto(cls, library: LibraryDict) -> Self:
        """
        Transform internal LibraryDict DTO to external API response.

        Args:
            library: Internal library DTO from service layer

        Returns:
            API response model
        """
        # Convert timestamps: if int (ms), convert to ISO format; if already string, pass through
        created_at = library.created_at
        updated_at = library.updated_at

        if isinstance(created_at, int):
            from datetime import datetime, timezone

            created_at = datetime.fromtimestamp(created_at / 1000, tz=timezone.utc).isoformat()

        if isinstance(updated_at, int):
            from datetime import datetime, timezone

            updated_at = datetime.fromtimestamp(updated_at / 1000, tz=timezone.utc).isoformat()

        return cls(
            id=library.id,
            name=library.name,
            root_path=library.root_path,
            is_enabled=library.is_enabled,
            is_default=library.is_default,
            created_at=created_at,
            updated_at=updated_at,
        )


class LibraryStatsResponse(BaseModel):
    """
    Response for library statistics endpoint.

    Maps to LibraryStatsResult DTO from helpers/dto/library_dto.py.
    Field names match frontend expectations.
    """

    total_files: int
    unique_artists: int
    unique_albums: int
    total_duration_seconds: float

    @classmethod
    def from_dto(cls, stats: LibraryStatsResult) -> Self:
        """
        Transform internal LibraryStatsResult DTO to external API response.

        Args:
            stats: Internal library stats from service layer

        Returns:
            API response model with frontend-compatible field names
        """
        return cls(
            total_files=stats.total_files,
            unique_artists=stats.total_artists,
            unique_albums=stats.total_albums,
            total_duration_seconds=stats.total_duration or 0.0,
        )


class StartScanResponse(BaseModel):
    """
    Response for start scan operation.

    Maps to StartScanResult DTO from helpers/dto/library_dto.py
    """

    files_discovered: int
    files_queued: int
    files_skipped: int
    files_removed: int
    job_ids: list[int]

    @classmethod
    def from_dto(cls, result: StartScanResult) -> Self:
        """
        Transform internal StartScanResult DTO to external API response.

        Args:
            result: Internal scan result from service layer

        Returns:
            API response model
        """
        return cls(
            files_discovered=result.files_discovered,
            files_queued=result.files_queued,
            files_skipped=result.files_skipped,
            files_removed=result.files_removed,
            job_ids=result.job_ids,
        )


class StartScanWithStatusResponse(BaseModel):
    """
    Response wrapper for start scan operation with status message.

    Used by library scan endpoint to provide contextual status information.
    """

    status: str
    message: str
    stats: StartScanResponse

    @classmethod
    def from_dto(cls, result: StartScanResult, library_id: int) -> Self:
        """
        Transform internal StartScanResult DTO to wrapped API response.

        Args:
            result: Internal scan result from service layer
            library_id: Library ID for message generation

        Returns:
            API response model with status wrapper
        """
        stats = StartScanResponse.from_dto(result)
        return cls(
            status="queued",
            message=f"Scan started for library {library_id}: {stats.files_queued} files queued",
            stats=stats,
        )


# ──────────────────────────────────────────────────────────────────────
# Library Request Types
# ──────────────────────────────────────────────────────────────────────


class CreateLibraryRequest(BaseModel):
    """Request body for creating a library."""

    name: str
    root_path: str
    is_enabled: bool = True
    is_default: bool = False


class UpdateLibraryRequest(BaseModel):
    """Request body for updating a library."""

    name: str | None = None
    root_path: str | None = None
    is_enabled: bool | None = None
    is_default: bool | None = None


class ScanLibraryRequest(BaseModel):
    """Request body for starting a library scan."""

    paths: list[str] | None = None
    recursive: bool = True
    force: bool = False
    clean_missing: bool = True


class ListLibrariesResponse(BaseModel):
    """Response wrapper for list of libraries."""

    libraries: list[LibraryResponse]

    @classmethod
    def from_dto(cls, libraries: list[LibraryDict]) -> ListLibrariesResponse:
        """Convert list of LibraryDict DTOs to response model."""
        return cls(libraries=[LibraryResponse.from_dto(lib) for lib in libraries])


# ──────────────────────────────────────────────────────────────────────
# File Search Response Types (DTO → Pydantic mappings)
# ──────────────────────────────────────────────────────────────────────


class FileTagResponse(BaseModel):
    """Single tag on a file."""

    key: str
    value: str
    type: str
    is_nomarr: bool


class LibraryFileWithTagsResponse(BaseModel):
    """Single library file with its tags."""

    id: int
    path: str
    library_id: int
    file_size: int | None
    modified_time: int | None
    duration_seconds: float | None
    artist: str | None
    album: str | None
    title: str | None
    calibration: str | None
    scanned_at: int | None
    last_tagged_at: int | None
    tagged: int
    tagged_version: str | None
    skip_auto_tag: int
    created_at: str | None
    updated_at: str | None
    tags: list[FileTagResponse]


class SearchFilesResponse(BaseModel):
    """Response for library file search."""

    files: list[LibraryFileWithTagsResponse]
    total: int
    limit: int
    offset: int

    @classmethod
    def from_dto(cls, result) -> SearchFilesResponse:
        """Transform SearchFilesResult DTO to API response."""
        from nomarr.helpers.dto.library_dto import SearchFilesResult

        assert isinstance(result, SearchFilesResult)

        return cls(
            files=[
                LibraryFileWithTagsResponse(
                    id=f.id,
                    path=f.path,
                    library_id=f.library_id,
                    file_size=f.file_size,
                    modified_time=f.modified_time,
                    duration_seconds=f.duration_seconds,
                    artist=f.artist,
                    album=f.album,
                    title=f.title,
                    calibration=f.calibration,
                    scanned_at=f.scanned_at,
                    last_tagged_at=f.last_tagged_at,
                    tagged=f.tagged,
                    tagged_version=f.tagged_version,
                    skip_auto_tag=f.skip_auto_tag,
                    created_at=f.created_at,
                    updated_at=f.updated_at,
                    tags=[
                        FileTagResponse(key=t.key, value=t.value, type=t.type, is_nomarr=t.is_nomarr) for t in f.tags
                    ],
                )
                for f in result.files
            ],
            total=result.total,
            limit=result.limit,
            offset=result.offset,
        )


class UniqueTagKeysResponse(BaseModel):
    """Response for unique tag keys endpoint."""

    tag_keys: list[str]
    count: int

    @classmethod
    def from_dto(cls, result) -> UniqueTagKeysResponse:
        """Transform UniqueTagKeysResult DTO to API response."""
        from nomarr.helpers.dto.library_dto import UniqueTagKeysResult

        assert isinstance(result, UniqueTagKeysResult)

        return cls(tag_keys=result.tag_keys, count=result.count)
