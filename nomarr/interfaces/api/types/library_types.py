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
        return cls(
            id=library.id,
            name=library.name,
            root_path=library.root_path,
            is_enabled=library.is_enabled,
            is_default=library.is_default,
            created_at=library.created_at,
            updated_at=library.updated_at,
        )


class LibraryStatsResponse(BaseModel):
    """
    Response for library statistics endpoint.

    Maps to LibraryStatsResult DTO from helpers/dto/library_dto.py
    """

    total_files: int
    total_artists: int
    total_albums: int
    total_duration: float | None
    total_size: int | None

    @classmethod
    def from_dto(cls, stats: LibraryStatsResult) -> Self:
        """
        Transform internal LibraryStatsResult DTO to external API response.

        Args:
            stats: Internal library stats from service layer

        Returns:
            API response model
        """
        return cls(
            total_files=stats.total_files,
            total_artists=stats.total_artists,
            total_albums=stats.total_albums,
            total_duration=stats.total_duration,
            total_size=stats.total_size,
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
