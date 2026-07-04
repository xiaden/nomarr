"""Processing workflows — audio file processing and tag writing pipeline.

The ``process_file_workflow`` orchestrates end-to-end file processing:
audio loading, ML inference, embedding computation, and calibrated
tag writing to audio files.
"""

from .process_file_wf import process_file_workflow

__all__ = [
    "process_file_workflow",
]
