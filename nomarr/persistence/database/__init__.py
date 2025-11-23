"""
Database package.
"""

from .calibration import CalibrationOperations, now_ms
from .calibration_queue_table import CalibrationQueueOperations, now_ms
from .calibration_runs_table import CalibrationRunsOperations, now_ms
from .library import LibraryOperations, now_ms
from .library_files_table import LibraryFilesOperations, now_ms
from .library_queue_table import LibraryQueueOperations, now_ms
from .library_tags_table import TagOperations
from .meta import MetaOperations
from .meta_table import MetaOperations

# from .navidrome_smart_playlists import NavidromeSmartPlaylistsOperations  # Circular import - import directly
from .queue import QueueOperations, now_ms
from .sessions_table import SessionOperations
from .tag_queue_table import QueueOperations, now_ms
from .tags import TagOperations
from .utils import count_and_delete, count_and_update, get_queue_stats, safe_count

__all__ = [
    "CalibrationOperations",
    "CalibrationQueueOperations",
    "CalibrationRunsOperations",
    "LibraryFilesOperations",
    "LibraryOperations",
    "LibraryQueueOperations",
    "MetaOperations",
    "NavidromeSmartPlaylistsOperations",
    "QueueOperations",
    "SessionOperations",
    "TagOperations",
    "count_and_delete",
    "count_and_update",
    "get_queue_stats",
    "now_ms",
    "safe_count",
]
