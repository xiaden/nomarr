"""Vector maintenance service for promote & rebuild operations."""

import logging
import math

from nomarr.components.ml.ml_vector_maintenance_comp import has_vector_index
from nomarr.persistence.db import Database
from nomarr.workflows.platform.promote_and_rebuild_vectors_wf import (
    promote_and_rebuild_workflow,
)

logger = logging.getLogger(__name__)


class VectorMaintenanceService:
    """Service for vector maintenance operations.

    Coordinates promote & rebuild workflow and provides stats for monitoring.
    """

    def __init__(self, db: Database, models_dir: str) -> None:
        """Initialize vector maintenance service.

        Args:
            db: Database instance
            models_dir: Path to ML models directory
        """
        self.db = db
        self.models_dir = models_dir

    def promote_and_rebuild(
        self,
        backbone_id: str,
        nlists: int | None = None,
    ) -> None:
        """Promote vectors from hot to cold and rebuild vector index.

        Synchronous operation - blocks until complete.
        If nlists not provided, calculates optimal value based on cold collection size.

        Args:
            backbone_id: Backbone identifier (e.g., "effnet", "yamnet")
            nlists: Number of HNSW graph lists (optional, auto-calculated if None)

        Raises:
            ValueError: If backbone not found or embed_dim cannot be determined
            RuntimeError: If hot not empty after drain
        """
        # Auto-calculate nlists if not provided
        if nlists is None:
            stats = self.get_hot_cold_stats(backbone_id)
            # Use cold count + hot count for sizing (total vectors after merge)
            total_count = stats["hot_count"] + stats["cold_count"]
            nlists = self.calculate_optimal_nlists(total_count)
            logger.info(
                f"Auto-calculated nlists={nlists} for backbone={backbone_id} "
                f"(hot={stats['hot_count']}, cold={stats['cold_count']})"
            )

        logger.info(
            f"Starting promote & rebuild: backbone={backbone_id}, nlists={nlists}"
        )

        try:
            promote_and_rebuild_workflow(
                db=self.db,
                backbone_id=backbone_id,
                nlists=nlists,
                models_dir=self.models_dir,
            )
            logger.info(f"Promote & rebuild completed: backbone={backbone_id}")
        except Exception as e:
            logger.error(
                f"Promote & rebuild failed: backbone={backbone_id}, error={e}",
                exc_info=True,
            )
            raise

    def get_hot_cold_stats(self, backbone_id: str) -> dict[str, int | bool]:
        """Get hot/cold statistics for a backbone.

        Args:
            backbone_id: Backbone identifier

        Returns:
            Dict with keys:
                - hot_count: Number of vectors in hot collection
                - cold_count: Number of vectors in cold collection
                - index_exists: Whether cold collection has vector index
        """
        hot_ops = self.db.register_vectors_track_backbone(backbone_id)
        cold_ops = self.db.get_vectors_track_cold(backbone_id)

        # Check if hot collection exists before counting
        hot_count = (
            hot_ops.count()
            if self.db.db.has_collection(f"vectors_track_hot__{backbone_id}")
            else 0
        )
        # Check if cold collection exists before counting
        cold_count = (
            cold_ops.count()
            if self.db.db.has_collection(f"vectors_track_cold__{backbone_id}")
            else 0
        )
        index_exists = has_vector_index(self.db.db, backbone_id)

        return {
            "hot_count": hot_count,
            "cold_count": cold_count,
            "index_exists": index_exists,
        }

    def calculate_optimal_nlists(self, doc_count: int) -> int:
        """Calculate optimal nlists for vector index based on document count.

        Uses sqrt(doc_count) bounded to [10, 100] range.
        ArangoDB recommends nlists ~ sqrt(doc_count) for good balance.

        Args:
            doc_count: Total number of documents

        Returns:
            Optimal nlists value (10-100)
        """
        if doc_count <= 0:
            return 10

        nlists = int(math.sqrt(doc_count))
        return max(10, min(100, nlists))
