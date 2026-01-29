"""Workers package - Discovery-based worker system.

This package contains the discovery-based ML processing workers that
query library_files directly instead of using a queue.
"""

from .discovery_worker import DiscoveryWorker, create_discovery_worker

__all__ = [
    "DiscoveryWorker",
    "create_discovery_worker",
]
