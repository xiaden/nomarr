"""Vector search service for similarity search on cold collections."""

import logging
from typing import Any

from nomarr.components.library.file_library_comp import get_file_library_key
from nomarr.components.library.library_records_comp import list_library_records
from nomarr.components.ml.vectors.ml_vector_maintenance_comp import has_vector_index
from nomarr.components.ml.vectors.ml_vector_registry_comp import get_cold_namespace
from nomarr.components.ml.vectors.ml_vector_retrieve_comp import get_cold_track_vector
from nomarr.helpers.vector_params_helper import compute_nlists, compute_nprobe
from nomarr.persistence.db import Database
from nomarr.services.infrastructure.config_svc import ConfigService
from nomarr.workflows.vectors.get_track_vector_wf import get_track_vector as get_track_vector_wf

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
        file_id: str,
        backbone_id: str,
        limit: int,
        min_score: float = 0.0,
        nprobe: int | None = None,
        library_scope: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search for similar tracks using vector similarity.

        Resolves the source track's library and vector internally from
        ``file_id``, then searches cold collection(s).

        Args:
            file_id: Library file document ID to find similar tracks for.
            backbone_id: Backbone identifier (e.g., "effnet", "yamnet")
            limit: Maximum number of results
            min_score: Minimum cosine similarity threshold (0-1). Results below
                this value are filtered out.
            nprobe: Centroids to probe per query. When ``None`` (default),
                auto-calculated from ``vector_group_size`` and
                ``vector_search_thoroughness`` in dynamic config.
                Pass an explicit int to override.
            library_scope: Controls which libraries to search.
                ``None`` or ``"own"`` — search source track's library only.
                ``"all"`` — fan-out across every library's cold collection.
                Any other string — treated as a specific library ``_key``.

        Returns:
            List of matching results with keys:
                - file_id: Library file document ID
                - score: Cosine similarity (0-1, higher = more similar)
                - vector: The stored embedding vector
                - Other document fields

        Raises:
            ValueError: If file not found, no vector exists, or cold collection
                has no vector index.
            RuntimeError: If search query fails
        """
        # Step 1: Resolve library_key from file_id
        library_key = get_file_library_key(self.db, file_id)
        if library_key is None:
            msg = f"File '{file_id}' not found or has no library association"
            raise ValueError(msg)

        # Step 2: Get the source track's vector
        vector_doc = get_cold_track_vector(self.db, file_id, backbone_id, library_key)
        if vector_doc is None:
            msg = (
                f"No vector found for file '{file_id}' with backbone "
                f"'{backbone_id}'. Track may not have been processed yet."
            )
            raise ValueError(msg)
        vector: list[float] = vector_doc["vector_n"]

        # Step 3: Search
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
        if not has_vector_index(self.db, backbone_id, target_library):
            msg = (
                f"Vector search not available for backbone '{backbone_id}' "
                f"library '{target_library}': cold collection has no vector index. "
                f"Run promote & rebuild workflow to create index."
            )
            raise ValueError(msg)

        # Get cold operations and search
        cold_ops = get_cold_namespace(self.db, backbone_id, target_library)

        # Auto-calculate nprobe from config when not explicitly provided
        if nprobe is None:
            doc_count = cold_ops.count()
            group_size: int = self._config_svc.get("vector_group_size", 15)
            thoroughness: int = self._config_svc.get("vector_search_thoroughness", 10)
            nlists = compute_nlists(doc_count, group_size)
            nprobe = compute_nprobe(nlists, thoroughness)

        try:
            raw_results = cold_ops.ann_search(vector, limit, nprobe=nprobe)
        except Exception as e:
            logger.error(
                f"Vector search failed for backbone={backbone_id}, library={target_library}, limit={limit}: {e}",
                exc_info=True,
            )
            raise RuntimeError(f"Vector search failed: {e}") from e

        # Apply min_score filtering
        filtered_results = [result for result in raw_results if result.get("score", 0.0) >= min_score]

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
        libraries = list_library_records(self.db, include_scan=False)

        for lib in libraries:
            lib_key: str = lib["_key"]
            cold_coll_name = f"vectors_track_cold__{backbone_id}__{lib_key}"
            if not self.db.db.has_collection(cold_coll_name):
                continue

            try:
                cold_ops = get_cold_namespace(self.db, backbone_id, lib_key)
                doc_count = cold_ops.count()
                if doc_count == 0:
                    continue

                effective_nprobe = nprobe
                if effective_nprobe is None:
                    group_size: int = self._config_svc.get("vector_group_size", 15)
                    thoroughness: int = self._config_svc.get("vector_search_thoroughness", 10)
                    nlists = compute_nlists(doc_count, group_size)
                    effective_nprobe = compute_nprobe(nlists, thoroughness)

                results = cold_ops.ann_search(vector, limit, nprobe=effective_nprobe)
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

    def get_track_vector(self, backbone_id: str, file_id: str) -> dict[str, Any] | None:
        """Get vector for a specific track.

        Delegates to the get_track_vector workflow, which resolves the
        owning library and fetches from cold collection only.

        Args:
            backbone_id: Backbone identifier
            file_id: Library file document ID

        Returns:
            Vector document or None if not found
        """
        return get_track_vector_wf(self.db, file_id, backbone_id)
