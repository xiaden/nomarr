"""Library API response types.

External API contracts for library endpoints.
These are Pydantic models that transform internal DTOs into API responses.

Architecture:
- These types are owned by the interface layer
- They define what external clients see (REST API shapes)
- They transform internal DTOs via .from_dto() classmethods
- Services and lower layers should NOT import from this module
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel

from nomarr.helpers.dto import LibraryPipelineStatusDTO
from nomarr.helpers.dto.library_dto import (
    FileTagsResult,
    LibraryScanStatusResult,
    SearchFilesResult,
    TagCleanupResult,
    UniqueTagKeysResult,
    WriteTagsResult,
)
from nomarr.interfaces.api.id_codec import encode_id

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dto.library_dto import LibraryStatsResult, ReconcileResult, StartScanResult


def _to_iso(value: int | str | None) -> str | None:
    """Convert an integer millisecond timestamp (or ISO string) to ISO 8601."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat()


# ──────────────────────────────────────────────────────────────────────
# Library Response Types (DTO → Pydantic mappings)
# ──────────────────────────────────────────────────────────────────────


class LibraryResponse(BaseModel):
    """Single library response.

    Mechanism A (TASK-library-domain-facades-A): the wire identity is the
    URL-encoded natural ``Library.name`` (``library_id`` is a string natural-name
    token, never a generated primary key). Built from a domain ``Library`` plus
    optional per-library scan status and file/folder counts supplied by the
    interface adapter.
    """

    library_id: str  # natural library name (mechanism A)
    name: str
    root_path: str
    is_enabled: bool
    watch_mode: str  # 'off', 'event', or 'poll'
    file_write_mode: str = "full"  # 'none', 'minimal', or 'full'
    library_auto_write: bool = False
    created_at: str
    updated_at: str
    scan_status: str | None = None
    scan_progress: int | None = None
    scan_total: int | None = None
    scanned_at: str | None = None
    scan_error: str | None = None
    # Statistics
    file_count: int = 0
    folder_count: int = 0

    @classmethod
    def from_dto(
        cls,
        library: Library,
        *,
        scan: LibraryScanStatusResult | None = None,
        file_count: int = 0,
        folder_count: int = 0,
    ) -> Self:
        """Transform a domain ``Library`` to the external API response.

        Args:
            library: Domain ``Library`` value from the service layer.
            scan: Optional per-library scan status for projection.
            file_count: Per-library file count from the name-keyed counts map.
            folder_count: Per-library folder count from the name-keyed counts map.

        Returns:
            API response model with natural-name identity.

        """
        return cls(
            library_id=library.name,
            name=library.name,
            root_path=library.root_path,
            is_enabled=library.is_enabled,
            watch_mode=library.watch_mode,
            file_write_mode=library.file_write_mode,
            library_auto_write=library.library_auto_write,
            created_at=_to_iso(library.created_at) or "",
            updated_at=_to_iso(library.updated_at) or "",
            scan_status=scan.scan_status if scan is not None else None,
            scan_progress=scan.scan_progress if scan is not None else None,
            scan_total=scan.scan_total if scan is not None else None,
            scanned_at=_to_iso(scan.scanned_at) if scan is not None else None,
            scan_error=scan.scan_error if scan is not None else None,
            file_count=file_count,
            folder_count=folder_count,
        )


class LibraryStatsResponse(BaseModel):
    """Response for library statistics endpoint.

    Maps to LibraryStatsResult DTO from helpers/dto/library_dto.py.
    Field names match frontend expectations.
    """

    total_files: int
    unique_artists: int
    unique_albums: int
    total_duration_seconds: float

    @classmethod
    def from_dto(cls, stats: LibraryStatsResult) -> Self:
        """Transform internal LibraryStatsResult DTO to external API response.

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
    """Response for start scan operation.

    Maps to StartScanResult DTO from helpers/dto/library_dto.py
    """

    files_discovered: int
    files_queued: int
    files_skipped: int
    files_removed: int
    job_ids: list[str]

    @classmethod
    def from_dto(cls, result: StartScanResult) -> Self:
        """Transform internal StartScanResult DTO to external API response.

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
    """Response wrapper for start scan operation with status message.

    Used by library scan endpoint to provide contextual status information.
    """

    status: str
    message: str
    stats: StartScanResponse

    @classmethod
    def from_dto(cls, result: StartScanResult, library_name: str) -> Self:
        """Transform internal StartScanResult DTO to wrapped API response.

        Args:
            result: Internal scan result from service layer
            library_name: Natural library name for the message

        Returns:
            API response model with status wrapper

        """
        stats = StartScanResponse.from_dto(result)
        return cls(
            status="started",
            message=f"Scan started for library {library_name}: {stats.files_queued} files discovered",
            stats=stats,
        )


