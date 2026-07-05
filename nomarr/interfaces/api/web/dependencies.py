"""FastAPI dependency injection helpers for web endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from fastapi import HTTPException

if TYPE_CHECKING:
    from nomarr.services.domain.analytics_svc import AnalyticsService
    from nomarr.services.domain.calibration_svc import CalibrationService
    from nomarr.services.domain.library_svc import LibraryService
    from nomarr.services.domain.metadata_svc import MetadataService
    from nomarr.services.domain.navidrome_svc import NavidromeService
    from nomarr.services.domain.playlist_import_svc import PlaylistImportService
    from nomarr.services.domain.tagging_svc import TaggingService
    from nomarr.services.domain.vector_maintenance_svc import VectorMaintenanceService
    from nomarr.services.domain.vector_search_svc import VectorSearchService
    from nomarr.services.infrastructure.config_svc import ConfigService
    from nomarr.services.infrastructure.file_watcher_svc import FileWatcherService
    from nomarr.services.infrastructure.info_svc import InfoService
    from nomarr.services.infrastructure.ml_svc import MLService
    from nomarr.services.infrastructure.pipeline_svc import LibraryPipelineService
    from nomarr.services.infrastructure.worker_system_svc import WorkerSystemService


def get_config() -> dict[str, Any]:
    """Get configuration dict from ConfigService."""
    from nomarr.app import application

    config_service = application.get_service("config")
    result = config_service.get_config()
    return cast("dict[str, Any]", result.config)


def get_workers_coordinator() -> WorkerSystemService:
    """Get WorkerSystemService instance."""
    from nomarr.app import application

    service = application.services.get("workers")
    if not service:
        raise HTTPException(status_code=503, detail="Worker system not available")
    return cast("WorkerSystemService", service)


def get_library_service() -> LibraryService:
    """Get LibraryService instance."""
    from nomarr.app import application

    service = application.services.get("library")
    if not service:
        raise HTTPException(status_code=503, detail="Library service not available")
    service.file_watcher_service = get_file_watcher_service()
    return cast("LibraryService", service)


def get_analytics_service() -> AnalyticsService:
    """Get AnalyticsService instance."""
    from nomarr.app import application

    service = application.services.get("analytics")
    if not service:
        raise HTTPException(status_code=503, detail="Analytics service not available")
    return cast("AnalyticsService", service)


def get_calibration_service() -> CalibrationService:
    """Get CalibrationService instance."""
    from nomarr.app import application

    service = application.services.get("calibration")
    if not service:
        raise HTTPException(status_code=503, detail="Calibration service not available")
    return cast("CalibrationService", service)


def get_config_service() -> ConfigService:
    """Get ConfigService instance."""
    from nomarr.app import application

    service = application.services.get("config")
    if not service:
        raise HTTPException(status_code=503, detail="Config service not available")
    return cast("ConfigService", service)


def get_navidrome_service() -> NavidromeService:
    """Get NavidromeService instance."""
    from nomarr.app import application

    service = application.services.get("navidrome")
    if not service:
        raise HTTPException(status_code=503, detail="Navidrome service not available")
    return cast("NavidromeService", service)


def get_ml_service() -> MLService:
    """Get ML service instance."""
    from nomarr.app import application

    service = application.services.get("ml")
    if not service:
        raise HTTPException(status_code=503, detail="ML service not available")
    return cast("MLService", service)


def get_tagging_service() -> TaggingService:
    """Get TaggingService instance."""
    from nomarr.app import application

    service = application.services.get("tagging")
    if not service:
        raise HTTPException(status_code=503, detail="Tagging service not available")
    return cast("TaggingService", service)


def get_pipeline_service() -> LibraryPipelineService:
    """Get LibraryPipelineService instance."""
    from nomarr.app import application

    service = application.services.get("pipeline")
    if not service:
        raise HTTPException(status_code=503, detail="Pipeline service not available")
    return cast("LibraryPipelineService", service)


def get_info_service() -> InfoService:
    """Get info service instance."""
    from nomarr.app import application

    service = application.services.get("info")
    if not service:
        raise HTTPException(status_code=503, detail="Info service not available")
    return cast("InfoService", service)


def get_metadata_service() -> MetadataService:
    """Get MetadataService instance."""
    from nomarr.app import application

    service = application.services.get("metadata")
    if not service:
        raise HTTPException(status_code=503, detail="Metadata service not available")
    return cast("MetadataService", service)


def get_file_watcher_service() -> FileWatcherService | None:
    """Get FileWatcherService instance (optional - may not be running)."""
    from nomarr.app import application

    return cast("FileWatcherService | None", application.services.get("file_watcher"))


def get_playlist_import_service() -> PlaylistImportService:
    """Get PlaylistImportService instance."""
    from nomarr.app import application

    service = application.services.get("playlist_import")
    if not service:
        raise HTTPException(status_code=503, detail="Playlist import service not available")
    return cast("PlaylistImportService", service)


def get_vector_search_service() -> VectorSearchService:
    """Get VectorSearchService instance."""
    from nomarr.app import application

    service = application.services.get("vector_search")
    if not service:
        raise HTTPException(status_code=503, detail="Vector search service not available")
    return cast("VectorSearchService", service)


def get_vector_maintenance_service() -> VectorMaintenanceService:
    """Get VectorMaintenanceService instance."""
    from nomarr.app import application

    service = application.services.get("vector_maintenance")
    if not service:
        raise HTTPException(status_code=503, detail="Vector maintenance service not available")
    return cast("VectorMaintenanceService", service)
