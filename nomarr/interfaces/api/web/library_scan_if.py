"""Library scan, pipeline, and write endpoints for the web UI."""

import asyncio
import logging
import threading
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from nomarr.helpers.exceptions import LibraryAlreadyScanningError, LibraryNotFoundError
from nomarr.helpers.logging_helper import sanitize_exception_message
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.id_codec import decode_path_id
from nomarr.interfaces.api.types.library_types import (
    PipelineStatusResponse,
    ReconcilePathsResponse,
    StartScanWithStatusResponse,
    StartTagWriteResponse,
    UpdateWriteModeResponse,
    ValidateLibraryTagsResponse,
)
from nomarr.interfaces.api.web.dependencies import (
    get_library_service,
    get_navidrome_service,
    get_pipeline_service,
    get_tagging_service,
)
from nomarr.services.infrastructure.pipeline_svc import LibraryPipelineService

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.services.domain.library_svc import LibraryService
    from nomarr.services.domain.navidrome_svc import NavidromeService
    from nomarr.services.domain.tagging_svc import TaggingService

router = APIRouter(prefix="/library", tags=["Library"])


@router.post("/{library_id}/scan/quick", dependencies=[Depends(verify_session)])
async def scan_library_quick(
    library_id: str,
    library_service: "LibraryService" = Depends(get_library_service),
) -> StartScanWithStatusResponse:
    """Start a quick scan for a specific library."""
    library_id = decode_path_id(library_id)
    try:
        stats = library_service.start_quick_scan(library_id=library_id)
        return StartScanWithStatusResponse.from_dto(stats, library_id)
    except LibraryNotFoundError:
        raise HTTPException(status_code=404, detail="Library not found") from None
    except LibraryAlreadyScanningError:
        raise HTTPException(status_code=409, detail="Library is already being scanned") from None
    except Exception as e:
        logger.exception(f"[Web API] Error starting quick scan for library {library_id}")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to start library scan"),
        ) from e


@router.post("/{library_id}/scan/full", dependencies=[Depends(verify_session)])
async def scan_library_full(
    library_id: str,
    library_service: "LibraryService" = Depends(get_library_service),
) -> StartScanWithStatusResponse:
    """Start a full scan for a specific library."""
    library_id = decode_path_id(library_id)
    try:
        stats = library_service.start_full_scan(library_id=library_id)
        return StartScanWithStatusResponse.from_dto(stats, library_id)
    except LibraryNotFoundError:
        raise HTTPException(status_code=404, detail="Library not found") from None
    except LibraryAlreadyScanningError:
        raise HTTPException(status_code=409, detail="Library is already being scanned") from None
    except Exception as e:
        logger.exception(f"[Web API] Error starting full scan for library {library_id}")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to start library scan"),
        ) from e


@router.post("/{library_id}/reconcile", dependencies=[Depends(verify_session)])
async def reconcile_library_paths(
    library_id: str,
    policy: Annotated[
        str,
        Query(description="Policy for invalid paths: dry_run, mark_invalid, delete_invalid"),
    ] = "mark_invalid",
    batch_size: Annotated[int, Query(description="Number of files to process per batch", ge=1, le=10000)] = 1000,
    library_service: "LibraryService" = Depends(get_library_service),
) -> ReconcilePathsResponse:
    """Reconcile library paths after configuration changes."""
    library_id = decode_path_id(library_id)
    try:
        stats = await asyncio.to_thread(
            library_service.reconcile_library_paths,
            library_id,
            policy=policy,
            batch_size=batch_size,
        )
        return ReconcilePathsResponse.from_dict(stats)
    except ValueError as e:
        error_message = str(e).lower()
        if "policy" in error_message:
            raise HTTPException(status_code=400, detail="Invalid reconciliation policy") from None
        raise HTTPException(status_code=404, detail="Library not found") from None
    except Exception as e:
        logger.exception(f"[Web API] Error reconciling paths for library {library_id}")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to reconcile library paths"),
        ) from e


