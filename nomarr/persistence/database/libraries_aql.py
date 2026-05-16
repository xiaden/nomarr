from __future__ import annotations

from typing import Any

from nomarr.persistence.aql import primitives
from nomarr.persistence.arango_client import SafeDatabase

Document = dict[str, Any]


def _extract_key(document_id_or_key: str) -> str:
    return document_id_or_key.split("/", 1)[1] if "/" in document_id_or_key else document_id_or_key


class LibrariesAqlOperations:
    """Thin Tier 2 bindings for the ``libraries`` collection."""

    COLLECTION = "libraries"
    ALLOWED_FIELDS = frozenset(
        {
            "name",
            "root_path",
            "is_enabled",
            "watch_mode",
            "file_write_mode",
            "library_auto_write",
            "created_at",
            "updated_at",
            "vector_group_size",
            "vector_search_thoroughness",
        },
    )

    def __init__(self, db: SafeDatabase) -> None:
        self._db = db

    def add_library(self, payload: dict[str, Any]) -> str:
        return primitives.insert_document(self._db, self.COLLECTION, payload)

    def get_library(self, library_id: str) -> Document | None:
        results = primitives.get_many_by_keys(self._db, self.COLLECTION, [_extract_key(library_id)])
        return results[0] if results else None

    def get_library_by_name(self, name: str) -> Document | None:
        results = primitives.get_many_by_field(
            self._db,
            self.COLLECTION,
            "name",
            name,
            limit=1,
            allowed_fields=self.ALLOWED_FIELDS,
        )
        return results[0] if results else None

    def list_libraries(self, *, enabled_only: bool = False) -> list[Document]:
        filters = {"is_enabled": True} if enabled_only else {}
        return primitives.get_filtered_docs(
            self._db,
            self.COLLECTION,
            filters=filters,
            sort_field="name",
            limit=None,
            allowed_fields=self.ALLOWED_FIELDS,
        )

    def list_library_keys(self) -> list[str]:
        cursor = self._db.aql.execute(
            """
            FOR doc IN @@collection
                SORT doc._key
                RETURN doc._key
            """,
            bind_vars={"@collection": self.COLLECTION},
        )
        return list(cursor)

    def update_library(self, library_id: str, fields: dict[str, Any]) -> None:
        primitives.update_document_by_key(self._db, self.COLLECTION, _extract_key(library_id), fields)

    def delete_library(self, library_id: str) -> None:
        primitives.delete_many_by_keys(self._db, self.COLLECTION, [_extract_key(library_id)])

    def remove_library(self, library_id: str) -> None:
        """Delete a library and all its associated data.

        Executes two AQL queries (each covering multiple collections via LET
        chaining), a Python loop for dynamically-named vector collections
        (AQL collection names must be static literals), and a final orphaned
        tag sweep.

        Collection names are hardcoded here; this method is the canonical,
        curated definition of what "remove a library" means at the persistence
        level.
        """
        lib_key = _extract_key(library_id)
        normalized_id = f"libraries/{lib_key}"

        # Part C keeps this flow in Tier 2 because it coordinates multi-collection
        # graph/path cleanup and vector lifecycle semantics, not a storage-generic
        # field delete shape.
        # ── Query 1: all file-level derived data ───────────────────────────
        # Collects file and stream IDs via LET, then removes each dependent
        # collection in order.  Each REMOVE targets a single collection.
        self._db.aql.execute(
            """
            LET file_ids = (
                FOR e IN library_contains_file
                    FILTER e._from == @lib
                    RETURN e._to
            )
            LET stream_ids = (
                FOR e IN file_has_output_stream
                    FILTER e._from IN file_ids
                    RETURN e._to
            )
            FOR e IN output_has_stream
                FILTER e._to IN stream_ids
                REMOVE e IN output_has_stream
            FOR sid IN stream_ids
                REMOVE sid IN ml_output_streams OPTIONS { ignoreErrors: true }
            FOR e IN file_has_output_stream
                FILTER e._from IN file_ids
                REMOVE e IN file_has_output_stream
            FOR e IN file_has_vectors
                FILTER e._from IN file_ids
                REMOVE e IN file_has_vectors
            FOR e IN song_has_tags
                FILTER e._from IN file_ids
                REMOVE e IN song_has_tags
            FOR c IN worker_claims
                FILTER c.file_id IN file_ids
                REMOVE c IN worker_claims
            FOR e IN file_has_state
                FILTER e._from IN file_ids
                REMOVE e IN file_has_state
            FOR fid IN file_ids
                REMOVE fid IN library_files OPTIONS { ignoreErrors: true }
            """,
            bind_vars={"lib": normalized_id},
        )

        # ── Query 2: library-level data ────────────────────────────────────
        self._db.aql.execute(
            """
            FOR e IN library_contains_file
                FILTER e._from == @lib
                REMOVE e IN library_contains_file
            FOR e IN library_contains_folder
                FILTER e._from == @lib
                REMOVE e._to IN library_folders OPTIONS { ignoreErrors: true }
            FOR e IN library_contains_folder
                FILTER e._from == @lib
                REMOVE e IN library_contains_folder
            FOR e IN library_has_scan
                FILTER e._from == @lib
                REMOVE e._to IN library_scans OPTIONS { ignoreErrors: true }
            FOR e IN library_has_scan
                FILTER e._from == @lib
                REMOVE e IN library_has_scan
            FOR e IN library_has_pipeline_state
                FILTER e._from == @lib
                REMOVE e._to IN library_pipeline_states OPTIONS { ignoreErrors: true }
            FOR e IN library_has_pipeline_state
                FILTER e._from == @lib
                REMOVE e IN library_has_pipeline_state
            REMOVE @lib_key IN libraries OPTIONS { ignoreErrors: true }
            """,
            bind_vars={"lib": normalized_id, "lib_key": lib_key},
        )

        # ── Per-library vector collections ─────────────────────────────────
        # Named vectors_track_*__{lib_key}.  Collection names are dynamic so
        # they cannot be referenced in AQL; discovered and deleted via the
        # DB API instead.
        suffix = f"__{lib_key}"
        for coll_meta in self._db.collections():
            name = coll_meta["name"]
            if name.startswith("vectors_track") and name.endswith(suffix):
                self._db.delete_collection(name, ignore_missing=True)

        # ── Orphaned tag documents ────────────────────────────────────────────
        # Tags that are no longer referenced by any song_has_tags edge.
        self._db.aql.execute(
            """
            FOR tag IN tags
                FILTER LENGTH(FOR e IN song_has_tags FILTER e._to == tag._id LIMIT 1 RETURN 1) == 0
                REMOVE tag IN tags
            """
        )
