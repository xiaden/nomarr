"""
Services package.
"""

from .analytics import (
    get_artist_tag_profile,
    get_mood_distribution,
    get_mood_value_co_occurrences,
    get_tag_correlation_matrix,
    get_tag_frequencies,
)
from .config import ConfigService
from .health_monitor import HealthMonitor
from .keys import SESSION_TIMEOUT_SECONDS, KeyManagementService
from .library import LibraryService
from .processing import ProcessingService
from .queue import QueueService
from .worker import WorkerService

__all__ = [
    "SESSION_TIMEOUT_SECONDS",
    "ConfigService",
    "HealthMonitor",
    "KeyManagementService",
    "LibraryService",
    "ProcessingService",
    "QueueService",
    "WorkerService",
    "get_artist_tag_profile",
    "get_mood_distribution",
    "get_mood_value_co_occurrences",
    "get_tag_correlation_matrix",
    "get_tag_frequencies",
]