@router.post("/{library_id}/write-tag", dependencies=[Depends(verify_session)], status_code=202)
async def write_library_tags(
    library_id: str,
    tagging_service: "TaggingService" = Depends(get_tagging_service),
    navidrome_service: "NavidromeService" = Depends(get_navidrome_service),
) -> StartTagWriteResponse:
    """Write pending file tags for a library."""
    library_id = decode_path_id(library_id)
    try:
        stop_event = threading.Event()

        def trigger_navidrome_rescan() -> None:
            navidrome_service.trigger_rescan()

        task_id = tagging_service.start_write_tags_background(
            library_id,
            stop_event=stop_event,
            on_complete=trigger_navidrome_rescan,
        )
        return StartTagWriteResponse(status="started", task_id=task_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Library not found") from None
    except Exception as e:
        logger.exception(f"[Web API] Error writing tags for library {library_id}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to write tags")) from e


@router.get("/{library_id}/pipeline", dependencies=[Depends(verify_session)])
async def get_library_pipeline_status(
    library_id: str,
    pipeline_service: Annotated[LibraryPipelineService, Depends(get_pipeline_service)],
) -> PipelineStatusResponse:
    """Get the current pipeline status for a single library."""
    library_id = decode_path_id(library_id)
    try:
        status = pipeline_service.get_pipeline_status(library_id)
        if status is None:
            raise HTTPException(status_code=404, detail="Library not found")
        return PipelineStatusResponse.from_dto(status)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[Web API] Error getting pipeline status for library {library_id}")
        raise HTTPException(
            status_code=500,
            detail=sanitize_exception_message(e, "Failed to get pipeline status"),
        ) from e


@router.patch("/{library_id}/write-mode", dependencies=[Depends(verify_session)])
async def update_write_mode(
    library_id: str,
    file_write_mode: Annotated[str, Query(description="New write mode: 'none', 'minimal', or 'full'")],
    library_service: Annotated["LibraryService", Depends(get_library_service)],
    tagging_service: Annotated["TaggingService", Depends(get_tagging_service)],
) -> UpdateWriteModeResponse:
    """Update the file write mode for a library."""
    library_id = decode_path_id(library_id)
    if file_write_mode not in ("none", "minimal", "full"):
        raise HTTPException(status_code=400, detail="file_write_mode must be 'none', 'minimal', or 'full'")
    try:
        library_service.update_library(library_id, file_write_mode=file_write_mode)
        tagging_service.mark_tags_stale(library_id)
        status = tagging_service.get_reconcile_status(library_id=library_id)
        return UpdateWriteModeResponse(
            file_write_mode=file_write_mode,
            requires_reconciliation=status["pending_count"] > 0,
            affected_file_count=status["pending_count"],
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Library not found") from None
    except Exception as e:
        logger.exception(f"[Web API] Error updating write mode for library {library_id}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to update write mode")) from e


@router.post("/{library_id}/validate-tag", dependencies=[Depends(verify_session)])
async def validate_library_tags(
    library_id: str,
    auto_repair: Annotated[bool, Query(description="Auto-repair incomplete files by marking for re-tagging")] = True,
    library_service: "LibraryService" = Depends(get_library_service),
) -> ValidateLibraryTagsResponse:
    """Validate tag completeness for a library's files."""
    library_id = decode_path_id(library_id)
    try:
        result = library_service.validate_library_tags(library_id=library_id, auto_repair=auto_repair)
        return ValidateLibraryTagsResponse(
            files_checked=result["files_checked"],
            complete_files=result["complete_files"],
            incomplete_files=result["incomplete_files"],
            files_repaired=result["files_repaired"],
            expected_heads=result["expected_heads"],
            missing_rels_summary=result.get("missing_rels_summary", {}),
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Library not found") from None
    except Exception as e:
        logger.exception(f"[Web API] Error validating tags for library {library_id}")
        raise HTTPException(status_code=500, detail=sanitize_exception_message(e, "Failed to validate tags")) from e
