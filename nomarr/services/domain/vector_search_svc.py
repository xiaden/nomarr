"""Vector search service for similarity search on cold collections."""

import logging
from typing import Any

from nomarr.components.ml.ml_vector_maintenance_comp import has_vector_index
from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


class VectorSearchService:
    """Service for vector similarity search operations.

    Searches against cold collections only (promoted vectors with indexes).
    Hot collections are write-only and never searched.
    """

    def __init__(self, db: Database) -> None:
        """Initialize vector search service.

        Args:
            db: Database instance
        """
        self.db = db

    def search_similar_tracks(
        self,
        backbone_id: str,
        vector: list[float],
        limit: int,
        min_score: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Search for similar tracks using vector similarity.

        Searches cold collection only (never falls back to hot).
        Requires cold collection to have a vector index.

        Args:
            backbone_id: Backbone identifier (e.g., "effnet", "yamnet")
            vector: Query embedding vector
            limit: Maximum number of results
            min_score: Minimum similarity score threshold (filters raw results)

        Returns:
            List of matching results with keys:
                - file_id: Library file document ID
                - score: Similarity score
                - vector: The stored embedding vector
                - Other document fields

        Raises:
            ValueError: If cold collection has no vector index (search not available)
            RuntimeError: If search query fails
        """
        # Validate vector index exists
        if not has_vector_index(self.db.db, backbone_id):
            msg = (
                f"Vector search not available for backbone '{backbone_id}': "
                f"cold collection has no vector index. "
                f"Run promote & rebuild workflow to create index."
            )
            raise ValueError(msg)

        # Get cold operations and search
        cold_ops = self.db.get_vectors_track_cold(backbone_id)

        try:
            raw_results = cold_ops.search_similar(vector, limit)
        except Exception as e:
            logger.error(
                f"Vector search failed for backbone={backbone_id}, limit={limit}: {e}",
                exc_info=True,
            )
            raise RuntimeError(f"Vector search failed: {e}") from e

        # Apply min_score filtering
        filtered_results = [
            result for result in raw_results if result.get("score", 0.0) >= min_score
        ]

        logger.debug(
            f"Vector search: backbone={backbone_id}, limit={limit}, "
            f"raw_results={len(raw_results)}, filtered={len(filtered_results)}"
        )

        return filtered_results

    def get_track_vector(
        self, backbone_id: str, file_id: str
    ) -> dict[str, Any] | None:
        """Get vector for a specific track.

        Tries cold collection first, then falls back to hot if not found.
        Fallback to hot allows retrieval of not-yet-promoted vectors.

        Args:
            backbone_id: Backbone identifier
            file_id: Library file document ID

        Returns:
            Vector document or None if not found in either collection
        """
        # Try cold first (promoted vectors)
        cold_ops = self.db.get_vectors_track_cold(backbone_id)
        result = cold_ops.get_vector(file_id)

        if result is not None:
            logger.debug(
                f"Vector found in cold: backbone={backbone_id}, file_id={file_id}"
            )
            return result

        # Fallback to hot (not yet promoted)
        hot_ops = self.db.register_vectors_track_backbone(backbone_id)
        result = hot_ops.get_vector(file_id)

        if result is not None:
            logger.debug(
                f"Vector found in hot: backbone={backbone_id}, file_id={file_id}"
            )
            return result

        logger.debug(f"Vector not found: backbone={backbone_id}, file_id={file_id}")
        return None
