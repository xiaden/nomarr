"""
Services package.
"""

from .analytics_service import AnalyticsConfig, AnalyticsService
from .calibration_download_service import check_missing_calibrations, download_calibrations, ensure_calibrations_exist
from .calibration_service import CalibrationConfig, CalibrationService
from .config_service import (
    INTERNAL_ALLOW_SHORT,
    INTERNAL_BATCH_SIZE,
    INTERNAL_CALIBRATION_APD_THRESHOLD,
    INTERNAL_CALIBRATION_AUTO_RUN,
    INTERNAL_CALIBRATION_CHECK_INTERVAL,
    INTERNAL_CALIBRATION_IQR_THRESHOLD,
    INTERNAL_CALIBRATION_JSD_THRESHOLD,
    INTERNAL_CALIBRATION_MEDIAN_THRESHOLD,
    INTERNAL_CALIBRATION_MIN_FILES,
    INTERNAL_CALIBRATION_QUALITY_THRESHOLD,
    INTERNAL_CALIBRATION_SRD_THRESHOLD,
    INTERNAL_HOST,
    INTERNAL_LIBRARY_SCAN_POLL_INTERVAL,
    INTERNAL_MIN_DURATION_S,
    INTERNAL_NAMESPACE,
    INTERNAL_POLL_INTERVAL,
    INTERNAL_PORT,
    INTERNAL_VERSION_TAG,
    INTERNAL_WORKER_ENABLED,
    ConfigService,
)
from .coordinator_service import CoordinatorConfig, CoordinatorService, process_file_wrapper
from .health_monitor_service import HealthMonitorConfig, HealthMonitorService
from .keys_service import SESSION_TIMEOUT_SECONDS, KeyManagementService
from .library_service import LibraryRootConfig, LibraryService
from .ml_service import MLConfig, MLService
from .navidrome_service import NavidromeConfig, NavidromeService
from .processing_service import ProcessingService
from .queue_service import BaseQueue, Job, ProcessingQueue, QueueService, RecalibrationQueue, ScanQueue
from .recalibration_service import RecalibrationService
from .worker_service import WorkerConfig, WorkerService

__all__ = [
    "INTERNAL_ALLOW_SHORT",
    "INTERNAL_BATCH_SIZE",
    "INTERNAL_CALIBRATION_APD_THRESHOLD",
    "INTERNAL_CALIBRATION_AUTO_RUN",
    "INTERNAL_CALIBRATION_CHECK_INTERVAL",
    "INTERNAL_CALIBRATION_IQR_THRESHOLD",
    "INTERNAL_CALIBRATION_JSD_THRESHOLD",
    "INTERNAL_CALIBRATION_MEDIAN_THRESHOLD",
    "INTERNAL_CALIBRATION_MIN_FILES",
    "INTERNAL_CALIBRATION_QUALITY_THRESHOLD",
    "INTERNAL_CALIBRATION_SRD_THRESHOLD",
    "INTERNAL_HOST",
    "INTERNAL_LIBRARY_SCAN_POLL_INTERVAL",
    "INTERNAL_MIN_DURATION_S",
    "INTERNAL_NAMESPACE",
    "INTERNAL_POLL_INTERVAL",
    "INTERNAL_PORT",
    "INTERNAL_VERSION_TAG",
    "INTERNAL_WORKER_ENABLED",
    "SESSION_TIMEOUT_SECONDS",
    "AnalyticsConfig",
    "AnalyticsService",
    "BaseQueue",
    "CalibrationConfig",
    "CalibrationService",
    "ConfigService",
    "CoordinatorConfig",
    "CoordinatorService",
    "HealthMonitorConfig",
    "HealthMonitorService",
    "Job",
    "KeyManagementService",
    "LibraryRootConfig",
    "LibraryService",
    "MLConfig",
    "MLService",
    "NavidromeConfig",
    "NavidromeService",
    "ProcessingQueue",
    "ProcessingService",
    "QueueService",
    "RecalibrationQueue",
    "RecalibrationService",
    "ScanQueue",
    "WorkerConfig",
    "WorkerService",
    "check_missing_calibrations",
    "download_calibrations",
    "ensure_calibrations_exist",
    "process_file_wrapper",
]
