"""
Library package.
"""

# TODO: Remove scan_library_workflow import once legacy code is fully deleted
from .scan_library_wf import update_library_file_from_tags  # scan_library_workflow is commented out
from .scan_single_file_wf import scan_single_file_workflow
from .start_library_scan_wf import LibraryScanStats, start_library_scan_workflow

__all__ = [
    "LibraryScanStats",
    # "scan_library_workflow",  # TODO: DELETE - legacy unused workflow
    "scan_single_file_workflow",
    "start_library_scan_workflow",
    "update_library_file_from_tags",
]
