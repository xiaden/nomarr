"""
Workflows package.
"""

# TODO: Remove scan_library_workflow import once legacy code is fully deleted
from .library.scan_library_wf import update_library_file_from_tags  # scan_library_workflow is commented out
from .library.scan_single_file_wf import scan_single_file_workflow
from .library.start_library_scan_wf import start_library_scan_workflow
from .processing.process_file_wf import process_file_workflow

__all__ = [
    "process_file_workflow",
    # "scan_library_workflow",  # TODO: DELETE - legacy unused workflow
    "scan_single_file_workflow",
    "start_library_scan_workflow",
    "update_library_file_from_tags",
]
