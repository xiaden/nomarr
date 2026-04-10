"""Cold vectors track operations for ArangoDB."""

from typing import Any, cast

from nomarr.persistence.arango_client import DatabaseLike


class VectorsTrackColdOperations:
    """Operations for cold collection (read/search-only, vector index required for search).

    Cold collections hold promoted vectors with vector indexes for similarity search.
    Vector indexes are created manually via maintenance workflow, never by bootstrap.

    Collection naming: vectors_track_cold__{backbone_id}__{library_key}[__{suffix}]
    """

    def __init__(
        self,
        db: DatabaseLike,
        backbone_id: str,
        library_key: str,
        collection_suffix: str | None = None,
    ) -> None:
        self.db = db
        self.backbone_id = backbone_id
        self.library_key = library_key
        base = f"vectors_track_cold__{backbone_id}__{library_key}"
        self.collection_name = f"{base}__{collection_suffix}" if collection_suffix else base
        self.collection = db.collection(self.collection_name)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_vector(self, file_id: str) -> dict[str, Any] | None:
        """Get the most recent vector document for a file from cold collection.

        Uses graph traversal via file_has_vectors edge collection.
        This is the primary read path for promoted vectors.

        Args:
            file_id: Library file document ID.

        Returns:
            Document dict or ``None`` if no vector exists for this file.

        """
        cursor = self.db.aql.execute(
            """
            FOR vec IN OUTBOUND @file_id file_has_vectors
                FILTER IS_SAME_COLLECTION(@coll, vec)
                SORT vec.created_at DESC
                LIMIT 1
                RETURN vec
            """,
            bind_vars={"file_id": file_id, "coll": self.collection_name},
        )
        results = list(cursor)  # type: ignore[arg-type]
        return cast("dict[str, Any]", results[0]) if results else None

    def get_vectors_by_file_ids(self, file_ids: list[str]) -> list[dict[str, Any]]:
        """Get vector documents for multiple files from cold collection.

        Uses graph traversal via file_has_vectors edge collection.

        Args:
            file_ids: List of library file document IDs.

        Returns:
            List of vector documents (one per file that has a stored vector).

        """
        if not file_ids:
            return []
        cursor = self.db.aql.execute(
            """
            FOR file_id IN @file_ids
                FOR vec IN OUTBOUND file_id file_has_vectors
                    FILTER IS_SAME_COLLECTION(@coll, vec)
                    RETURN vec
            """,
            bind_vars={"file_ids": file_ids, "coll": self.collection_name},
        )
        return list(cursor)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_similar(self, vector: list[float], limit: int, nprobe: int = 20) -> list[dict[str, Any]]:
        """Search for similar vectors using ANN index.

        Returns raw results with distance scores. Service layer applies min_score filtering.

        Requires vector index to exist on cold collection (created via promote & rebuild).

        Args:
            vector: Query embedding vector.
            limit: Maximum number of results to return.
            nprobe: Number of centroids to probe during search. Higher values improve
                recall at the cost of latency. Overrides defaultNProbe from the index.
                Should be roughly 10% of nLists (e.g. nprobe=20 for nLists=170).

        Returns:
            List of dicts with keys:
                - file_id: Library file document ID (resolved via file_has_vectors edge)
                - score: Cosine similarity (higher = more similar)
                - vector: The stored embedding vector
                - All other document fields (_key, model_suite_hash, etc.)

        Raises:
            ArangoDB error if no vector index exists on collection.

        """
        cursor = self.db.aql.execute(
            f"""
            FOR doc IN {self.collection_name}
                LET score = APPROX_NEAR_COSINE(doc.vector_n, @query_vector, {{nProbe: {nprobe}}})
                // Resolve file_id via edge traversal (FK-free)
                LET file_ids = (
                    FOR f IN INBOUND doc file_has_vectors
                        RETURN f._id
                )
                LET file_id = FIRST(file_ids)
                SORT score DESC
                LIMIT @limit
                RETURN MERGE(doc, {{ score: score, file_id: file_id }})
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {"query_vector": vector, "limit": limit},
            ),
        )
        return list(cursor)  # type: ignore[arg-type]

    # ------------------------------------------------------------------

    def search_similar_by_genre(
        self,
        vector: list[float],
        genre: str,
        limit: int,
        nprobe: int = 20,
    ) -> list[dict[str, Any]]:
        """Search for similar vectors filtered to a specific genre using ANN index.

        Like `search_similar`, but restricts results to documents whose ``genres``
        list contains *genre*.  The vector index must have ``storedValues`` set to
        ``[{"fields": ["genres"]}]`` so that ArangoDB can apply the filter without
        fetching the full document from storage.

        Args:
            vector: Query embedding vector.
            genre: Genre string to filter on (must appear in doc.genres).
            limit: Maximum number of results to return.
            nprobe: Number of centroids to probe during search. Higher values improve
                recall at the cost of latency. Overrides defaultNProbe from the index.
                Should be roughly 10% of nLists (e.g. nprobe=20 for nLists=170).

        Returns:
            List of dicts with keys:
                - file_id: Library file document ID (resolved via file_has_vectors edge)
                - score: Cosine similarity (higher = more similar)
                - vector: The stored embedding vector
                - All other document fields (_key, model_suite_hash, genres, etc.)

        Raises:
            ArangoDB error if no vector index exists on collection.

        """
        cursor = self.db.aql.execute(
            f"""
            FOR doc IN {self.collection_name}
                LET score = APPROX_NEAR_COSINE(doc.vector_n, @query_vector, {{nProbe: {nprobe}}})
                FILTER @genre IN doc.genres
                // Resolve file_id via edge traversal (FK-free)
                LET file_ids = (
                    FOR f IN INBOUND doc file_has_vectors
                        RETURN f._id
                )
                LET file_id = FIRST(file_ids)
                SORT score DESC
                LIMIT @limit
                RETURN MERGE(doc, {{ score: score, file_id: file_id }})
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {"query_vector": vector, "limit": limit, "genre": genre},
            ),
        )
        return list(cursor)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Count documents in cold collection.

        Returns:
            Number of documents in cold collection.
        """
        cursor = self.db.aql.execute(
            f"""
            RETURN LENGTH({self.collection_name})
            """
        )
        results = list(cursor)  # type: ignore[arg-type]
        return cast("int", results[0]) if results else 0

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_by_file_id(self, file_id: str) -> int:
        """Delete all vector documents for a given file from cold collection.

        Uses graph traversal to find vectors, removes them, then cascade-deletes edges.

        Args:
            file_id: Library file document ID.

        Returns:
            Number of documents deleted.

        """
        collection_name = self.collection_name
        # Remove vectors via traversal
        cursor = self.db.aql.execute(
            f"""
            FOR vec IN OUTBOUND @file_id file_has_vectors
                FILTER IS_SAME_COLLECTION(@coll, vec)
                REMOVE vec IN {collection_name}
                COLLECT WITH COUNT INTO removed
                RETURN removed
            """,
            bind_vars={"file_id": file_id, "coll": collection_name},
        )
        results = list(cursor)  # type: ignore[arg-type]
        removed = cast("int", results[0]) if results else 0

        # Cascade-delete edges pointing to this collection
        self.db.aql.execute(
            """
            FOR e IN file_has_vectors
                FILTER e._from == @file_id AND STARTS_WITH(e._to, @coll_prefix)
                REMOVE e IN file_has_vectors
            """,
            bind_vars={
                "file_id": file_id,
                "coll_prefix": f"{collection_name}/",
            },
        )
        return removed

    def delete_by_file_ids(self, file_ids: list[str]) -> int:
        """Bulk delete vector documents for multiple files from cold collection.

        Uses graph traversal to find vectors, removes them, then cascade-deletes edges.

        Args:
            file_ids: List of library file document IDs.

        Returns:
            Number of documents deleted.

        """
        if not file_ids:
            return 0
        collection_name = self.collection_name
        # Remove vectors via traversal
        cursor = self.db.aql.execute(
            f"""
            FOR file_id IN @file_ids
                FOR vec IN OUTBOUND file_id file_has_vectors
                    FILTER IS_SAME_COLLECTION(@coll, vec)
                    REMOVE vec IN {collection_name}
                    COLLECT WITH COUNT INTO removed
                    RETURN removed
            """,
            bind_vars={"file_ids": file_ids, "coll": collection_name},
        )
        results = list(cursor)  # type: ignore[arg-type]
        removed = cast("int", results[0]) if results else 0

        # Cascade-delete edges pointing to this collection
        self.db.aql.execute(
            """
            FOR e IN file_has_vectors
                FILTER e._from IN @file_ids AND STARTS_WITH(e._to, @coll_prefix)
                REMOVE e IN file_has_vectors
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "file_ids": file_ids,
                    "coll_prefix": f"{collection_name}/",
                },
            ),
        )
        return removed

    def truncate(self) -> None:
        """Remove all documents from cold collection.

        Used for testing and maintenance. Drops all promoted vectors.
        """
        self.collection.truncate()