# ──────────────────────────────────────────────────────────────────────
# Library Request Types
# ──────────────────────────────────────────────────────────────────────


class CreateLibraryRequest(BaseModel):
    """Request body for creating a library."""

    name: str | None = None  # Optional: auto-generated from path if not provided
    root_path: str
    is_enabled: bool = True
    watch_mode: str = "off"  # 'off', 'event', or 'poll' (default: 'off')
    file_write_mode: str = "full"  # 'none', 'minimal', or 'full' (default: 'full')
    library_auto_write: bool = False


class UpdateLibraryRequest(BaseModel):
    """Request body for updating a library."""

    name: str | None = None
    root_path: str | None = None
    is_enabled: bool | None = None
    watch_mode: str | None = None  # 'off', 'event', or 'poll'
    file_write_mode: str | None = None  # 'none', 'minimal', or 'full'
    library_auto_write: bool | None = None


class ListLibrariesResponse(BaseModel):
    """Response wrapper for list of libraries."""

    libraries: list[LibraryResponse]

    @classmethod
    def from_dto(
        cls,
        libraries: list[Library],
        *,
        counts: dict[str, dict[str, int]] | None = None,
        scans: dict[str, LibraryScanStatusResult] | None = None,
    ) -> ListLibrariesResponse:
        """Convert a list of domain ``Library`` values to the response model.

        The interface adapter supplies the name-keyed file/folder ``counts`` and
        per-library ``scans`` for the transport projection (P4-S8).

        Args:
            libraries: Domain ``Library`` values.
            counts: ``{name: {"file_count": int, "folder_count": int}}``.
            scans: ``{name: LibraryScanStatusResult}``.

        Returns:
            Response model with natural-name wire identity.

        """
        counts = counts or {}
        scans = scans or {}
        return cls(
            libraries=[
                LibraryResponse.from_dto(
                    lib,
                    scan=scans.get(lib.name),
                    file_count=counts.get(lib.name, {}).get("file_count", 0),
                    folder_count=counts.get(lib.name, {}).get("folder_count", 0),
                )
                for lib in libraries
            ]
        )


# ──────────────────────────────────────────────────────────────────────
# File Search Response Types (DTO → Pydantic mappings)
# ──────────────────────────────────────────────────────────────────────


class FileTagResponse(BaseModel):
    """Single tag on a file."""

    key: str
    value: str
    tag_type: str
    is_nomarr: bool


