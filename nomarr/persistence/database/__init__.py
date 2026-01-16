"""
Database operations package.

Contains table-specific operations classes (one per table) and joined query operations.
Each *_aql.py file owns all AQL for that specific table.
"""

from .file_tags_aql import FileTagOperations
from .library_files_aql import LibraryFilesOperations
from .meta_aql import MetaOperations
from .sessions_aql import SessionOperations
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
