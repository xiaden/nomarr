"""
Database operations package.

Contains table-specific operations classes (one per table) and joined query operations.
Each *_table.py file owns all SQL for that specific table.
joined_queries.py owns multi-table JOIN queries.
"""

from .calibration_queue_table import CalibrationQueueOperations
from .calibration_runs_table import CalibrationRunsOperations
from .library_files_table import LibraryFilesOperations
from .library_queue_table import LibraryQueueOperations
from .library_tags_table import TagOperations
from .meta_table import MetaOperations
from .sessions_table import SessionOperations
from .tag_queue_table import QueueOperations
from .utils import count_and_delete, count_and_update, get_queue_stats, safe_count

# JoinedQueryOperations has circular import with workflows - imported directly in db.py

__all__ = [
    "CalibrationQueueOperations",
    "CalibrationRunsOperations",
    "LibraryFilesOperations",
    "LibraryQueueOperations",
    "MetaOperations",
    "QueueOperations",
    "SessionOperations",
    "TagOperations",
    "count_and_delete",
    "count_and_update",
    "get_queue_stats",
    "safe_count",
]
