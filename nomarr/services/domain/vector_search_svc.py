"""Vector search service for similarity search on cold collections."""

import logging
from typing import Any

from nomarr.components.ml.vectors.ml_vector_maintenance_comp import has_vector_index
from nomarr.helpers.vector_params_helper import compute_nlists, compute_nprobe
from nomarr.persistence.db import Database
from nomarr.services.infrastructure.config_svc import ConfigService

logger = logging.getLogger(__name__)


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
        backbone_id: str,
        library_key: str,
        vector: list[float],
        limit: int,
        min_score: float = 0.0,
        nprobe: int | None = None,
        library_scope: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search for similar tracks using vector similarity.

        Searches cold collection only (never falls back to hot).
        Requires cold collection to have a vector index.

        Args:
            backbone_id: Backbone identifier (e.g., "effnet", "yamnet")
            library_key: ArangoDB ``_key`` of the source track's library.
                Used for single-library search and as the default scope.
            vector: Query embedding vector
            limit: Maximum number of results
            min_score: Minimum similarity score threshold (filters raw results)
            nprobe: Centroids to probe per query. When ``None`` (default),
                auto-calculated from ``vector_group_size`` and
                ``vector_search_thoroughness`` in dynamic config.
                Pass an explicit int to override.
            library_scope: Controls which libraries to search.
                ``None`` or ``"own"`` — search *library_key*'s collection only.
                ``"all"`` — fan-out across every library's cold collection.
                Any other string — treated as a specific library ``_key``.

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
        # Resolve effective target library based on scope
        if library_scope == "all":
            return self._search_fan_out(
                backbone_id=backbone_id,
                vector=vector,
                limit=limit,
                min_score=min_score,
                nprobe=nprobe,
            )

        target_library = library_key if library_scope is None or library_scope == "own" else library_scope

        # Validate vector index exists
        if not has_vector_index(self.db.db, backbone_id, target_library):
            msg = (
                f"Vector search not available for backbone '{backbone_id}' "
                f"library '{target_library}': cold collection has no vector index. "
                f"Run promote & rebuild workflow to create index."
            )
            raise ValueError(msg)

        # Get cold operations and search
        cold_ops = self.db.get_vectors_track_cold(backbone_id, target_library)

        # Auto-calculate nprobe from config when not explicitly provided
        if nprobe is None:
            doc_count = cold_ops.count()
            group_size: int = self._config_svc.get("vector_group_size", 15)
            thoroughness: int = self._config_svc.get("vector_search_thoroughness", 10)
            nlists = compute_nlists(doc_count, group_size)
            nprobe = compute_nprobe(nlists, thoroughness)

        try:
            raw_results = cold_ops.search_similar(vector, limit, nprobe=nprobe)
        except Exception as e:
            logger.error(
                f"Vector search failed for backbone={backbone_id}, library={target_library}, limit={limit}: {e}",
                exc_info=True,
            )
            raise RuntimeError(f"Vector search failed: {e}") from e

        # Apply min_score filtering
        filtered_results = [
            result for result in raw_results if result.get("score", 0.0) >= min_score
        ]

        logger.debug(
            f"Vector search: backbone={backbone_id}, library={target_library}, limit={limit}, nprobe={nprobe}, "
            f"raw_results={len(raw_results)}, filtered={len(filtered_results)}"
        )

        return filtered_results


    def _search_fan_out(
        self,
        backbone_id: str,
        vector: list[float],
        limit: int,
        min_score: float = 0.0,
        nprobe: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search across ALL library cold collections, merge by score.

        Iterates over every registered library, searches each cold collection
        that exists, and returns the top *limit* results by descending score
        after deduplication by ``file_id``.

        Args:
            backbone_id: Backbone identifier.
            vector: Query embedding vector.
            limit: Maximum number of results to return.
            min_score: Minimum similarity score threshold.
            nprobe: Explicit centroids to probe (auto-calculated per library
                when ``None``).

        Returns:
            Merged, deduplicated, score-sorted list of results capped at *limit*.
        """
        all_results: list[dict[str, Any]] = []
        libraries = self.db.libraries.list_libraries()

        for lib in libraries:
            lib_key: str = lib["_key"]
            cold_coll_name = f"vectors_track_cold__{backbone_id}__{lib_key}"
            if not self.db.db.has_collection(cold_coll_name):
                continue

            try:
                cold_ops = self.db.get_vectors_track_cold(backbone_id, lib_key)
                doc_count = cold_ops.count()
                if doc_count == 0:
                    continue

                effective_nprobe = nprobe
                if effective_nprobe is None:
                    group_size: int = self._config_svc.get("vector_group_size", 15)
                    thoroughness: int = self._config_svc.get("vector_search_thoroughness", 10)
                    nlists = compute_nlists(doc_count, group_size)
                    effective_nprobe = compute_nprobe(nlists, thoroughness)

                results = cold_ops.search_similar(vector, limit, nprobe=effective_nprobe)
                all_results.extend(results)
            except Exception:
                logger.warning(
                    "Fan-out search failed for library %s, skipping",
                    lib_key,
                    exc_info=True,
                )
                continue

        # Sort by score descending and deduplicate by file_id (keep highest score)
        all_results.sort(key=lambda r: r.get("score", 0.0), reverse=True)
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for r in all_results:
            fid: str = r.get("file_id", "")
            if fid not in seen:
                seen.add(fid)
                if r.get("score", 0.0) >= min_score:
                    unique.append(r)

        logger.debug(
            "Fan-out search: backbone=%s, libraries=%d, total_raw=%d, unique=%d, returning=%d",
            backbone_id,
            len(libraries),
            len(all_results),
            len(unique),
            min(limit, len(unique)),
        )
        return unique[:limit]

    def get_track_vector(
        self, backbone_id: str, file_id: str, library_key: str
    ) -> dict[str, Any] | None:
        """Get vector for a specific track.

        Tries cold collection first, then falls back to hot if not found.
        Fallback to hot allows retrieval of not-yet-promoted vectors.

        Args:
            backbone_id: Backbone identifier
            file_id: Library file document ID
            library_key: ArangoDB ``_key`` of the library document.

        Returns:
            Vector document or None if not found in either collection
        """
        hot_coll_name = f"vectors_track_hot__{backbone_id}__{library_key}"
        cold_coll_name = f"vectors_track_cold__{backbone_id}__{library_key}"

        # Try cold first (promoted vectors) - only if collection exists
        result = None
        if self.db.db.has_collection(cold_coll_name):
            cold_ops = self.db.get_vectors_track_cold(backbone_id, library_key)
            result = cold_ops.get_vector(file_id)

        if result is not None:
            logger.debug(
                f"Vector found in cold: backbone={backbone_id}, file_id={file_id}"
            )
            return result

        # Fallback to hot (not yet promoted) - only if collection exists
        if self.db.db.has_collection(hot_coll_name):
            hot_ops = self.db.register_vectors_track_backbone(backbone_id, library_key)
            result = hot_ops.get_vector(file_id)

        if result is not None:
            logger.debug(
                f"Vector found in hot: backbone={backbone_id}, file_id={file_id}"
            )
            return result

        logger.debug(f"Vector not found: backbone={backbone_id}, file_id={file_id}")
        return None
