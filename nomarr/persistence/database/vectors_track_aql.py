"""Vectors track operations for ArangoDB.

Each backbone has its own collection named ``vectors_track__{backbone_id}``.
Documents store a pooled track-level embedding vector per file, keyed by
``sha1(file_id|model_suite_hash)``.
"""

import hashlib
import math
from typing import Any, cast

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import DatabaseLike


class VectorsTrackHotOperations:
    """Operations for hot collection (write-only, no vector index).

    Hot collections accumulate vectors during active ML processing without
    triggering expensive HNSW graph maintenance. Vectors are later promoted
    to cold collection via maintenance workflow.

    Collection naming: vectors_track_hot__{backbone_id}__{library_key}
    """

    def __init__(self, db: DatabaseLike, backbone_id: str, library_key: str) -> None:
        self.db = db
        self.backbone_id = backbone_id
        self.library_key = library_key
        self.collection_name = f"vectors_track_hot__{backbone_id}__{library_key}"
        self.collection = db.collection(self.collection_name)

    @staticmethod
    def _make_key(file_id: str, model_suite_hash: str) -> str:
        """Build a deterministic ArangoDB-safe ``_key``.

        Backbone identity is encoded in the collection name, so only
        ``file_id`` and ``model_suite_hash`` contribute to the key.

        This key strategy ensures convergent drain semantics: same file + model
        produces same _key in both hot and cold collections.
        """
        return hashlib.sha1(f"{file_id}|{model_suite_hash}".encode()).hexdigest()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def upsert_vector(
        self,
        file_id: str,
        model_suite_hash: str,
        embed_dim: int,
        vector: list[float],
        num_segments: int,
    ) -> None:
        """Upsert a track-level embedding vector to hot collection.

        Uses atomic AQL UPSERT to handle parallel workers safely.
        No vector index maintenance occurs (hot collections have no vector indexes).

        Both the raw ``vector`` and an L2-normalized copy ``vector_n`` are stored.
        ``vector_n`` is used for cosine index search; ``vector`` is preserved for
        downstream arithmetic (e.g. centroid computation, future metric changes).

        Args:
            file_id: Library file document ID (e.g., ``"library_files/12345"``).
            model_suite_hash: 12-char hex hash from ``compute_model_suite_hash()``.
            embed_dim: Number of embedding dimensions.
            vector: Pooled embedding as a list of floats.
            num_segments: Number of backbone patches that were pooled.

        """
        _key = self._make_key(file_id, model_suite_hash)
        ts = now_ms().value
        collection_name = self.collection_name

        norm = math.sqrt(math.fsum(x * x for x in vector))
        vector_n = [x / norm for x in vector] if norm > 0.0 else list(vector)

        self.db.aql.execute(
            f"""
            UPSERT {{ _key: @_key }}
            INSERT {{
                _key: @_key,
                file_id: @file_id,
                model_suite_hash: @model_suite_hash,
                embed_dim: @embed_dim,
                vector: @vector,
                vector_n: @vector_n,
                num_segments: @num_segments,
                created_at: @ts
            }}
            UPDATE {{
                file_id: @file_id,
                model_suite_hash: @model_suite_hash,
                embed_dim: @embed_dim,
                vector: @vector,
                vector_n: @vector_n,
                num_segments: @num_segments,
                created_at: @ts
            }}
            IN {collection_name}
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "_key": _key,
                    "file_id": file_id,
                    "model_suite_hash": model_suite_hash,
                    "embed_dim": embed_dim,
                    "vector": vector,
                    "vector_n": vector_n,
                    "num_segments": num_segments,
                    "ts": ts,
                },
            ),
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_vector(self, file_id: str) -> dict[str, Any] | None:
        """Get the most recent vector document for a file from hot collection.

        Args:
            file_id: Library file document ID.

        Returns:
            Document dict or ``None`` if no vector exists for this file.

        """
        cursor = self.db.aql.execute(
            f"""
            FOR doc IN {self.collection_name}
                FILTER doc.file_id == @file_id
                SORT doc.created_at DESC
                LIMIT 1
                RETURN doc
            """,
            bind_vars={"file_id": file_id},
        )
        results = list(cursor)  # type: ignore[arg-type]
        return cast("dict[str, Any]", results[0]) if results else None

    def get_vectors_by_file_ids(self, file_ids: list[str]) -> list[dict[str, Any]]:
        """Get vector documents for multiple files from hot collection.

        Args:
            file_ids: List of library file document IDs.

        Returns:
            List of vector documents (one per file that has a stored vector).

        """
        if not file_ids:
            return []
        cursor = self.db.aql.execute(
            f"""
            FOR doc IN {self.collection_name}
                FILTER doc.file_id IN @file_ids
                RETURN doc
            """,
            bind_vars={"file_ids": file_ids},
        )
        return list(cursor)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_by_file_id(self, file_id: str) -> int:
        """Delete all vector documents for a given file from hot collection.

        Args:
            file_id: Library file document ID.

        Returns:
            Number of documents deleted.

        """
        cursor = self.db.aql.execute(
            f"""
            FOR doc IN {self.collection_name}
                FILTER doc.file_id == @file_id
                REMOVE doc IN {self.collection_name}
                COLLECT WITH COUNT INTO removed
                RETURN removed
            """,
            bind_vars={"file_id": file_id},
        )
        results = list(cursor)  # type: ignore[arg-type]
        return cast("int", results[0]) if results else 0

    def delete_by_file_ids(self, file_ids: list[str]) -> int:
        """Bulk delete vector documents for multiple files from hot collection.

        Args:
            file_ids: List of library file document IDs.

        Returns:
            Number of documents deleted.

        """
        if not file_ids:
            return 0
        cursor = self.db.aql.execute(
            f"""
            FOR doc IN {self.collection_name}
                FILTER doc.file_id IN @file_ids
                REMOVE doc IN {self.collection_name}
                COLLECT WITH COUNT INTO removed
                RETURN removed
            """,
            bind_vars={"file_ids": file_ids},
        )
        results = list(cursor)  # type: ignore[arg-type]
        return cast("int", results[0]) if results else 0

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Count documents in hot collection.

        Used to check hot collection size before deciding when to promote.

        Returns:
            Number of documents in hot collection.
        """
        cursor = self.db.aql.execute(
            f"""
            RETURN LENGTH({self.collection_name})
            """
        )
        results = list(cursor)  # type: ignore[arg-type]
        return cast("int", results[0]) if results else 0

    def truncate(self) -> None:
        """Remove all documents from hot collection.

        Used for testing and maintenance. In production, use promote & rebuild
        workflow instead to preserve vectors in cold collection.
        """
        self.collection.truncate()



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

        This is the primary read path for promoted vectors.

        Args:
            file_id: Library file document ID.

        Returns:
            Document dict or ``None`` if no vector exists for this file.

        """
        cursor = self.db.aql.execute(
            f"""
            FOR doc IN {self.collection_name}
                FILTER doc.file_id == @file_id
                SORT doc.created_at DESC
                LIMIT 1
                RETURN doc
            """,
            bind_vars={"file_id": file_id},
        )
        results = list(cursor)  # type: ignore[arg-type]
        return cast("dict[str, Any]", results[0]) if results else None

    def get_vectors_by_file_ids(self, file_ids: list[str]) -> list[dict[str, Any]]:
        """Get vector documents for multiple files from cold collection.

        Args:
            file_ids: List of library file document IDs.

        Returns:
            List of vector documents (one per file that has a stored vector).

        """
        if not file_ids:
            return []
        cursor = self.db.aql.execute(
            f"""
            FOR doc IN {self.collection_name}
                FILTER doc.file_id IN @file_ids
                RETURN doc
            """,
            bind_vars={"file_ids": file_ids},
        )
        return list(cursor)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_similar(
        self, vector: list[float], limit: int, nprobe: int = 20
    ) -> list[dict[str, Any]]:
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
                - file_id: Library file document ID
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
                SORT score DESC
                LIMIT @limit
                RETURN MERGE(doc, {{ score: score }})
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
                - file_id: Library file document ID
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
                SORT score DESC
                LIMIT @limit
                RETURN MERGE(doc, {{ score: score }})
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

        Args:
            file_id: Library file document ID.

        Returns:
            Number of documents deleted.

        """
        cursor = self.db.aql.execute(
            f"""
            FOR doc IN {self.collection_name}
                FILTER doc.file_id == @file_id
                REMOVE doc IN {self.collection_name}
                COLLECT WITH COUNT INTO removed
                RETURN removed
            """,
            bind_vars={"file_id": file_id},
        )
        results = list(cursor)  # type: ignore[arg-type]
        return cast("int", results[0]) if results else 0

    def delete_by_file_ids(self, file_ids: list[str]) -> int:
        """Bulk delete vector documents for multiple files from cold collection.

        Args:
            file_ids: List of library file document IDs.

        Returns:
            Number of documents deleted.

        """
        if not file_ids:
            return 0
        cursor = self.db.aql.execute(
            f"""
            FOR doc IN {self.collection_name}
                FILTER doc.file_id IN @file_ids
                REMOVE doc IN {self.collection_name}
                COLLECT WITH COUNT INTO removed
                RETURN removed
            """,
            bind_vars={"file_ids": file_ids},
        )
        results = list(cursor)  # type: ignore[arg-type]
        return cast("int", results[0]) if results else 0

    def truncate(self) -> None:
        """Remove all documents from cold collection.

        Used for testing and maintenance. Drops all promoted vectors.
        """
        self.collection.truncate()
