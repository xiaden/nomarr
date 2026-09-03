"""Vector search service for similarity search on cold collections."""

import logging
from typing import Any

from nomarr.components.ml.vectors.ml_vector_retrieve_comp import (
    get_cold_track_vector,
    search_similar_cold_track_vectors,
)
from nomarr.persistence.db import Database
from nomarr.services.infrastructure.config_svc import ConfigService

logger = logging.getLogger(__name__)


class MissingSeedVectorError(ValueError):
    """Raised when the requested track has no vector for the backbone."""


class VectorIndexUnavailableError(ValueError):
    """Raised when the cold vector index is unavailable for searching."""


class VectorSearchService:
    """Service for vector similarity search operations.

    Searches against cold collections only (promoted vectors with indexes).
    Hot collections are write-only and never searched.
    """

    def __init__(self, db: Database, config_svc: ConfigService) -> None:
        """Initialize vector search service.

        Args:
            db: Database instance
            config_svc: Configuration service for dynamic settings

        """
        self.db = db
        self._config_svc = config_svc

    def search_similar_tracks(
        self,
        file_id: int,
        backbone_id: str,
        limit: int,
        min_score: float = 0.0,
        nprobe: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search for similar tracks using vector similarity.

        Resolves the source track's vector from ``file_id``, then performs a
        single ANN query against the per-backbone cold collection. Cross-library
        search is the default (collections are per-backbone, not per-library).

        Args:
            file_id: Library file document ID to find similar tracks for.
            backbone_id: Backbone identifier (e.g., "effnet", "yamnet")
            limit: Maximum number of results
            min_score: Minimum cosine similarity threshold (-1 to 1). Results below
                this value are filtered out.
            nprobe: Centroids to probe per query. When ``None`` (default),
                auto-calculated from ``vector_group_size`` and
                ``vector_search_thoroughness`` in dynamic config.
                Pass an explicit int to override.

        Returns:
            List of matching results with keys:
                - file_id: Library file document ID
                - score: Cosine similarity in [-1, 1] (higher = more similar)
                - vector: The stored embedding vector
                - Other document fields

        Raises:
            MissingSeedVectorError: If no vector exists for the source track.
            VectorIndexUnavailableError: If the cold vector index is unavailable.
            RuntimeError: If search query fails

        """
        # The cold HNSW index is a service prerequisite; check it before looking
        # up the seed so an unavailable index remains distinct from an
        # unprocessed track.
        if not self.db.ml.has_vector_index(backbone_id):
            raise VectorIndexUnavailableError(f"No vector index available for backbone '{backbone_id}'.")

        # Step 1: Get the source track's vector from the per-backbone cold collection
        vector_doc = get_cold_track_vector(self.db, file_id, backbone_id)
        if vector_doc is None:
            msg = (
                f"No vector found for file '{file_id}' with backbone "
                f"'{backbone_id}'. Track may not have been processed yet."
            )
            raise MissingSeedVectorError(msg)
        vector: list[float] = vector_doc["vector_n"]

        # Step 2: Single ANN search on per-backbone cold collection
        raw_results = search_similar_cold_track_vectors(
            db=self.db,
            backbone_id=backbone_id,
            seed_vector=vector,
            result_limit=limit,
        )

        # SimilarResult exposes the repository's canonical cosine similarity.
        filtered_results = [result for result in raw_results if result["score"] >= min_score]
        filtered_results.sort(key=lambda result: result["score"], reverse=True)

        logger.debug(
            f"Vector search: backbone={backbone_id}, limit={limit}, nprobe={nprobe}, "
            f"raw_results={len(raw_results)}, filtered={len(filtered_results)}"
        )

        return filtered_results

    def get_track_vector(self, backbone_id: str, file_id: int) -> dict[str, Any] | None:
        """Get vector for a specific track.

        Delegates to the get_track_vector workflow, which fetches from the
        per-backbone cold collection directly (no library resolution needed).

        Args:
            backbone_id: Backbone identifier
            file_id: Library file document ID

        Returns:
            Vector document or None if not found

        """
        from nomarr.workflows.vectors.get_track_vector_wf import get_track_vector as get_track_vector_wf

        return get_track_vector_wf(self.db, file_id, backbone_id)
