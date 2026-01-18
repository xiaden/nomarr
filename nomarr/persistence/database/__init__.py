"""
Database operations package.

Contains table-specific operations classes (one per table) and joined query operations.
Each *_aql.py file owns all AQL for that specific table.
"""

from .calibration_history_aql import CalibrationHistoryOperations
from .calibration_state_aql import CalibrationStateOperations
from .entities_aql import EntityOperations
from .file_tags_aql import FileTagOperations
from .health_aql import HealthOperations
from .libraries_aql import LibrariesOperations
from .library_files_aql import LibraryFilesOperations
from .library_folders_aql import LibraryFoldersOperations
from .library_tags_aql import LibraryTagOperations
from .meta_aql import MetaOperations
from .sessions_aql import SessionOperations
from .song_tag_edges_aql import SongTagEdgeOperations
from .tag_queue_aql import QueueOperations

# JoinedQueryOperations has circular import with workflows - imported directly in db.py

__all__ = [
    "CalibrationHistoryOperations",
    "CalibrationStateOperations",
    "EntityOperations",
    "FileTagOperations",
    "HealthOperations",
    "LibrariesOperations",
    "LibraryFilesOperations",
    "LibraryFoldersOperations",
    "LibraryTagOperations",
    "MetaOperations",
    "QueueOperations",
    "SessionOperations",
    "SongTagEdgeOperations",
]
