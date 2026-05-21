"""Workers package - Discovery-based worker system.

This package contains the discovery-based ML processing workers that
query library_files directly instead of using a queue.
"""

from .discovery_worker import DiscoveryWorker, create_discovery_worker
from .tag_extraction_worker import TagExtractionWorker

__all__ = [
    "DiscoveryWorker",
    "TagExtractionWorker",
    "create_discovery_worker",
]
