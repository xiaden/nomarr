"""Database operations package.

Contains table-specific operations classes (one per collection).

Structure:
- Single-file modules (e.g., libraries_aql.py) for simple operations
- Multi-file subpackages (e.g., library_files_aql/, tags_aql/) for complex operations

All Operations classes are exported from this __init__.py for consistent imports:
    from nomarr.persistence.database import LibrariesOperations, TagOperations

When operations grow large (500+ lines), split into a subpackage with logical
modules (crud.py, queries.py, stats.py) while keeping the same import path.
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
