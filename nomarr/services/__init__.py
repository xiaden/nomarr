"""
Services package.
"""

from .analytics_svc import AnalyticsConfig, AnalyticsService
from .calibration_download_svc import check_missing_calibrations, download_calibrations, ensure_calibrations_exist
from .calibration_svc import CalibrationConfig, CalibrationService
from .config_svc import (
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
from .coordinator_svc import CoordinatorConfig, CoordinatorService
from .health_monitor_svc import HealthMonitorConfig, HealthMonitorService
from .keys_svc import SESSION_TIMEOUT_SECONDS, KeyManagementService
from .library_svc import LibraryRootConfig, LibraryService
from .ml_svc import MLConfig, MLService
from .navidrome_svc import NavidromeConfig, NavidromeService
from .queue_svc import BaseQueue, Job, ProcessingQueue, QueueService, RecalibrationQueue, ScanQueue
from .recalibration_svc import RecalibrationService
from .workers_coordinator_svc import WorkersCoordinator

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
    "QueueService",
    "RecalibrationQueue",
    "RecalibrationService",
    "ScanQueue",
    "WorkersCoordinator",
    "check_missing_calibrations",
    "download_calibrations",
    "ensure_calibrations_exist",
]
