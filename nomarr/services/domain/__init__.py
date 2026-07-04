"""Domain services — business logic service classes with DI wiring.

Provides the domain service layer for the application:
- ``AnalyticsService`` — library-wide analytics computations
- ``CalibrationService`` — calibration lifecycle management
- ``LibraryService`` — library CRUD, scanning, queries, file operations
- ``MetadataService`` — entity navigation and metadata operations
- ``NavidromeService`` — playlist generation and Navidrome integration
- ``TaggingService`` — calibrated tag writing and curation
"""

from .analytics_svc import AnalyticsConfig, AnalyticsService
from .calibration_svc import CalibrationConfig, CalibrationService
from .library_svc import LibraryService, LibraryServiceConfig
from .metadata_svc import MetadataService
from .navidrome_svc import NavidromeConfig, NavidromeService
from .tagging_svc import TaggingService, TaggingServiceConfig

__all__ = [
    "AnalyticsConfig",
    "AnalyticsService",
    "CalibrationConfig",
    "CalibrationService",
    "LibraryService",
    "LibraryServiceConfig",
    "MetadataService",
    "NavidromeConfig",
    "NavidromeService",
    "TaggingService",
    "TaggingServiceConfig",
]
