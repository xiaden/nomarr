"""Vector maintenance service for promote & rebuild operations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.infrastructure.config_svc import ConfigService

from nomarr.components.ml.onnx.ml_discovery_comp import discover_backbones
from nomarr.helpers.vector_params_helper import get_ef_construction
from nomarr.workflows.platform.promote_and_rebuild_vectors_wf import (
    promote_and_rebuild_workflow,
)
from nomarr.workflows.platform.rebuild_vector_index_wf import (
    rebuild_vector_index_workflow,
)

logger = logging.getLogger(__name__)


class VectorMaintenanceService:
    """Service for vector maintenance operations.

    Coordinates promote & rebuild workflow and provides stats for monitoring.
    """

    def __init__(self, db: Database, models_dir: str, config_svc: ConfigService) -> None:
        """Initialize vector maintenance service.

        Args:
            db: Database instance
            models_dir: Path to ML models directory
            config_svc: Configuration service for dynamic settings

        """
        self.db = db
        self.models_dir = models_dir
        self._config_svc = config_svc

    def promote_and_rebuild(
        self,
        backbone_id: str,
        nlists: int | None = None,
    ) -> None:
        """Promote vectors from hot to cold and rebuild vector index.

        If nlists not provided, calculates optimal value based on cold tier size.

        Args:
            backbone_id: Backbone identifier (e.g., "effnet", "yamnet")
            nlists: Number of HNSW graph lists (optional, auto-calculated if None)

        Raises:
            ValueError: If backbone not found or embed_dim cannot be determined
            RuntimeError: If hot not empty after drain

        """
        # Auto-calculate ef_construction if not provided
        if nlists is None:
            stats = self.get_hot_cold_stats(backbone_id)
            # Use cold count + hot count for sizing (total vectors after merge)
            total_count = stats["hot_count"] + stats["cold_count"]
            nlists = self.calculate_optimal_ef_construction(total_count)
            logger.info(
                f"Auto-calculated ef_construction={nlists} for backbone={backbone_id} "
                f"(hot={stats['hot_count']}, cold={stats['cold_count']})"
            )

        logger.info(f"Starting promote & rebuild: backbone={backbone_id}, nlists={nlists}")

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

    def get_hot_cold_stats(self, backbone_id: str, library_id: int | None = None) -> dict[str, int | bool]:
        """Get hot/cold statistics for a backbone.

        Args:
            backbone_id: Backbone identifier
            library_id: Optional library ID to scope the counts

        Returns:
            Dict with keys:
                - hot_count: Number of vectors in hot tier
                - cold_count: Number of vectors in cold tier
                - index_exists: Whether cold tier has vector index

        """
        stats = self.db.ml.get_embedding_stats(backbone_id, library_id=library_id)
        return {
            **stats,
            "index_exists": self.db.ml.has_embedding_index(backbone_id),
        }

    def get_backbone_vector_stats(self, library_id: int | None = None) -> list[dict[str, str | int | bool]]:
        """Get per-backbone vector statistics, optionally for one library.

        Iterates all discovered backbones and returns hot/cold stats for each.

        Returns:
            List of stats rows containing ``backbone_id``, ``hot_count``,
            ``cold_count``, and ``index_exists``.

        """
        stats: list[dict[str, str | int | bool]] = []
        for backbone_id in discover_backbones(self.models_dir):
            try:
                backbone_stats = self.get_hot_cold_stats(backbone_id, library_id=library_id)
                stats.append(
                    {
                        "backbone_id": backbone_id,
                        "hot_count": int(backbone_stats["hot_count"]),
                        "cold_count": int(backbone_stats["cold_count"]),
                        "index_exists": bool(backbone_stats["index_exists"]),
                    }
                )
            except Exception:
                logger.warning("Failed to get vector stats for backbone %s", backbone_id, exc_info=True)
                continue

        return stats

    def calculate_optimal_ef_construction(self, doc_count: int) -> int:
        """Calculate optimal HNSW ef_construction for vector index based on document count.

        Delegates to :func:`~nomarr.helpers.vector_params_helper.get_ef_construction`
        which scales the build-time parameter by collection size.

        Args:
            doc_count: Total number of documents

        Returns:
            Optimal ef_construction value (100-500)

        """
        return get_ef_construction(doc_count)

    def rebuild_index(
        self,
        backbone_id: str,
        nlists: int | None = None,
    ) -> None:
        """Drop and rebuild the vector index without promoting hot vectors.

        Use this to update index parameters (e.g. nLists) when cold is already
        fully populated. Faster than promote_and_rebuild when there is no
        pending hot data.

        Args:
            backbone_id: Backbone identifier (e.g., "effnet", "yamnet")
            nlists: Number of Voronoi cells (auto-calculated if None)

        Raises:
            ValueError: If backbone not found, cold tier missing,
                or embed_dim cannot be determined
            RuntimeError: If index creation fails

        """
        if nlists is None:
            stats = self.get_hot_cold_stats(backbone_id)
            nlists = self.calculate_optimal_ef_construction(int(stats["cold_count"]))
            logger.info(
                f"Auto-calculated ef_construction={nlists} for backbone={backbone_id} (cold={stats['cold_count']})"
            )

        logger.info(f"Starting index rebuild: backbone={backbone_id}, nlists={nlists}")

        try:
            rebuild_vector_index_workflow(
                db=self.db,
                backbone_id=backbone_id,
                models_dir=self.models_dir,
            )
            logger.info(f"Index rebuild completed: backbone={backbone_id}")
        except Exception as e:
            logger.error(
                f"Index rebuild failed: backbone={backbone_id}, error={e}",
                exc_info=True,
            )
            raise
