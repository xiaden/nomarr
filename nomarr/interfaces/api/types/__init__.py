"""
API response types package.

External API contracts organized by domain.
Each module defines Pydantic models with .from_dto() transformation methods.
"""

from nomarr.interfaces.api.types.library_types import (
    CreateLibraryRequest,
    LibraryResponse,
    LibraryStatsResponse,
    ScanLibraryRequest,
    StartScanResponse,
    StartScanWithStatusResponse,
    UpdateLibraryRequest,
)
from nomarr.interfaces.api.types.navidrome_types import (
    GeneratePlaylistResponse,
    GenerateTemplateFilesRequest,
    GenerateTemplateFilesResponse,
    GetTemplateSummaryResponse,
    PlaylistGenerateRequest,
    PlaylistPreviewRequest,
    PlaylistPreviewResponse,
    PreviewTagStatsResponse,
    SmartPlaylistFilterResponse,
    TagConditionResponse,
    TemplateSummaryItemResponse,
)
from nomarr.interfaces.api.types.processing_types import (
    BatchProcessRequest,
    ProcessFileRequest,
    ProcessFileResponse,
)
from nomarr.interfaces.api.types.queue_types import (
    FlushRequest,
    FlushResponse,
    JobRemovalResult,
    ListJobsResponse,
    OperationResult,
    QueueJobResponse,
    QueueStatusResponse,
    RemoveJobRequest,
)

__all__ = [
    "BatchProcessRequest",
    "CreateLibraryRequest",
    "FlushRequest",
    "FlushResponse",
    "GeneratePlaylistResponse",
    "GenerateTemplateFilesRequest",
    "GenerateTemplateFilesResponse",
    "GetTemplateSummaryResponse",
    "JobRemovalResult",
    "LibraryResponse",
    "LibraryStatsResponse",
    "ListJobsResponse",
    "OperationResult",
    "PlaylistGenerateRequest",
    "PlaylistPreviewRequest",
    "PlaylistPreviewResponse",
    "PreviewTagStatsResponse",
    "ProcessFileRequest",
    "ProcessFileResponse",
    "QueueJobResponse",
    "QueueStatusResponse",
    "RemoveJobRequest",
    "ScanLibraryRequest",
    "SmartPlaylistFilterResponse",
    "StartScanResponse",
    "StartScanWithStatusResponse",
    "TagConditionResponse",
    "TemplateSummaryItemResponse",
    "UpdateLibraryRequest",
]
