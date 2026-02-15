"""Database operations package.

Contains table-specific operations classes (one per table) and joined query operations.
Each *_aql.py file owns all AQL for that specific table.
"""

from .calibration_history_aql import CalibrationHistoryOperations
from .calibration_state_aql import CalibrationStateOperations
from .health_aql import HealthOperations
from .libraries_aql import LibrariesOperations
from .library_files_aql import LibraryFilesOperations
from .library_folders_aql import LibraryFoldersOperations
from .meta_aql import MetaOperations
from .segment_scores_stats_aql import SegmentScoresStatsOperations
from .sessions_aql import SessionOperations
from .tags_aql import TagOperations

# JoinedQueryOperations has circular import with workflows - imported directly in db.py

__all__ = [
    "CalibrationHistoryOperations",
    "CalibrationStateOperations",
    "HealthOperations",
    "LibrariesOperations",
    "LibraryFilesOperations",
    "LibraryFoldersOperations",
    "MetaOperations",
    "SegmentScoresStatsOperations",
    "SessionOperations",
    "TagOperations",
]
