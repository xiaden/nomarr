"""File state edge operations for ArangoDB.

CRUD operations on the ``file_has_state`` edge collection which connects
``library_files/*`` vertices to ``file_states/*`` state vertices.

Edge presence = file has reached that processing stage.
Edge absence  = file still needs processing.

State vertices (fixed, created by migration V016):
    ``file_states/ml_tagged``   — ML tagging complete
    ``file_states/calibrated``  — Calibration applied
    ``file_states/reconciled``  — Tags written to disk

Edge attribute schemas:
    ml_tagged:   ``{version: str, tagged_at: int}``
    calibrated:  ``{hash: str, calibrated_at: int}``
    reconciled:  ``{mode: str, calibration_hash: str|null, written_at: int, has_namespace: bool}``
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from arango.cursor import Cursor

_EDGE_COLLECTION = "file_has_state"
_STATE_ML_TAGGED = "file_states/ml_tagged"
_STATE_CALIBRATED = "file_states/calibrated"
_STATE_RECONCILED = "file_states/reconciled"


class FileStatesOperations:
    """CRUD operations for the file_has_state edge collection."""

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db
        self.collection = db.collection(_EDGE_COLLECTION)  # type: ignore[union-attr]

    # ------------------------------------------------------------------
    # ML Tagged state
    # ------------------------------------------------------------------

    def set_ml_tagged(self, file_id: str, version: str, tagged_at: int | None = None) -> None:
        """Upsert the ml_tagged edge for a file.

        Creates the edge if absent, updates attributes if present.

        Args:
            file_id: Document _id (e.g., ``library_files/12345``).
            version: Model version string.
            tagged_at: Timestamp in ms (defaults to now).
        """
        if tagged_at is None:
            tagged_at = now_ms().value
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            UPSERT { _from: @file_id, _to: @state }
            INSERT { _from: @file_id, _to: @state, version: @version, tagged_at: @tagged_at }
            UPDATE { version: @version, tagged_at: @tagged_at }
            IN @@coll
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "file_id": file_id,
                    "state": _STATE_ML_TAGGED,
                    "version": version,
                    "tagged_at": tagged_at,
                    "@coll": _EDGE_COLLECTION,
                },
            ),
        )

    def clear_ml_tagged(self, file_id: str) -> None:
        """Remove the ml_tagged edge for a file (marks it as needing re-tagging).

        Args:
            file_id: Document _id.
        """
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR edge IN @@coll
                FILTER edge._from == @file_id AND edge._to == @state
                REMOVE edge IN @@coll
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {"file_id": file_id, "state": _STATE_ML_TAGGED, "@coll": _EDGE_COLLECTION},
            ),
        )

    def is_ml_tagged(self, file_id: str) -> bool:
        """Check if a file has been ML tagged.

        Args:
            file_id: Document _id.

        Returns:
            True if the ml_tagged edge exists.
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR edge IN @@coll
                    FILTER edge._from == @file_id AND edge._to == @state
                    LIMIT 1
                    RETURN true
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {"file_id": file_id, "state": _STATE_ML_TAGGED, "@coll": _EDGE_COLLECTION},
                ),
            ),
        )
        return bool(next(cursor, False))

    def get_ml_tagged(self, file_id: str) -> dict[str, Any] | None:
        """Get ml_tagged edge attributes for a file.

        Args:
            file_id: Document _id.

        Returns:
            Dict with ``version`` and ``tagged_at``, or None if not tagged.
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR edge IN @@coll
                    FILTER edge._from == @file_id AND edge._to == @state
                    RETURN { version: edge.version, tagged_at: edge.tagged_at }
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {"file_id": file_id, "state": _STATE_ML_TAGGED, "@coll": _EDGE_COLLECTION},
                ),
            ),
        )
        return next(cursor, None)  # type: ignore[arg-type]

    def get_untagged_file_ids(
        self,
        library_id: str | None = None,
        limit: int = 100,
    ) -> list[str]:
        """Get IDs of files without the ml_tagged edge.

        Args:
            library_id: Restrict to a single library (None = all libraries).
            limit: Maximum number of IDs to return.

        Returns:
            List of file ``_id`` values needing tagging.
        """
        library_filter = "FILTER file.library_id == @library_id" if library_id else ""
        query = f"""
            FOR file IN library_files
                {library_filter}
                LET has_state = LENGTH(
                    FOR edge IN @@coll
                        FILTER edge._from == file._id AND edge._to == @state
                        LIMIT 1
                        RETURN 1
                )
                FILTER has_state == 0
                SORT file._key
                LIMIT @limit
                RETURN file._id
        """
        bind_vars: dict[str, Any] = {
            "state": _STATE_ML_TAGGED,
            "@coll": _EDGE_COLLECTION,
            "limit": limit,
        }
        if library_id:
            bind_vars["library_id"] = library_id

        cursor = cast(
            "Cursor",
            self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)),  # type: ignore[union-attr]
        )
        return list(cursor)

    def library_has_tagged_files(self, library_id: str) -> bool:
        """Check if any file in a library has the ml_tagged edge.

        Args:
            library_id: Library document _id.

        Returns:
            True if at least one file in the library is ml_tagged.
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR file IN library_files
                    FILTER file.library_id == @library_id
                    FOR edge IN @@coll
                        FILTER edge._from == file._id AND edge._to == @state
                        LIMIT 1
                        RETURN true
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "library_id": library_id,
                        "state": _STATE_ML_TAGGED,
                        "@coll": _EDGE_COLLECTION,
                    },
                ),
            ),
        )
        return bool(next(cursor, False))

    # ------------------------------------------------------------------
    # Calibration state
    # ------------------------------------------------------------------

    def set_calibrated(
        self, file_id: str, calibration_hash: str, calibrated_at: int | None = None
    ) -> None:
        """Upsert the calibrated edge for a file.

        Args:
            file_id: Document _id.
            calibration_hash: Global calibration version hash.
            calibrated_at: Timestamp in ms (defaults to now).
        """
        if calibrated_at is None:
            calibrated_at = now_ms().value
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            UPSERT { _from: @file_id, _to: @state }
            INSERT { _from: @file_id, _to: @state, hash: @hash, calibrated_at: @calibrated_at }
            UPDATE { hash: @hash, calibrated_at: @calibrated_at }
            IN @@coll
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "file_id": file_id,
                    "state": _STATE_CALIBRATED,
                    "hash": calibration_hash,
                    "calibrated_at": calibrated_at,
                    "@coll": _EDGE_COLLECTION,
                },
            ),
        )

    def set_calibrated_batch(self, items: list[tuple[str, str]]) -> None:
        """Upsert calibrated edges for multiple files in a single AQL query.

        Args:
            items: List of ``(file_id, calibration_hash)`` tuples.
        """
        if not items:
            return
        ts = now_ms().value
        docs = [
            {"_from": file_id, "_to": _STATE_CALIBRATED, "hash": h, "calibrated_at": ts}
            for file_id, h in items
        ]
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR doc IN @docs
                UPSERT { _from: doc._from, _to: doc._to }
                INSERT doc
                UPDATE { hash: doc.hash, calibrated_at: doc.calibrated_at }
                IN @@coll
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {"docs": docs, "@coll": _EDGE_COLLECTION},
            ),
        )

    def clear_calibrated(self, file_id: str) -> None:
        """Remove the calibrated edge for a file.

        Args:
            file_id: Document _id.
        """
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR edge IN @@coll
                FILTER edge._from == @file_id AND edge._to == @state
                REMOVE edge IN @@coll
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {"file_id": file_id, "state": _STATE_CALIBRATED, "@coll": _EDGE_COLLECTION},
            ),
        )

    def clear_all_calibrated(self) -> int:
        """Remove all calibrated edges.

        Used when clearing calibration data to mark all files as needing
        recalibration.

        Returns:
            Number of edges removed.
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR edge IN @@coll
                    FILTER edge._to == @state
                    REMOVE edge IN @@coll
                    COLLECT WITH COUNT INTO cnt
                    RETURN cnt
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {"state": _STATE_CALIBRATED, "@coll": _EDGE_COLLECTION},
                ),
            ),
        )
        return next(cursor, 0)  # type: ignore[arg-type]

    def get_calibration_status_by_library(self, expected_hash: str) -> list[dict[str, Any]]:
        """Get calibration status counts grouped by library.

        Returns count of files with current calibration hash vs outdated/missing.

        Args:
            expected_hash: Expected global calibration version hash.

        Returns:
            List of ``{library_id, total_files, current_count, outdated_count}``.
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR file IN library_files
                    LET cal_edge = FIRST(
                        FOR edge IN @@coll
                            FILTER edge._from == file._id AND edge._to == @state
                            RETURN edge
                    )
                    COLLECT lib = file.library_id
                    AGGREGATE
                        total = COUNT(1),
                        current = SUM(cal_edge != null AND cal_edge.hash == @expected_hash ? 1 : 0),
                        outdated = SUM(cal_edge == null OR cal_edge.hash != @expected_hash ? 1 : 0)
                    RETURN {
                        library_id: lib,
                        total_files: total,
                        current_count: current,
                        outdated_count: outdated
                    }
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "state": _STATE_CALIBRATED,
                        "expected_hash": expected_hash,
                        "@coll": _EDGE_COLLECTION,
                    },
                ),
            ),
        )
        return list(cursor)

    # ------------------------------------------------------------------
    def get_tagged_paths_needing_calibration(self, calibration_hash: str) -> list[str]:
        """Get paths of tagged files whose DB mood tags are stale.

        Finds files with an ``ml_tagged`` edge but no ``calibrated`` edge
        matching the expected hash.

        Args:
            calibration_hash: The current global calibration version.

        Returns:
            List of file paths needing mood tag recomputation.
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
            FOR file IN library_files
                LET has_tagged = LENGTH(
                    FOR edge IN @@coll
                        FILTER edge._from == file._id AND edge._to == @ml_tagged_state
                        LIMIT 1
                        RETURN 1
                )
                FILTER has_tagged > 0
                LET cal_edge = FIRST(
                    FOR edge IN @@coll
                        FILTER edge._from == file._id AND edge._to == @cal_state
                        RETURN edge
                )
                FILTER cal_edge == null OR cal_edge.hash != @hash
                RETURN file.path
            """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "@coll": _EDGE_COLLECTION,
                        "ml_tagged_state": _STATE_ML_TAGGED,
                        "cal_state": _STATE_CALIBRATED,
                        "hash": calibration_hash,
                    },
                ),
            ),
        )
        return list(cursor)

    # ------------------------------------------------------------------
    # Reconciliation state
    # ------------------------------------------------------------------

    def set_reconciled(
        self,
        file_id: str,
        mode: str,
        calibration_hash: str | None,
        written_at: int | None = None,
        has_namespace: bool = False,
    ) -> None:
        """Upsert the reconciled edge for a file.

        Args:
            file_id: Document _id.
            mode: Write mode used (``none``, ``minimal``, ``full``).
            calibration_hash: Calibration hash at time of write.
            written_at: Timestamp in ms (defaults to now).
            has_namespace: Whether file has essentia:* namespace tags.
        """
        if written_at is None:
            written_at = now_ms().value
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            UPSERT { _from: @file_id, _to: @state }
            INSERT {
                _from: @file_id, _to: @state,
                mode: @mode, calibration_hash: @calibration_hash,
                written_at: @written_at, has_namespace: @has_namespace
            }
            UPDATE {
                mode: @mode, calibration_hash: @calibration_hash,
                written_at: @written_at, has_namespace: @has_namespace
            }
            IN @@coll
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "file_id": file_id,
                    "state": _STATE_RECONCILED,
                    "mode": mode,
                    "calibration_hash": calibration_hash,
                    "written_at": written_at,
                    "has_namespace": has_namespace,
                    "@coll": _EDGE_COLLECTION,
                },
            ),
        )

    def clear_reconciled(self, file_id: str) -> None:
        """Remove the reconciled edge for a file.

        Args:
            file_id: Document _id.
        """
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR edge IN @@coll
                FILTER edge._from == @file_id AND edge._to == @state
                REMOVE edge IN @@coll
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {"file_id": file_id, "state": _STATE_RECONCILED, "@coll": _EDGE_COLLECTION},
            ),
        )

    def get_files_needing_reconciliation(
        self,
        library_id: str,
        target_mode: str,
        calibration_hash: str | None,
        batch_size: int = 100,
    ) -> list[dict[str, Any]]:
        """Get files that need tag reconciliation.

        A file needs reconciliation when it has an ``ml_tagged`` edge (file has
        ML tags in the database) AND:
        - No reconciled edge exists (never written), OR
        - Edge mode != target_mode, OR
        - Edge calibration_hash != expected hash (for modes using mood tags)

        Args:
            library_id: Library document _id.
            target_mode: Desired write mode.
            calibration_hash: Current calibration hash (None = ignore hash matching).
            batch_size: Maximum files to return.

        Returns:
            List of file dicts (``_id``, ``_key``, ``path``).
        """
        # Build hash mismatch clause only when calibration matters
        hash_clause = ""
        if calibration_hash is not None:
            hash_clause = "OR rec_edge.calibration_hash != @calibration_hash"

        query = f"""
            FOR file IN library_files
                FILTER file.library_id == @library_id
                LET has_tagged = LENGTH(
                    FOR edge IN @@coll
                        FILTER edge._from == file._id AND edge._to == @ml_tagged_state
                        LIMIT 1
                        RETURN 1
                )
                FILTER has_tagged > 0
                LET rec_edge = FIRST(
                    FOR edge IN @@coll
                        FILTER edge._from == file._id AND edge._to == @state
                        RETURN edge
                )
                FILTER rec_edge == null
                    OR rec_edge.mode != @target_mode
                    {hash_clause}
                SORT file._key
                LIMIT @batch_size
                RETURN {{ _id: file._id, _key: file._key, path: file.path }}
        """
        bind_vars: dict[str, Any] = {
            "library_id": library_id,
            "ml_tagged_state": _STATE_ML_TAGGED,
            "state": _STATE_RECONCILED,
            "target_mode": target_mode,
            "@coll": _EDGE_COLLECTION,
            "batch_size": batch_size,
        }
        if calibration_hash is not None:
            bind_vars["calibration_hash"] = calibration_hash

        cursor = cast(
            "Cursor",
            self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)),  # type: ignore[union-attr]
        )
        return list(cursor)

    def count_files_needing_reconciliation(
        self,
        library_id: str,
        target_mode: str,
        calibration_hash: str | None,
    ) -> int:
        """Count files needing tag reconciliation.

        Same logic as ``get_files_needing_reconciliation`` but returns count only.
        Only counts files that have an ``ml_tagged`` edge (ML tags exist in DB).

        Args:
            library_id: Library document _id.
            target_mode: Desired write mode.
            calibration_hash: Current calibration hash.

        Returns:
            Number of files needing reconciliation.
        """
        hash_clause = ""
        if calibration_hash is not None:
            hash_clause = "OR rec_edge.calibration_hash != @calibration_hash"

        query = f"""
            FOR file IN library_files
                FILTER file.library_id == @library_id
                LET has_tagged = LENGTH(
                    FOR edge IN @@coll
                        FILTER edge._from == file._id AND edge._to == @ml_tagged_state
                        LIMIT 1
                        RETURN 1
                )
                FILTER has_tagged > 0
                LET rec_edge = FIRST(
                    FOR edge IN @@coll
                        FILTER edge._from == file._id AND edge._to == @state
                        RETURN edge
                )
                FILTER rec_edge == null
                    OR rec_edge.mode != @target_mode
                    {hash_clause}
                COLLECT WITH COUNT INTO cnt
                RETURN cnt
        """
        bind_vars: dict[str, Any] = {
            "library_id": library_id,
            "ml_tagged_state": _STATE_ML_TAGGED,
            "state": _STATE_RECONCILED,
            "target_mode": target_mode,
            "@coll": _EDGE_COLLECTION,
        }
        if calibration_hash is not None:
            bind_vars["calibration_hash"] = calibration_hash

        cursor = cast(
            "Cursor",
            self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)),  # type: ignore[union-attr]
        )
        return next(cursor, 0)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # ML tagging discovery
    # ------------------------------------------------------------------

    def discover_next_untagged_file(
        self,
        min_duration_s: int | None = None,
        allow_short: bool = True,
    ) -> dict[str, Any] | None:
        """Find next file needing ML tagging for worker discovery.

        Finds files WITHOUT an ``ml_tagged`` edge and without active
        ``worker_claims``.  Used by ML workers to claim work.

        Args:
            min_duration_s: Minimum duration in seconds for ML processing.
                If provided and *allow_short* is ``False``, files shorter
                than this are excluded from discovery.
            allow_short: If ``True``, skip duration filtering.

        Returns:
            File dict or ``None`` if no work available.
        """
        duration_filter = ""
        bind_vars: dict[str, Any] = {"@coll": _EDGE_COLLECTION, "ml_tagged_state": _STATE_ML_TAGGED}
        if min_duration_s is not None and not allow_short:
            duration_filter = (
                "\n                    FILTER file.duration_seconds == null"
                " OR file.duration_seconds >= @min_duration_s"
            )
            bind_vars["min_duration_s"] = min_duration_s

        query = f"""\
                FOR file IN library_files{duration_filter}
                    LET has_tagged = LENGTH(
                        FOR edge IN @@coll
                            FILTER edge._from == file._id AND edge._to == @ml_tagged_state
                            LIMIT 1
                            RETURN 1
                    )
                    FILTER has_tagged == 0
                    LET claim_key = CONCAT("claim_", file._key)
                    FILTER DOCUMENT(CONCAT("worker_claims/", claim_key)) == null
                    SORT file._key
                    LIMIT 1
                    RETURN file
                """
        logger.debug("[DB] discover_next_untagged_file query: %s", query.strip())
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                query,
                bind_vars=cast("dict[str, Any]", bind_vars),
            ),
        )
        results = list(cursor)
        logger.debug("[DB] discover_next_untagged_file raw results count: %d", len(results))
        result = results[0] if results else None
        if result:
            logger.debug("[DB] discover_next_untagged_file: found %s", result.get("_id"))
        else:
            if logger.isEnabledFor(logging.DEBUG):
                self._log_tagging_diagnostics()
        return result

    def count_untagged_files(self, library_id: int | None = None) -> int:
        """Count files without an ``ml_tagged`` edge.

        Args:
            library_id: Optional library ID to scope the count.

        Returns:
            Number of files missing the ``ml_tagged`` edge.
        """
        filter_clause = "FILTER file.library_id == @library_id" if library_id is not None else ""
        bind_vars: dict[str, Any] = {"@coll": _EDGE_COLLECTION, "ml_tagged_state": _STATE_ML_TAGGED}
        if library_id is not None:
            bind_vars["library_id"] = library_id

        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                f"""
                FOR file IN library_files
                    {filter_clause}
                    LET has_tagged = LENGTH(
                        FOR edge IN @@coll
                            FILTER edge._from == file._id AND edge._to == @ml_tagged_state
                            LIMIT 1
                            RETURN 1
                    )
                    FILTER has_tagged == 0
                    COLLECT WITH COUNT INTO cnt
                    RETURN cnt
                """,
                bind_vars=cast("dict[str, Any]", bind_vars),
            ),
        )
        return next(cursor, 0)  # type: ignore[arg-type]

    def count_recently_tagged(self, window_seconds: int = 300) -> int:
        """Count files tagged within a recent time window.

        Queries ``ml_tagged`` edges with ``tagged_at`` attribute within
        the lookback window.

        Args:
            window_seconds: Lookback window in seconds (default 300 = 5 minutes).

        Returns:
            Number of files tagged within the window.
        """
        cutoff = now_ms().value - (window_seconds * 1000)
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR edge IN @@coll
                    FILTER edge._to == @ml_tagged_state
                    FILTER edge.tagged_at != null
                    FILTER edge.tagged_at >= @cutoff
                    COLLECT WITH COUNT INTO cnt
                    RETURN cnt
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "@coll": _EDGE_COLLECTION,
                        "ml_tagged_state": _STATE_ML_TAGGED,
                        "cutoff": cutoff,
                    },
                ),
            ),
        )
        return next(cursor, 0)  # type: ignore[arg-type]

    def _log_tagging_diagnostics(self) -> None:
        """Log diagnostic counts for tagging discovery debugging."""
        diag = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """\
                LET total = LENGTH(FOR f IN library_files RETURN 1)
                LET untagged = LENGTH(
                    FOR f IN library_files
                        LET has_tagged = LENGTH(
                            FOR edge IN @@coll
                                FILTER edge._from == f._id AND edge._to == @ml_tagged_state
                                LIMIT 1
                                RETURN 1
                        )
                        FILTER has_tagged == 0
                        RETURN 1
                )
                LET unclaimed = LENGTH(
                    FOR f IN library_files
                        LET has_tagged = LENGTH(
                            FOR edge IN @@coll
                                FILTER edge._from == f._id AND edge._to == @ml_tagged_state
                                LIMIT 1
                                RETURN 1
                        )
                        FILTER has_tagged == 0
                        LET claim_key = CONCAT("claim_", f._key)
                        FILTER DOCUMENT(CONCAT("worker_claims/", claim_key)) == null
                        RETURN 1
                )
                RETURN {total, untagged, unclaimed}
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {"@coll": _EDGE_COLLECTION, "ml_tagged_state": _STATE_ML_TAGGED},
                ),
            ),
        )
        diag_result: dict[str, Any] = next(iter(diag), {})
        logger.debug(
            "[DB] discover_next_untagged_file: no files found. "
            "Diagnostics: total=%s, untagged=%s, unclaimed=%s",
            diag_result.get("total"),
            diag_result.get("untagged"),
            diag_result.get("unclaimed"),
        )

    # ------------------------------------------------------------------
    # Cross-state utilities
    # ------------------------------------------------------------------

    def clear_all_states(self, file_id: str) -> int:
        """Remove all state edges for a file (e.g., on file deletion).

        Args:
            file_id: Document _id.

        Returns:
            Number of edges removed.
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR edge IN @@coll
                    FILTER edge._from == @file_id
                    REMOVE edge IN @@coll
                    COLLECT WITH COUNT INTO cnt
                    RETURN cnt
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {"file_id": file_id, "@coll": _EDGE_COLLECTION},
                ),
            ),
        )
        return next(cursor, 0)  # type: ignore[arg-type]


    def clear_all_states_batch(self, file_ids: list[str]) -> int:
        """Remove all state edges for a batch of files.

        Used during bulk file deletion to cascade edge cleanup.

        Args:
            file_ids: List of document _id values.

        Returns:
            Number of edges removed.
        """
        if not file_ids:
            return 0
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR edge IN @@coll
                    FILTER edge._from IN @file_ids
                    REMOVE edge IN @@coll
                    COLLECT WITH COUNT INTO cnt
                    RETURN cnt
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {"file_ids": file_ids, "@coll": _EDGE_COLLECTION},
                ),
            ),
        )
        return next(cursor, 0)  # type: ignore[arg-type]
