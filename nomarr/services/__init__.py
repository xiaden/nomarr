"""Services package.

Organized into domain (business logic) and infrastructure (runtime plumbing) services.
"""

# Domain services
from .domain import (
    AnalyticsConfig,
    AnalyticsService,
    CalibrationConfig,
    CalibrationService,
    LibraryService,
    LibraryServiceConfig,
    MetadataService,
    NavidromeConfig,
    NavidromeService,
    TaggingService,
    TaggingServiceConfig,
)

# Calibration availability helpers (moved from infrastructure in Part B per CONTRACTS D3)
from .domain.calibration_svc import check_missing_calibrations, ensure_calibrations_exist

# Infrastructure services
from .infrastructure import (
    INTERNAL_ALLOW_SHORT,
    INTERNAL_BATCH_SIZE,
    INTERNAL_CALIBRATION_APD_THRESHOLD,
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
    SESSION_TIMEOUT_SECONDS,
    ConfigService,
    HealthMonitorConfig,
    HealthMonitorService,
    InfoService,
    KeyManagementService,
    MLConfig,
    MLService,
    WorkerSystemService,
)

__all__ = [
    "INTERNAL_ALLOW_SHORT",
    "INTERNAL_BATCH_SIZE",
    "INTERNAL_CALIBRATION_APD_THRESHOLD",
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
    "CalibrationConfig",
    "CalibrationService",
    "ConfigService",
    "HealthMonitorConfig",
    "HealthMonitorService",
    "InfoService",
    "KeyManagementService",
    "LibraryService",
    "LibraryServiceConfig",
    "MLConfig",
    "MLService",
    "MetadataService",
    "NavidromeConfig",
    "NavidromeService",
    "TaggingService",
    "TaggingServiceConfig",
    "WorkerSystemService",
    "check_missing_calibrations",
    "ensure_calibrations_exist",
]
