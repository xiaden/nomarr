"""Vector maintenance service for promote & rebuild operations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.services.infrastructure.config_svc import ConfigService

from nomarr.components.ml.onnx.ml_discovery_comp import discover_backbones
from nomarr.components.ml.vectors.ml_vector_maintenance_comp import has_vector_index
from nomarr.helpers.vector_params_helper import compute_nlists
from nomarr.persistence.db import Database
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
        library_key: str,
        nlists: int | None = None,
    ) -> None:
        """Promote vectors from hot to cold and rebuild vector index.

        Synchronous operation - blocks until complete.
        If nlists not provided, calculates optimal value based on cold collection size.

        Args:
            backbone_id: Backbone identifier (e.g., "effnet", "yamnet")
            library_key: ArangoDB ``_key`` of the library document.
            nlists: Number of HNSW graph lists (optional, auto-calculated if None)

        Raises:
            ValueError: If backbone not found or embed_dim cannot be determined
            RuntimeError: If hot not empty after drain
        """
        # Auto-calculate nlists if not provided
        if nlists is None:
            stats = self.get_hot_cold_stats(backbone_id, library_key)
            # Use cold count + hot count for sizing (total vectors after merge)
            total_count = stats["hot_count"] + stats["cold_count"]
            nlists = self.calculate_optimal_nlists(total_count, library_key)
            logger.info(
                f"Auto-calculated nlists={nlists} for backbone={backbone_id} "
                f"(hot={stats['hot_count']}, cold={stats['cold_count']})"
            )

        logger.info(f"Starting promote & rebuild: backbone={backbone_id}, library={library_key}, nlists={nlists}")

        try:
            promote_and_rebuild_workflow(
                db=self.db,
                backbone_id=backbone_id,
                library_key=library_key,
                nlists=nlists,
                models_dir=self.models_dir,
            )
            logger.info(f"Promote & rebuild completed: backbone={backbone_id}, library={library_key}")
        except Exception as e:
            logger.error(
                f"Promote & rebuild failed: backbone={backbone_id}, library={library_key}, error={e}",
                exc_info=True,
            )
            raise

    def get_hot_cold_stats(self, backbone_id: str, library_key: str) -> dict[str, int | bool]:
        """Get hot/cold statistics for a backbone+library.

        Args:
            backbone_id: Backbone identifier
            library_key: ArangoDB ``_key`` of the library document.

        Returns:
            Dict with keys:
                - hot_count: Number of vectors in hot collection
                - cold_count: Number of vectors in cold collection
                - index_exists: Whether cold collection has vector index
        """
        hot_ops = self.db.register_vectors_track_backbone(backbone_id, library_key)
        cold_ops = self.db.get_vectors_track_cold(backbone_id, library_key)

        hot_coll_name = f"vectors_track_hot__{backbone_id}__{library_key}"
        cold_coll_name = f"vectors_track_cold__{backbone_id}__{library_key}"

        # Check if hot collection exists before counting
        hot_count = hot_ops.count() if self.db.db.has_collection(hot_coll_name) else 0
        # Check if cold collection exists before counting
        cold_count = cold_ops.count() if self.db.db.has_collection(cold_coll_name) else 0
        index_exists = has_vector_index(self.db.db, backbone_id, library_key)

        return {
            "hot_count": hot_count,
            "cold_count": cold_count,
            "index_exists": index_exists,
        }

    def get_library_vector_stats(self, library_id: str) -> list[dict[str, str | int | bool]]:
        """Get per-backbone vector statistics for a library.

        Args:
            library_id: Library document ``_id`` or ``_key``.

        Returns:
            List of stats rows containing ``backbone_id``, ``hot_count``,
            ``cold_count``, and ``index_exists``.

        Raises:
            ValueError: If library not found

        """
        library = self.db.libraries.get_library(library_id)
        if library is None:
            msg = f"Library not found: {library_id}"
            raise ValueError(msg)

        library_key = str(library["_key"])
        stats: list[dict[str, str | int | bool]] = []
        for backbone_id in discover_backbones(self.models_dir):
            try:
                backbone_stats = self.get_hot_cold_stats(backbone_id, library_key)
                stats.append(
                    {
                        "backbone_id": backbone_id,
                        "hot_count": int(backbone_stats["hot_count"]),
                        "cold_count": int(backbone_stats["cold_count"]),
                        "index_exists": bool(backbone_stats["index_exists"]),
                    }
                )
            except Exception:
                logger.debug("Failed to get vector stats for backbone %s, library %s", backbone_id, library_key)
                continue

        return stats

    def calculate_optimal_nlists(self, doc_count: int, library_key: str | None = None) -> int:
        """Calculate optimal nlists for vector index based on document count.

        Reads per-library ``vector_group_size`` from the library document when
        *library_key* is provided, falling back to the global
        ``DynamicConfig.vector_group_size`` default.

        Delegates to ``compute_nlists`` helper which uses the N/group_size
        heuristic bounded to [10, 4000].

        Args:
            doc_count: Total number of documents
            library_key: Optional library ``_key`` for per-library config lookup

        Returns:
            Optimal nlists value (10-4000)
        """
        group_size: int = self._config_svc.get("vector_group_size", 15)

        if library_key is not None:
            lib_doc = self.db.libraries.get_library(library_key)
            if lib_doc is not None:
                lib_group_size = lib_doc.get("vector_group_size")
                if lib_group_size is not None:
                    group_size = int(lib_group_size)

        return compute_nlists(doc_count, group_size)

    def rebuild_index(
        self,
        backbone_id: str,
        library_key: str,
        nlists: int | None = None,
    ) -> None:
        """Drop and rebuild the vector index without promoting hot vectors.

        Use this to update index parameters (e.g. nLists) when cold is already
        fully populated. Faster than promote_and_rebuild when there is no
        pending hot data.

        Args:
            backbone_id: Backbone identifier (e.g., "effnet", "yamnet")
            library_key: ArangoDB ``_key`` of the library document.
            nlists: Number of Voronoi cells (auto-calculated if None)

        Raises:
            ValueError: If backbone not found, cold collection missing,
                or embed_dim cannot be determined
            RuntimeError: If index creation fails
        """
        if nlists is None:
            stats = self.get_hot_cold_stats(backbone_id, library_key)
            nlists = self.calculate_optimal_nlists(int(stats["cold_count"]), library_key)
            logger.info(f"Auto-calculated nlists={nlists} for backbone={backbone_id} (cold={stats['cold_count']})")

        logger.info(f"Starting index rebuild: backbone={backbone_id}, library={library_key}, nlists={nlists}")

        try:
            rebuild_vector_index_workflow(
                db=self.db,
                backbone_id=backbone_id,
                library_key=library_key,
                nlists=nlists,
                models_dir=self.models_dir,
            )
            logger.info(f"Index rebuild completed: backbone={backbone_id}, library={library_key}")
        except Exception as e:
            logger.error(
                f"Index rebuild failed: backbone={backbone_id}, library={library_key}, error={e}",
                exc_info=True,
            )
            raise
