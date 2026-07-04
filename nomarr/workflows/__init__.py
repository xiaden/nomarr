"""Workflows layer — process orchestration and task pipelines.

Workflows are pure functions that compose domain components and persistence
operations into deterministic, testable pipelines. They are called by services
and form the middle tier of the architecture:

    interfaces → services → workflows → components → persistence

Sub-packages are organized by domain:

- ``calibration/`` — Histogram calibration, apply, export/import bundles
- ``library/`` — Library scan, tag IO, path reconciliation, file sync
- ``metadata/`` — Entity cleanup (orphan detection/removal)
- ``navidrome/`` — Playlist generation, smart-playlist query parsing, sync
- ``platform/`` — DB preparation, ML model registration, vector maintenance, pruning
- ``playlist_import/`` — Spotify/Deezer playlist conversion to M3U
- ``processing/`` — Audio file processing pipeline and tag writing
- ``vectors/`` — Track vector retrieval and promotion
"""

from .processing.process_file_wf import process_file_workflow

__all__ = [
    "process_file_workflow",
]
