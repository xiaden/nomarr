"""Worker system service — manages the discovery-based worker runtime.

Provides the ``WorkerSystemService`` which coordinates discovery workers,
handles lifecycle management, and integrates with the background task system
for ML processing orchestration.
"""

from .main import WorkerSystemService

__all__ = ["WorkerSystemService"]
