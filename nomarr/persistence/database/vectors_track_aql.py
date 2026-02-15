"""Vectors track operations for ArangoDB.

Each backbone has its own collection named ``vectors_track__{backbone_id}``.
Documents store a pooled track-level embedding vector per file, keyed by
``sha1(file_id|model_suite_hash)``.
"""

import hashlib
from typing import Any, cast

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import DatabaseLike


class VectorsTrackOperations:
    """Operations for a single vectors_track__{backbone} collection."""

    def __init__(self, db: DatabaseLike, backbone_id: str) -> None:
        self.db = db
        self.backbone_id = backbone_id
        self.collection_name = f"vectors_track__{backbone_id}"
        self.collection = db.collection(self.collection_name)

    @staticmethod
    def _make_key(file_id: str, model_suite_hash: str) -> str:
        """Build a deterministic ArangoDB-safe ``_key``.

        Backbone identity is encoded in the collection name, so only
        ``file_id`` and ``model_suite_hash`` contribute to the key.
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
        """Upsert a track-level embedding vector.

        Uses atomic AQL UPSERT to handle parallel workers safely.

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

        self.db.aql.execute(
            f"""
            UPSERT {{ _key: @_key }}
            INSERT {{
                _key: @_key,
                file_id: @file_id,
                model_suite_hash: @model_suite_hash,
                embed_dim: @embed_dim,
                vector: @vector,
                num_segments: @num_segments,
                created_at: @ts
            }}
            UPDATE {{
                file_id: @file_id,
                model_suite_hash: @model_suite_hash,
                embed_dim: @embed_dim,
                vector: @vector,
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
                    "num_segments": num_segments,
                    "ts": ts,
                },
            ),
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_vector(self, file_id: str) -> dict[str, Any] | None:
        """Get the most recent vector document for a file.

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
        """Get vector documents for multiple files.

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
        """Delete all vector documents for a given file.

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
        """Bulk delete vector documents for multiple files.

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
        """Remove all documents from this vectors_track collection."""
        self.collection.truncate()
