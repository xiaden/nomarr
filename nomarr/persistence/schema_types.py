"""Shared schema-era types and runtime vector namespace helpers."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import SafeDatabase

if TYPE_CHECKING:
    from arango.collection import StandardCollection

_FIELD_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_VECTOR_EDGE_COLLECTION = "file_has_vectors"
_VECTOR_ALLOWED_FIELDS = frozenset(
    {
        "_id",
        "_key",
        "file_id",
        "model_suite_hash",
        "embed_dim",
        "vector",
        "vector_n",
        "num_segments",
        "created_at",
        "genres",
    }
)


class CollectionType(StrEnum):
    """Types of ArangoDB collections."""

    DOCUMENT = "document"
    EDGE = "edge"
    STATE_GRAPH = "state_graph"
    TEMPLATE = "template"
    INFRASTRUCTURE = "infrastructure"


class SchemaValidationError(RuntimeError):
    """Raised when legacy schema declarations are internally inconsistent."""


class CapabilityError(RuntimeError):
    """Raised when a legacy namespace method is called without the required capability."""


@dataclass(frozen=True, slots=True)
class Field:
    """Field/value pair used by the remaining collection-first helper calls."""

    name: str
    value: Any


@dataclass(frozen=True, slots=True)
class UniqueField(Field):
    """Marker subtype for callers that conceptually target a unique field."""


def _validate_field_name(field_name: str) -> None:
    if not _FIELD_NAME_RE.match(field_name):
        msg = f"Invalid field name {field_name!r}"
        raise ValueError(msg)


def _as_document_id(collection: str, document_id_or_key: str) -> str:
    return document_id_or_key if "/" in document_id_or_key else f"{collection}/{document_id_or_key}"


class _VectorGetAccessor:
    def __init__(self, owner: VectorCollection) -> None:
        self._owner = owner

    def in_(self, field: Field, *, limit: int | None = None) -> list[dict[str, Any]]:
        return self._owner._get_many_by_field(field.name, field.value, limit=limit)


class _VectorFieldDelete:
    def __init__(self, owner: VectorCollection, field_name: str) -> None:
        self._owner = owner
        self._field_name = field_name

    def __call__(self, value: Any) -> int:
        return self._owner._delete_by_field(self._field_name, value)

    def in_(self, values: list[Any]) -> int:
        return self._owner._delete_by_field_in(self._field_name, values)


class _VectorFieldDeleteAccessor:
    def __init__(self, owner: VectorCollection, field_name: str) -> None:
        self.delete = _VectorFieldDelete(owner, field_name)


class VectorCollection:
    """Runtime-bound namespace for a registered vector collection."""

    NAME_PATTERN = "vectors_track"
    EDGE_COLLECTION = _VECTOR_EDGE_COLLECTION

    def __init__(self, db: SafeDatabase, name: str) -> None:
        self._db = db
        self._name = name
        self.collection: StandardCollection = db.collection(name)
        self.get = _VectorGetAccessor(self)
        self.file_id = _VectorFieldDeleteAccessor(self, "file_id")

    @staticmethod
    def _make_vector_key(file_id: str, model_suite_hash: str) -> str:
        return hashlib.sha1(f"{file_id}|{model_suite_hash}".encode()).hexdigest()

    @staticmethod
    def _normalize_vector(vector: list[float]) -> list[float]:
        norm = math.sqrt(math.fsum(value * value for value in vector))
        return [value / norm for value in vector] if norm > 0.0 else list(vector)

    def count(self) -> int:
        return cast("int", self.collection.count())

    def truncate(self) -> None:
        self.collection.truncate()

    def aggregate(self, field_name: str, *, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        _validate_field_name(field_name)
        if field_name not in _VECTOR_ALLOWED_FIELDS:
            msg = f"Field {field_name!r} is not allowed for vector aggregation"
            raise ValueError(msg)
        limit_clause = "LIMIT @offset, @limit" if limit is not None else ""
        bind_vars: dict[str, Any] = {
            "@collection": self._name,
            "field_name": field_name,
        }
        if limit is not None:
            bind_vars["offset"] = offset
            bind_vars["limit"] = limit
        cursor = self._db.aql.execute(
            f"""
            FOR doc IN @@collection
                SORT doc[@field_name] ASC
                {limit_clause}
                RETURN {{ value: doc[@field_name] }}
            """,
            bind_vars=bind_vars,
        )
        return cast("list[dict[str, Any]]", list(cursor))

    def upsert(self, *, _key: str, fields: dict[str, Any]) -> list[str]:
        payload = dict(fields)
        cursor = self._db.aql.execute(
            """
            UPSERT { _key: @_key }
                INSERT MERGE(@fields, { _key: @_key })
                UPDATE @fields
                IN @@collection
                RETURN NEW._id
            """,
            bind_vars={"@collection": self._name, "_key": _key, "fields": payload},
        )
        return [str(value) for value in cursor]

    def update_many(self, docs: list[dict[str, Any]]) -> None:
        if not docs:
            return
        cast("Any", self.collection).update_many(docs)

    def move_collection(self, dest: str) -> int:
        from nomarr.persistence.constructor import verbs

        return cast("int", verbs.move_collection(self._db, self._name, dest))

    def get_vector(self, file_id: str) -> dict[str, Any] | None:
        cursor = self._db.aql.execute(
            """
            FOR vec IN OUTBOUND @file_id @@edge_collection
                FILTER IS_SAME_COLLECTION(@collection, vec)
                SORT vec.created_at DESC
                LIMIT 1
                RETURN MERGE(vec, { file_id: @file_id })
            """,
            bind_vars={
                "@edge_collection": self.EDGE_COLLECTION,
                "collection": self._name,
                "file_id": _as_document_id("library_files", file_id),
            },
        )
        results = list(cursor)
        return cast("dict[str, Any]", results[0]) if results else None

    def get_vectors_by_file_ids(self, file_ids: list[str]) -> list[dict[str, Any]]:
        normalized_file_ids = [_as_document_id("library_files", file_id) for file_id in file_ids]
        if not normalized_file_ids:
            return []
        cursor = self._db.aql.execute(
            """
            FOR file_id IN @file_ids
                FOR vec IN OUTBOUND file_id @@edge_collection
                    FILTER IS_SAME_COLLECTION(@collection, vec)
                    RETURN MERGE(vec, { file_id: file_id })
            """,
            bind_vars={
                "@edge_collection": self.EDGE_COLLECTION,
                "collection": self._name,
                "file_ids": normalized_file_ids,
            },
        )
        return cast("list[dict[str, Any]]", list(cursor))

    def _get_many_by_field(self, field_name: str, values: Any, *, limit: int | None = None) -> list[dict[str, Any]]:
        _validate_field_name(field_name)
        if field_name not in _VECTOR_ALLOWED_FIELDS:
            msg = f"Field {field_name!r} is not allowed for vector reads"
            raise ValueError(msg)
        value_list = values if isinstance(values, list) else [values]
        limit_clause = "LIMIT @limit" if limit is not None else ""
        bind_vars: dict[str, Any] = {
            "@collection": self._name,
            "field_name": field_name,
            "values": value_list,
        }
        if limit is not None:
            bind_vars["limit"] = limit
        cursor = self._db.aql.execute(
            f"""
            FOR doc IN @@collection
                FILTER doc[@field_name] IN @values
                {limit_clause}
                RETURN doc
            """,
            bind_vars=bind_vars,
        )
        return cast("list[dict[str, Any]]", list(cursor))

    def _delete_by_field(self, field_name: str, value: Any) -> int:
        return self._delete_by_field_in(field_name, [value])

    def _delete_by_field_in(self, field_name: str, values: list[Any]) -> int:
        _validate_field_name(field_name)
        normalized_values = [
            _as_document_id("library_files", value) if field_name == "file_id" and isinstance(value, str) else value
            for value in values
        ]
        if not normalized_values:
            return 0
        cursor = self._db.aql.execute(
            """
            FOR doc IN @@collection
                FILTER doc[@field_name] IN @values
                REMOVE doc IN @@collection
                RETURN 1
            """,
            bind_vars={
                "@collection": self._name,
                "field_name": field_name,
                "values": normalized_values,
            },
        )
        return len(list(cursor))


class VectorsTrackHot(VectorCollection):
    """Runtime namespace template for hot per-library vector collections."""

    NAME_PATTERN = "vectors_track_hot__{backbone_id}__{library_key}"

    def upsert_vector(
        self,
        file_id: str,
        model_suite_hash: str,
        embed_dim: int,
        vector: list[float],
        num_segments: int,
    ) -> None:
        file_doc_id = _as_document_id("library_files", file_id)
        vector_key = self._make_vector_key(file_doc_id, model_suite_hash)
        payload = {
            "file_id": file_doc_id,
            "model_suite_hash": model_suite_hash,
            "embed_dim": embed_dim,
            "vector": list(vector),
            "vector_n": self._normalize_vector(vector),
            "num_segments": num_segments,
            "created_at": now_ms().value,
        }
        vector_ids = self.upsert(_key=vector_key, fields=payload)
        if not vector_ids:
            msg = f"Vector upsert returned no ids for collection {self._name!r}"
            raise RuntimeError(msg)
        self._db.aql.execute(
            """
            UPSERT { _from: @file_id, _to: @vector_id }
                INSERT { _from: @file_id, _to: @vector_id }
                UPDATE {}
                IN @@edge_collection
            """,
            bind_vars={
                "@edge_collection": self.EDGE_COLLECTION,
                "file_id": file_doc_id,
                "vector_id": vector_ids[0],
            },
        )


class VectorsTrackCold(VectorCollection):
    """Runtime namespace template for cold per-library vector collections."""

    NAME_PATTERN = "vectors_track_cold__{backbone_id}__{library_key}"

    def ann_search(
        self,
        vector: list[float],
        limit: int,
        nprobe: int = 10,
        *,
        filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        genre_filter = None
        if filter is not None:
            genre_filter = filter.get("genres")
            if genre_filter is not None and not isinstance(genre_filter, str):
                msg = "Cold vector genre filter must be a string when provided"
                raise ValueError(msg)
        cursor = self._db.aql.execute(
            """
            FOR doc IN @@collection
                FILTER @genre == null OR @genre IN doc.genres
                LET score = APPROX_NEAR_COSINE(doc.vector_n, @query_vector, { nProbe: @nprobe })
                LET file_id = FIRST(
                    FOR file IN INBOUND doc @@edge_collection
                        RETURN file._id
                )
                SORT score DESC
                LIMIT @limit
                RETURN MERGE(doc, { score: score, file_id: file_id })
            """,
            bind_vars={
                "@collection": self._name,
                "@edge_collection": self.EDGE_COLLECTION,
                "genre": genre_filter,
                "query_vector": vector,
                "nprobe": nprobe,
                "limit": limit,
            },
        )
        return cast("list[dict[str, Any]]", list(cursor))


__all__ = [
    "CapabilityError",
    "CollectionType",
    "Field",
    "SchemaValidationError",
    "UniqueField",
    "VectorCollection",
    "VectorsTrackCold",
    "VectorsTrackHot",
]
