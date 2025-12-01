"""
Database operations package.

Contains table-specific operations classes (one per table) and joined query operations.
Each *_sql.py file owns all SQL for that specific table.
joined_queries_sql.py owns multi-table JOIN queries.
"""

from .calibration_queue_sql import CalibrationQueueOperations
from .calibration_runs_sql import CalibrationRunsOperations
from .file_tags_sql import FileTagOperations
from .library_files_sql import LibraryFilesOperations
from .library_queue_sql import LibraryQueueOperations
from .meta_sql import MetaOperations
from .sessions_sql import SessionOperations
from .shared_sql import count_and_delete, count_and_update, get_queue_stats, safe_count
from .tag_queue_sql import QueueOperations

# JoinedQueryOperations has circular import with workflows - imported directly in db.py

__all__ = [
    "CalibrationQueueOperations",
    "CalibrationRunsOperations",
    "FileTagOperations",
    "LibraryFilesOperations",
    "LibraryQueueOperations",
    "MetaOperations",
    "QueueOperations",
    "SessionOperations",
    "count_and_delete",
    "count_and_update",
    "get_queue_stats",
    "safe_count",
]