class LibraryFileWithTagsResponse(BaseModel):
    """Single library file with its tags."""

    file_id: int  # Primary key
    path: str
    library_id: int | None  # Primary key (None for orphaned files)
    file_size: int | None
    modified_time: int | None
    duration_seconds: float | None
    artist: str | None
    album: str | None
    title: str | None
    calibration_version: str | None = None
    scanned_at: int | None
    last_tagged_at: int | None
    tagged: bool
    tagged_version: str | None
    skip_auto_tag: bool
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
        assert isinstance(result, SearchFilesResult)

        return cls(
            files=[
                LibraryFileWithTagsResponse(
                    file_id=encode_id(f.id),
                    path=f.path,
                    library_id=encode_id(f.library_id) if f.library_id else None,
                    file_size=f.file_size,
                    modified_time=f.modified_time,
                    duration_seconds=f.duration_seconds,
                    artist=f.artist,
                    album=f.album,
                    title=f.title,
                    calibration_version=f.calibration_version,
                    scanned_at=f.scanned_at,
                    last_tagged_at=f.last_tagged_at,
                    tagged=f.tagged,
                    tagged_version=f.tagged_version,
                    skip_auto_tag=f.skip_auto_tag,
                    created_at=f.created_at,
                    updated_at=f.updated_at,
                    tags=[
                        FileTagResponse(key=t.key, value=str(t.value), tag_type=t.tag_type, is_nomarr=t.is_nomarr)
                        for t in f.tags
                    ],
                )
                for f in result.songs
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
        assert isinstance(result, UniqueTagKeysResult)

        return cls(tag_keys=result.tag_keys, count=result.count)


class TagCleanupResponse(BaseModel):
    """Response for tag cleanup endpoint."""

    orphaned_count: int
    deleted_count: int

    @classmethod
    def from_dto(cls, result) -> TagCleanupResponse:
        """Transform TagCleanupResult DTO to API response."""
        assert isinstance(result, TagCleanupResult)

        return cls(orphaned_count=result.orphaned_count, deleted_count=result.deleted_count)


class ReconcilePathsResponse(BaseModel):
    """Response for library path reconciliation endpoint."""

    total_files: int
    valid_files: int
    invalid_config: int
    not_found: int
    unknown_status: int
    deleted_files: int
    errors: int

    @classmethod
    def from_dict(cls, result: ReconcileResult) -> ReconcilePathsResponse:
        """Transform ReconcileResult DTO to API response."""
        return cls(
            total_files=result["total_files"],
            valid_files=result["valid_files"],
            invalid_config=result["invalid_config"],
            not_found=result["not_found"],
            unknown_status=result["unknown_status"],
            deleted_files=result["deleted_files"],
            errors=result["errors"],
        )


class FileTagsResponse(BaseModel):
    """Response for file tags endpoint."""

    file_id: int
    path: str
    tags: list[FileTagResponse]

    @classmethod
    def from_dto(cls, result) -> FileTagsResponse:
        """Transform FileTagsResult DTO to API response."""
        assert isinstance(result, FileTagsResult)

        return cls(
            file_id=result.file_id,
            path=result.path,
            tags=[
                FileTagResponse(key=t.key, value=str(t.value), tag_type=t.tag_type, is_nomarr=t.is_nomarr)
                for t in result.tags
            ],
        )


# ──────────────────────────────────────────────────────────────────────
# Tag Writing Reconciliation Types
# ──────────────────────────────────────────────────────────────────────


class WriteTagsResponse(BaseModel):
    """Response for completed tag write operation."""

    processed: int  # Files successfully written
    remaining: int  # Files still pending tag write
    failed: int  # Files that failed during this batch

    @classmethod
    def from_dto(cls, result) -> WriteTagsResponse:
        """Transform WriteTagsResult DTO to API response."""
        assert isinstance(result, WriteTagsResult)
        return cls(processed=result.processed, remaining=result.remaining, failed=result.failed)


class PipelineStatusResponse(BaseModel):
    """Response for the per-library pipeline status endpoint.

    ``library_id`` is the natural library name (mechanism A).
    """

    library_id: str
    scan_state: str
    ml_state: str
    calibration_state: str
    tag_write_state: str
    untagged_count: int | None
    uncalibrated_count: int | None
    pending_write_count: int | None
    library_auto_write: bool
    file_write_mode: str

    @classmethod
    def from_dto(cls, dto: LibraryPipelineStatusDTO) -> Self:
        """Transform LibraryPipelineStatusDTO to API response."""
        assert isinstance(dto, LibraryPipelineStatusDTO)
        return cls(
            library_id=dto.library_id,
            scan_state=dto.scan_state,
            ml_state=dto.ml_state,
            calibration_state=dto.calibration_state,
            tag_write_state=dto.tag_write_state,
            untagged_count=dto.untagged_count,
            uncalibrated_count=dto.uncalibrated_count,
            pending_write_count=dto.pending_write_count,
            library_auto_write=dto.library_auto_write,
            file_write_mode=dto.file_write_mode,
        )


class StartTagWriteResponse(BaseModel):
    """Response for starting a background tag write task."""

    status: str
    task_id: str


class UpdateWriteModeResponse(BaseModel):
    """Response for write mode update endpoint."""

    file_write_mode: str
    requires_reconciliation: bool
    affected_file_count: int


class ValidateLibraryTagsResponse(BaseModel):
    """Response for library tag validation endpoint."""

    files_checked: int
    complete_files: int
    incomplete_files: int
    files_repaired: int
    expected_heads: int
    missing_names_summary: dict[str, int]


class ErroredFileItemResponse(BaseModel):
    """Single errored file in the response."""

    file_id: int
    path: str
    duration_seconds: float | None
    artist: str | None
    title: str | None


class ErroredFilesResponse(BaseModel):
    """Response for errored files listing endpoint."""

    files: list[ErroredFileItemResponse]
    total: int


class RetryErroredRequest(BaseModel):
    """Request body for retrying errored files."""

    file_ids: list[str] | None = None


class RetryErroredResponse(BaseModel):
    """Response for retry errored files endpoint."""

    retried: int
