from __future__ import annotations

from typing import Any, cast

from nomarr.persistence.aql import primitives
from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.schema_types import VectorCollection, VectorsTrackCold, VectorsTrackHot

Document = dict[str, Any]

_VECTOR_TEMPLATE_CLASSES: dict[str, type[VectorCollection]] = {
    VectorsTrackHot.NAME_PATTERN.split("__{", maxsplit=1)[0]: VectorsTrackHot,
    VectorsTrackCold.NAME_PATTERN.split("__{", maxsplit=1)[0]: VectorsTrackCold,
}
_VECTOR_ALLOWED_FIELDS = frozenset(
    {
        "file_id",
        "model_suite_hash",
        "embed_dim",
        "vector",
        "vector_n",
        "num_segments",
        "created_at",
    },
)


def _as_document_id(collection: str, document_id_or_key: str) -> str:
    return document_id_or_key if "/" in document_id_or_key else f"{collection}/{document_id_or_key}"


def _matches_name_pattern(collection_name: str, pattern: str) -> bool:
    prefix = pattern.split("__{", maxsplit=1)[0]
    return collection_name == prefix or collection_name.startswith(prefix + "__")


class VectorsAqlOperations:
    """Thin Tier 2 bindings for runtime vector collections."""

    EDGE_COLLECTION = "file_has_vectors"

    def __init__(self, db: SafeDatabase) -> None:
        self._db = db
        self._registered_namespaces: dict[str, VectorCollection] = {}

    def register_vector_collection(self, name: str, template: str) -> VectorCollection:
        existing = self._registered_namespaces.get(name)
        if existing is not None:
            return existing
        if not self._db.has_collection(name):
            raise ValueError(f"Collection {name!r} does not exist in ArangoDB")
        vector_template_cls = _VECTOR_TEMPLATE_CLASSES.get(template)
        if vector_template_cls is None:
            raise ValueError(f"{template!r} is not a supported template collection")
        if not _matches_name_pattern(name, vector_template_cls.NAME_PATTERN):
            msg = f"Collection {name!r} does not match template pattern {vector_template_cls.NAME_PATTERN!r}"
            raise ValueError(msg)
        namespace = vector_template_cls(self._db, name)
        self._registered_namespaces[name] = namespace
        return namespace

    def list_registered_vector_collection_names(self) -> list[str]:
        return sorted(self._registered_namespaces)

    def list_registered_vector_namespaces(self) -> dict[str, Any]:
        return cast("dict[str, Any]", dict(self._registered_namespaces))

    def truncate_vector_collection(self, collection_name: str) -> None:
        if collection_name not in self._registered_namespaces:
            msg = f"Collection {collection_name!r} is not a registered vector collection"
            raise ValueError(msg)
        self._truncate_collection(collection_name)

    def truncate_vector_edges(self) -> None:
        self._truncate_collection(self.EDGE_COLLECTION)

    def get_file_vectors(self, collection_name: str, file_id: str) -> list[Document]:
        return primitives.get_many_by_field(
            self._db,
            collection_name,
            "file_id",
            _as_document_id("library_files", file_id),
            limit=None,
            allowed_fields=_VECTOR_ALLOWED_FIELDS,
        )

    def upsert_vector(self, collection_name: str, payload: dict[str, Any]) -> None:
        vector_payload = dict(payload)
        vector_key = vector_payload.get("_key")
        file_id = vector_payload.get("file_id")
        model_suite_hash = vector_payload.get("model_suite_hash")
        raw_vector = vector_payload.get("vector")

        if not isinstance(vector_key, str) or not vector_key:
            if isinstance(file_id, str) and isinstance(model_suite_hash, str):
                vector_key = VectorCollection._make_vector_key(file_id, model_suite_hash)
                vector_payload["_key"] = vector_key
            else:
                msg = "Vector payload must include '_key' or both 'file_id' and 'model_suite_hash'"
                raise ValueError(msg)

        if isinstance(raw_vector, list) and "vector_n" not in vector_payload:
            vector_payload["vector_n"] = VectorCollection._normalize_vector(cast("list[float]", raw_vector))

        cursor = self._db.aql.execute(
            """
            UPSERT { _key: @vector_key }
                INSERT MERGE(@payload, { _key: @vector_key })
                UPDATE @payload
                IN @@collection
                RETURN NEW._id
            """,
            bind_vars={"@collection": collection_name, "vector_key": vector_key, "payload": vector_payload},
        )
        results = list(cursor)
        vector_id = cast("str", results[0])

        if isinstance(file_id, str) and file_id:
            self.upsert_file_has_vector_edge(file_id, vector_id)

    def upsert_file_has_vector_edge(self, file_id: str, vector_id: str) -> None:
        self._db.aql.execute(
            """
            UPSERT { _from: @file_id, _to: @vector_id }
                INSERT { _from: @file_id, _to: @vector_id }
                UPDATE {}
                IN @@collection
            """,
            bind_vars={
                "@collection": self.EDGE_COLLECTION,
                "file_id": _as_document_id("library_files", file_id),
                "vector_id": vector_id,
            },
        )

    def delete_vectors_for_file(self, collection_name: str, file_id: str) -> None:
        """Delete vector documents and their edges for a file.

        Removes vector documents from ``collection_name`` whose ``file_id`` matches,
        then removes the corresponding ``file_has_vectors`` edges in a single AQL pass.

        Args:
            collection_name: Name of the vector collection to delete from.
            file_id: File document ID or ``_key``.
        """
        # Part C keeps this handwritten because vector-document deletion must stay
        # paired with vector-edge cleanup, which is vector-lifecycle logic, not Tier 1.
        self._db.aql.execute(
            """
            LET vector_ids = (
                FOR doc IN @@collection
                    FILTER doc.file_id == @file_id
                    RETURN doc._id
            )
            FOR edge IN @@edge_collection
                FILTER edge._from == @file_id AND edge._to IN vector_ids
                REMOVE edge IN @@edge_collection
            FOR vector_id IN vector_ids
                REMOVE vector_id IN @@collection
                OPTIONS { ignoreErrors: true }
            """,
            bind_vars={
                "@collection": collection_name,
                "@edge_collection": self.EDGE_COLLECTION,
                "file_id": _as_document_id("library_files", file_id),
            },
        )

    def delete_file_has_vector_edges_for_file(self, file_id: str) -> int:
        cursor = self._db.aql.execute(
            """
            FOR edge IN @@collection
                FILTER edge._from == @file_id
                REMOVE edge IN @@collection
                RETURN 1
            """,
            bind_vars={
                "@collection": self.EDGE_COLLECTION,
                "file_id": _as_document_id("library_files", file_id),
            },
        )
        return len(list(cursor))

    def delete_file_has_vector_edges_for_files(self, file_ids: list[str]) -> int:
        normalized_file_ids = [_as_document_id("library_files", file_id) for file_id in file_ids]
        if not normalized_file_ids:
            return 0
        cursor = self._db.aql.execute(
            """
            FOR edge IN @@collection
                FILTER edge._from IN @file_ids
                REMOVE edge IN @@collection
                RETURN 1
            """,
            bind_vars={"@collection": self.EDGE_COLLECTION, "file_ids": normalized_file_ids},
        )
        return len(list(cursor))

    def vector_search(self, collection_name: str, query_vector: list[float], *, limit: int) -> list[Document]:
        return primitives.execute(
            self._db,
            """
            FOR doc IN @@collection
                LET score = APPROX_NEAR_COSINE(doc.vector_n, @query_vector, { nProbe: @nprobe })
                LET file_id = FIRST(
                    FOR file IN INBOUND doc @@edge_collection
                        RETURN file._id
                )
                SORT score DESC
                LIMIT @limit
                RETURN MERGE(doc, { score: score, file_id: file_id })
            """,
            {
                "@collection": collection_name,
                "@edge_collection": self.EDGE_COLLECTION,
                "query_vector": query_vector,
                "nprobe": 20,
                "limit": limit,
            },
        )

    def _truncate_collection(self, collection_name: str) -> None:
        self._db.aql.execute(
            """
            FOR doc IN @@collection
                REMOVE doc IN @@collection
            """,
            bind_vars={"@collection": collection_name},
        )

    # ------------------------------------------------------------------ #
    # High-level embedding index operations                                #
    # These are the only methods callers need to make vectors searchable.  #
    # The hot/cold split is an implementation detail of this layer.        #
    # ------------------------------------------------------------------ #

    def _hot_name(self, backbone_id: str, library_key: str) -> str:
        return f"vectors_track_hot__{backbone_id}__{library_key}"

    def _cold_name(self, backbone_id: str, library_key: str) -> str:
        return f"vectors_track_cold__{backbone_id}__{library_key}"

    def _drop_cold_index(self, cold_name: str) -> None:
        if not self._db.has_collection(cold_name):
            return
        cold_col = cast("Any", self._db.collection(cold_name))
        for idx in cast("list[dict[str, Any]]", cold_col.indexes()):
            if idx.get("type") == "vector" and idx.get("id"):
                cold_col.delete_index(idx["id"])

    def _build_cold_index(self, cold_name: str, embed_dim: int, nlists: int) -> None:
        if not self._db.has_collection(cold_name):
            msg = f"Cold collection '{cold_name}' does not exist"
            raise ValueError(msg)
        cold_col = cast("Any", self._db.collection(cold_name))
        cold_col.add_index(
            {
                "type": "vector",
                "fields": ["vector_n"],
                "params": {"metric": "cosine", "dimension": embed_dim, "nLists": nlists},
                "storedValues": ["genres"],
            }
        )

    def get_embedding_stats(self, backbone_id: str, library_key: str) -> dict[str, int | bool]:
        """Return hot count, cold count, and whether the cold index exists."""
        hot_name = self._hot_name(backbone_id, library_key)
        cold_name = self._cold_name(backbone_id, library_key)

        hot_count = 0
        if self._db.has_collection(hot_name):
            hot_count = cast("int", self._db.collection(hot_name).count())

        cold_count = 0
        index_exists = False
        if self._db.has_collection(cold_name):
            cold_col = cast("Any", self._db.collection(cold_name))
            cold_count = cast("int", cold_col.count())
            index_exists = any(idx.get("type") == "vector" for idx in cast("list[dict[str, Any]]", cold_col.indexes()))

        return {"hot_count": hot_count, "cold_count": cold_count, "index_exists": index_exists}

    def has_embedding_index(self, backbone_id: str, library_key: str) -> bool:
        """Return True if the cold collection has an ANN vector index."""
        return bool(self.get_embedding_stats(backbone_id, library_key)["index_exists"])

    def index_library_embeddings(self, backbone_id: str, library_key: str, embed_dim: int, nlists: int) -> int:
        """Drain hot vectors to cold and build ANN index.

        Idempotent: if hot is already empty and the cold index exists, returns 0
        immediately without touching the database.

        Args:
            backbone_id: Backbone identifier (e.g. ``"discogs_effnet"``).
            library_key: ArangoDB ``_key`` of the library document.
            embed_dim: Embedding dimension (from the ONNX model).
            nlists: Number of Voronoi cells for the HNSW index.

        Returns:
            Number of documents drained from hot to cold.

        Raises:
            RuntimeError: If hot is not empty after drain.
        """
        hot_name = self._hot_name(backbone_id, library_key)
        cold_name = self._cold_name(backbone_id, library_key)

        stats = self.get_embedding_stats(backbone_id, library_key)
        hot_count = int(stats["hot_count"])
        index_exists = bool(stats["index_exists"])

        if hot_count == 0 and index_exists:
            return 0

        # Drop existing index before drain (keeps memory usage bounded)
        if index_exists:
            self._drop_cold_index(cold_name)

        # Drain hot → cold via move_collection (handles edge re-pointing + truncate)
        if hot_count > 0:
            if hot_name not in self._registered_namespaces:
                self.register_vector_collection(hot_name, "vectors_track_hot")
            hot_ops = self._registered_namespaces[hot_name]
            # Ensure the cold collection exists before the UPSERT in move_collection
            if not self._db.has_collection(cold_name):
                self._db.create_collection(cold_name)
            drained = cast("int", hot_ops.move_collection(cold_name))
            self.register_vector_collection(cold_name, "vectors_track_cold")

            remaining = cast("int", cast("Any", self._db.collection(hot_name)).count())
            if remaining > 0:
                raise RuntimeError(f"Hot collection '{hot_name}' not empty after drain: {remaining} documents remain.")
        else:
            drained = 0

        self._build_cold_index(cold_name, embed_dim, nlists)
        return drained

    def rebuild_library_embedding_index(self, backbone_id: str, library_key: str, embed_dim: int, nlists: int) -> None:
        """Drop and rebuild the ANN index without draining hot.

        Use when cold data is already complete and only index parameters
        need updating (e.g., after a full re-index or nlists tuning).

        Args:
            backbone_id: Backbone identifier.
            library_key: ArangoDB ``_key`` of the library document.
            embed_dim: Embedding dimension.
            nlists: Number of Voronoi cells for the HNSW index.
        """
        cold_name = self._cold_name(backbone_id, library_key)
        self._drop_cold_index(cold_name)
        self._build_cold_index(cold_name, embed_dim, nlists)
