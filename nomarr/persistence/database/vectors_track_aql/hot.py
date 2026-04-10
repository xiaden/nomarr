"""Hot vectors track operations for ArangoDB."""

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
                model_suite_hash: @model_suite_hash,
                embed_dim: @embed_dim,
                vector: @vector,
                vector_n: @vector_n,
                num_segments: @num_segments,
                created_at: @ts
            }}
            UPDATE {{
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
                    "model_suite_hash": model_suite_hash,
                    "embed_dim": embed_dim,
                    "vector": vector,
                    "vector_n": vector_n,
                    "num_segments": num_segments,
                    "ts": ts,
                },
            ),
        )

        # UPSERT the edge (file -> vector)
        vector_id = f"{collection_name}/{_key}"
        self.db.aql.execute(
            """
            UPSERT { _from: @file_id, _to: @vector_id }
            INSERT { _from: @file_id, _to: @vector_id }
            UPDATE {}
            IN file_has_vectors
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {"file_id": file_id, "vector_id": vector_id},
            ),
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_vector(self, file_id: str) -> dict[str, Any] | None:
        """Get the most recent vector document for a file from hot collection.

        Uses graph traversal via file_has_vectors edge collection.

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
        """Get vector documents for multiple files from hot collection.

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
    # Delete
    # ------------------------------------------------------------------

    def delete_by_file_id(self, file_id: str) -> int:
        """Delete all vector documents for a given file from hot collection.

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
        """Bulk delete vector documents for multiple files from hot collection.

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
