from __future__ import annotations

import logging
from typing import Any

from nomarr.persistence.aql import primitives
from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.schema import CollectionNames

Document = dict[str, Any]
_logger = logging.getLogger(__name__)


def _extract_key(document_id_or_key: str) -> str:
    return document_id_or_key.split("/", 1)[1] if "/" in document_id_or_key else document_id_or_key


class LibrariesAqlOperations:
    """Thin Tier 2 bindings for the ``libraries`` collection."""

    COLLECTION = CollectionNames.LIBRARIES.value
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
            "scan_state",
            "ml_state",
            "calibration_state",
            "tag_write_state",
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

    def update_pipeline_axis(self, library_id: str, axis_field: str, axis_value: str) -> None:
        """Update a single pipeline axis field on a library document."""
        primitives.update_document_by_key(
            self._db,
            self.COLLECTION,
            _extract_key(library_id),
            {axis_field: axis_value},
        )

    def get_pipeline_state(self, library_id: str) -> dict[str, str] | None:
        """Return the four pipeline axis values for a library, or None if not found."""
        lib = self.get_library(library_id)
        if lib is None:
            return None
        return {
            "scan_state": lib.get("scan_state", "not_scanned"),
            "ml_state": lib.get("ml_state", "not_ML_processed"),
            "calibration_state": lib.get("calibration_state", "not_calibrated"),
            "tag_write_state": lib.get("tag_write_state", "not_written"),
        }

    def get_libraries_in_axis_state(self, axis_field: str, axis_value: str) -> list[str]:
        """Return library document IDs where the given axis field matches the value."""
        cursor = self._db.aql.execute(
            """
            FOR doc IN @@collection
                FILTER doc[@field] == @value
                SORT doc._key
                RETURN doc._id
            """,
            bind_vars={
                "@collection": self.COLLECTION,
                "field": axis_field,
                "value": axis_value,
            },
        )
        return list(cursor)

    def remove_library(self, library_id: str) -> None:
        """Delete a library and all its associated data.

        File-level data is processed in batches of 250 so the AQL
        transaction size stays within ArangoDB limits for large libraries.
        Library-level data and orphaned tags are handled in single queries
        (their cardinality is independent of file count).
        """
        lib_key = _extract_key(library_id)
        normalized_id = f"{self.COLLECTION}/{lib_key}"
        # Local AQL collection name variables (derived from CollectionNames)
        lcf = CollectionNames.LIBRARY_CONTAINS_FILE.value  # library_contains_file
        fhe = CollectionNames.FILE_HAS_OUTPUT_STREAM.value  # file_has_output_stream
        ohs = CollectionNames.OUTPUT_HAS_STREAM.value  # output_has_stream
        fhv = CollectionNames.FILE_HAS_VECTORS.value  # file_has_vectors
        sht = CollectionNames.SONG_HAS_TAGS.value  # song_has_tags
        fhs = CollectionNames.FILE_HAS_STATE.value  # file_has_state
        wc = CollectionNames.WORKER_CLAIMS.value  # worker_claims
        mos = CollectionNames.ML_OUTPUT_STREAMS.value  # ml_output_streams
        lcf_ = CollectionNames.LIBRARY_CONTAINS_FOLDER.value  # library_contains_folder
        lfol = CollectionNames.LIBRARY_FOLDERS.value  # library_folders
        lhs = CollectionNames.LIBRARY_HAS_SCAN.value  # library_has_scan
        lsc = CollectionNames.LIBRARY_SCANS.value  # library_scans
        lhp = CollectionNames.LIBRARY_HAS_PIPELINE_STATE.value  # library_has_pipeline_state
        lps = CollectionNames.LIBRARY_PIPELINE_STATES.value  # library_pipeline_states
        lfi = CollectionNames.LIBRARY_FILES.value  # library_files
        tg = CollectionNames.TAGS.value  # tags

        # ── Query 1: all file-level derived data ───────────────────────────
        # Fetches file IDs for the library, then processes them in batches.
        # Each batch handles all dependent collections for its subset of files
        # in a single AQL transaction, keeping operation count within ArangoDB
        # limits for libraries with tens of thousands of files.
        file_cursor = self._db.aql.execute(
            f"""
            FOR e IN {lcf}
                FILTER e._from == @lib
                RETURN e._to
            """,
            bind_vars={"lib": normalized_id},
        )
        all_file_ids = list(file_cursor)
        batch_size = 250
        total_files = len(all_file_ids)

        _logger.info(
            "[remove_library] Deleting %d files in batches of %d from library %s",
            total_files,
            batch_size,
            lib_key,
        )

        _remove_file_batch = f"""
        LET stream_data = (
            FOR e IN {fhe}
                FILTER e._from IN @batch
                RETURN {{id: e._to, edge: e}}
        )
        LET stream_ids = stream_data[* RETURN CURRENT.id]
        LET stream_edges = stream_data[* RETURN CURRENT.edge]
        LET output_edges = (
            FOR e IN {ohs}
                FILTER e._to IN stream_ids
                RETURN e
        )
        FOR oe IN output_edges
            REMOVE oe IN {ohs} OPTIONS {{ ignoreErrors: true }}
        FOR sid IN stream_ids
            REMOVE sid IN {mos} OPTIONS {{ ignoreErrors: true }}
        FOR fse IN stream_edges
            REMOVE fse IN {fhe} OPTIONS {{ ignoreErrors: true }}
        FOR ve IN {fhv}
            FILTER ve._from IN @batch
            REMOVE ve IN {fhv} OPTIONS {{ ignoreErrors: true }}
        FOR te IN {sht}
            FILTER te._from IN @batch
            REMOVE te IN {sht} OPTIONS {{ ignoreErrors: true }}
        FOR c IN {wc}
            FILTER c.file_id IN @batch
            REMOVE c IN {wc} OPTIONS {{ ignoreErrors: true }}
        FOR se IN {fhs}
            FILTER se._from IN @batch
            REMOVE se IN {fhs} OPTIONS {{ ignoreErrors: true }}
        FOR fid IN @batch
            REMOVE fid IN {lfi} OPTIONS {{ ignoreErrors: true }}
        """

        for i in range(0, total_files, batch_size):
            batch = all_file_ids[i : i + batch_size]
            if i > 0 and i % (batch_size * 5) == 0:
                _logger.debug(
                    "[remove_library] Batch %d/%d (%d files processed so far)",
                    i // batch_size,
                    (total_files + batch_size - 1) // batch_size,
                    i,
                )
            self._db.aql.execute(
                _remove_file_batch,
                bind_vars={"batch": batch},
            )

        # ── Query 2: library-level data ────────────────────────────────────
        self._db.aql.execute(
            f"""
            LET folder_edges = (
                FOR e IN {lcf_}
                    FILTER e._from == @lib
                    RETURN e
            )
            LET scan_edges = (
                FOR e IN {lhs}
                    FILTER e._from == @lib
                    RETURN e
            )
            LET pipeline_edges = (
                FOR e IN {lhp}
                    FILTER e._from == @lib
                    RETURN e
            )
            FOR file_edge IN {lcf}
                FILTER file_edge._from == @lib
                REMOVE file_edge IN {lcf} OPTIONS {{ ignoreErrors: true }}
            FOR folder_target IN folder_edges
                REMOVE folder_target._to IN {lfol} OPTIONS {{ ignoreErrors: true }}
            FOR folder_edge IN folder_edges
                REMOVE folder_edge IN {lcf_} OPTIONS {{ ignoreErrors: true }}
            FOR scan_target IN scan_edges
                REMOVE scan_target._to IN {lsc} OPTIONS {{ ignoreErrors: true }}
            FOR scan_edge IN scan_edges
                REMOVE scan_edge IN {lhs} OPTIONS {{ ignoreErrors: true }}
            FOR pipeline_target IN pipeline_edges
                REMOVE pipeline_target._to IN {lps} OPTIONS {{ ignoreErrors: true }}
            FOR pipeline_edge IN pipeline_edges
                REMOVE pipeline_edge IN {lhp} OPTIONS {{ ignoreErrors: true }}
            REMOVE @lib_key IN {self.COLLECTION} OPTIONS {{ ignoreErrors: true }}
            """,
            bind_vars={"lib": normalized_id, "lib_key": lib_key},
        )

        # ── Orphaned tag documents ────────────────────────────────────────────
        # Tags that are no longer referenced by any song_has_tags edge.
        self._db.aql.execute(
            f"""
            FOR tag IN {tg}
                FILTER FIRST(FOR e IN {sht} FILTER e._to == tag._id LIMIT 1 RETURN 1) == null
                REMOVE tag IN {tg} OPTIONS {{ ignoreErrors: true }}
            """
        )
