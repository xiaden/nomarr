"""File state edge operations for ArangoDB.

CRUD operations on the ``file_has_state`` edge collection which connects
``library_files/*`` vertices to ``file_states/*`` singleton vertices.

Each file has exactly one edge per state axis, pointing to either the
positive or negative vertex. State edges are pure boolean — no domain
payload (version, hash, timestamps).

State axes (positive / negative):
    tagged / not_tagged           — ML tagging complete
    too_short / not_too_short     — Below minimum duration for ML
    calibrated / not_calibrated   — Calibration applied
    tags_written / tags_not_written — Tags physically written to disk
    tags_current / tags_stale     — Disk tags match DB state
    scanned / not_scanned         — File processed by scanner
    vectors_extracted / not_vectors_extracted — Embedding vectors exist
    errored / not_errored         — Processing error encountered

Discovery uses INBOUND traversal on negative vertices for O(1) lookup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor

_EDGE_COLLECTION = "file_has_state"

# -- State vertex constants (8 axes, 16 vertices) ---------------------
STATE_TAGGED = "file_states/tagged"
STATE_NOT_TAGGED = "file_states/not_tagged"
STATE_TOO_SHORT = "file_states/too_short"
STATE_NOT_TOO_SHORT = "file_states/not_too_short"
STATE_CALIBRATED = "file_states/calibrated"
STATE_NOT_CALIBRATED = "file_states/not_calibrated"
STATE_TAGS_WRITTEN = "file_states/tags_written"
STATE_TAGS_NOT_WRITTEN = "file_states/tags_not_written"
STATE_TAGS_CURRENT = "file_states/tags_current"
STATE_TAGS_STALE = "file_states/tags_stale"
STATE_SCANNED = "file_states/scanned"
STATE_NOT_SCANNED = "file_states/not_scanned"
STATE_VECTORS_EXTRACTED = "file_states/vectors_extracted"
STATE_NOT_VECTORS_EXTRACTED = "file_states/not_vectors_extracted"
STATE_ERRORED = "file_states/errored"
STATE_NOT_ERRORED = "file_states/not_errored"

ALL_STATE_VERTICES = (
    STATE_TAGGED,
    STATE_NOT_TAGGED,
    STATE_TOO_SHORT,
    STATE_NOT_TOO_SHORT,
    STATE_CALIBRATED,
    STATE_NOT_CALIBRATED,
    STATE_TAGS_WRITTEN,
    STATE_TAGS_NOT_WRITTEN,
    STATE_TAGS_CURRENT,
    STATE_TAGS_STALE,
    STATE_SCANNED,
    STATE_NOT_SCANNED,
    STATE_VECTORS_EXTRACTED,
    STATE_NOT_VECTORS_EXTRACTED,
    STATE_ERRORED,
    STATE_NOT_ERRORED,
)

AXIS_PAIRS: dict[str, tuple[str, str]] = {
    "tagged": (STATE_TAGGED, STATE_NOT_TAGGED),
    "too_short": (STATE_TOO_SHORT, STATE_NOT_TOO_SHORT),
    "calibrated": (STATE_CALIBRATED, STATE_NOT_CALIBRATED),
    "tags_written": (STATE_TAGS_WRITTEN, STATE_TAGS_NOT_WRITTEN),
    "tags_current": (STATE_TAGS_CURRENT, STATE_TAGS_STALE),
    "scanned": (STATE_SCANNED, STATE_NOT_SCANNED),
    "vectors_extracted": (STATE_VECTORS_EXTRACTED, STATE_NOT_VECTORS_EXTRACTED),
    "errored": (STATE_ERRORED, STATE_NOT_ERRORED),
}


class FileStatesOperations:
    """CRUD operations for the file_has_state edge collection."""

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db
        self.collection = db.collection(_EDGE_COLLECTION)  # type: ignore[union-attr]

    # ------------------------------------------------------------------
    # Axis transition helper
    # ------------------------------------------------------------------

    def _transition_state(self, file_id: str, axis: str, to_positive: bool) -> None:
        """Transition a file's state on a single axis.

        Executes a single atomic AQL query that removes any existing axis edge
        and upserts the target state edge.  Using one round-trip eliminates the
        TOCTOU race that caused unique-constraint violations when two workers
        transitioned the same file concurrently.

        Args:
            file_id: Document ``_id`` of the library file.
            axis: State axis key (must be a key in ``AXIS_PAIRS``).
            to_positive: If True, target the positive vertex; otherwise negative.
        """
        positive, negative = AXIS_PAIRS[axis]
        new_state = positive if to_positive else negative
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR e IN file_has_state
                FILTER e._from == @file_id
                    AND (e._to == @positive OR e._to == @negative)
                REMOVE e IN file_has_state OPTIONS { ignoreErrors: true }
            UPSERT { _from: @file_id, _to: @new_state }
                INSERT { _from: @file_id, _to: @new_state }
                UPDATE {}
                IN file_has_state
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "file_id": file_id,
                    "positive": positive,
                    "negative": negative,
                    "new_state": new_state,
                },
            ),
        )

    # ------------------------------------------------------------------
    # Positive axis setters
    # ------------------------------------------------------------------

    def set_tagged(self, file_id: str) -> None:
        self._transition_state(file_id, "tagged", to_positive=True)

    def set_too_short(self, file_id: str) -> None:
        self._transition_state(file_id, "too_short", to_positive=True)

    def set_calibrated(self, file_id: str) -> None:
        self._transition_state(file_id, "calibrated", to_positive=True)

    def set_tags_written(self, file_id: str) -> None:
        self._transition_state(file_id, "tags_written", to_positive=True)

    def set_tags_current(self, file_id: str) -> None:
        self._transition_state(file_id, "tags_current", to_positive=True)

    def set_scanned(self, file_id: str) -> None:
        self._transition_state(file_id, "scanned", to_positive=True)

    def set_vectors_extracted(self, file_id: str) -> None:
        self._transition_state(file_id, "vectors_extracted", to_positive=True)

    def set_errored(self, file_id: str) -> None:
        self._transition_state(file_id, "errored", to_positive=True)

    # ------------------------------------------------------------------
    # Negative axis setters
    # ------------------------------------------------------------------

    def set_not_tagged(self, file_id: str) -> None:
        self._transition_state(file_id, "tagged", to_positive=False)

    def set_not_too_short(self, file_id: str) -> None:
        self._transition_state(file_id, "too_short", to_positive=False)

    def set_not_calibrated(self, file_id: str) -> None:
        self._transition_state(file_id, "calibrated", to_positive=False)

    def set_tags_not_written(self, file_id: str) -> None:
        self._transition_state(file_id, "tags_written", to_positive=False)

    def set_tags_stale(self, file_id: str) -> None:
        self._transition_state(file_id, "tags_current", to_positive=False)

    def set_not_scanned(self, file_id: str) -> None:
        self._transition_state(file_id, "scanned", to_positive=False)

    def set_not_vectors_extracted(self, file_id: str) -> None:
        self._transition_state(file_id, "vectors_extracted", to_positive=False)

    def set_not_errored(self, file_id: str) -> None:
        self._transition_state(file_id, "errored", to_positive=False)

    # ------------------------------------------------------------------
    # Bulk transitions
    # ------------------------------------------------------------------

    def bulk_set_not_calibrated(self) -> int:
        """Transition ALL files from calibrated to not_calibrated.

        Returns:
            Number of edges transitioned.
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR e IN file_has_state
                    FILTER e._to == @calibrated
                    RETURN { key: e._key, from_id: e._from }
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "calibrated": STATE_CALIBRATED,
                    },
                ),
            ),
        )
        edges = cast("list[dict[str, str]]", list(cursor))
        if not edges:
            return 0

        keys = [edge["key"] for edge in edges]
        from_ids = [edge["from_id"] for edge in edges]

        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR k IN @keys
                REMOVE k IN file_has_state
            """,
            bind_vars=cast("dict[str, Any]", {"keys": keys}),
        )
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR fid IN @from_ids
                INSERT { _from: fid, _to: @not_calibrated } INTO file_has_state
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "from_ids": from_ids,
                    "not_calibrated": STATE_NOT_CALIBRATED,
                },
            ),
        )
        return len(edges)

    def bulk_set_tags_stale(self, library_id: str | None = None) -> int:
        """Transition files from tags_current to tags_stale, optionally scoped to a library.

        Args:
            library_id: If given, only files belonging to this library are transitioned.

        Returns:
            Number of edges transitioned.
        """
        if library_id is not None:
            query = """
                LET lib_file_ids = (
                    FOR f IN OUTBOUND @library_id library_contains_file RETURN f._id
                )
                FOR e IN file_has_state
                    FILTER e._to == @tags_current AND e._from IN lib_file_ids
                    RETURN { key: e._key, from_id: e._from }
            """
            bind_vars: dict[str, Any] = {
                "library_id": library_id,
                "tags_current": STATE_TAGS_CURRENT,
            }
        else:
            query = """
                FOR e IN file_has_state
                    FILTER e._to == @tags_current
                    RETURN { key: e._key, from_id: e._from }
            """
            bind_vars = {
                "tags_current": STATE_TAGS_CURRENT,
            }
        cursor = cast(
            "Cursor",
            self.db.aql.execute(query, bind_vars=cast("dict[str, Any]", bind_vars)),  # type: ignore[union-attr]
        )
        edges = cast("list[dict[str, str]]", list(cursor))
        if not edges:
            return 0

        keys = [edge["key"] for edge in edges]
        from_ids = [edge["from_id"] for edge in edges]

        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR k IN @keys
                REMOVE k IN file_has_state
            """,
            bind_vars=cast("dict[str, Any]", {"keys": keys}),
        )
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR fid IN @from_ids
                INSERT { _from: fid, _to: @tags_stale } INTO file_has_state
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {"from_ids": from_ids, "tags_stale": STATE_TAGS_STALE},
            ),
        )
        return len(edges)

    def bulk_set_scanned(self, file_ids: list[str]) -> int:
        """Transition specified files from not_scanned to scanned.

        Args:
            file_ids: Document ``_id`` values of files to mark as scanned.

        Returns:
            Number of edges transitioned.
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR e IN file_has_state
                    FILTER e._to == @not_scanned AND e._from IN @file_ids
                    RETURN { key: e._key, from_id: e._from }
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "not_scanned": STATE_NOT_SCANNED,
                        "file_ids": file_ids,
                    },
                ),
            ),
        )
        edges = cast("list[dict[str, str]]", list(cursor))
        if not edges:
            return 0

        keys = [edge["key"] for edge in edges]
        from_ids = [edge["from_id"] for edge in edges]

        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR k IN @keys
                REMOVE k IN file_has_state
            """,
            bind_vars=cast("dict[str, Any]", {"keys": keys}),
        )
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR fid IN @from_ids
                INSERT { _from: fid, _to: @scanned } INTO file_has_state
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {"from_ids": from_ids, "scanned": STATE_SCANNED},
            ),
        )
        return len(edges)

    def bulk_set_not_vectors_extracted(self) -> int:
        """Transition ALL files from vectors_extracted to not_vectors_extracted.

        Returns:
            Number of edges transitioned.
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR e IN file_has_state
                    FILTER e._to == @vectors_extracted
                    RETURN { key: e._key, from_id: e._from }
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "vectors_extracted": STATE_VECTORS_EXTRACTED,
                    },
                ),
            ),
        )
        edges = cast("list[dict[str, str]]", list(cursor))
        if not edges:
            return 0

        keys = [edge["key"] for edge in edges]
        from_ids = [edge["from_id"] for edge in edges]

        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR k IN @keys
                REMOVE k IN file_has_state
            """,
            bind_vars=cast("dict[str, Any]", {"keys": keys}),
        )
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR fid IN @from_ids
                INSERT { _from: fid, _to: @not_vectors_extracted } INTO file_has_state
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "from_ids": from_ids,
                    "not_vectors_extracted": STATE_NOT_VECTORS_EXTRACTED,
                },
            ),
        )
        return len(edges)

    def bulk_set_not_errored(self, file_ids: list[str]) -> int:
        """Transition specified files from errored to not_errored.

        Args:
            file_ids: Document ``_id`` values of files to clear from the errored state.

        Returns:
            Number of edges transitioned.
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR e IN file_has_state
                    FILTER e._to == @errored AND e._from IN @file_ids
                    RETURN { key: e._key, from_id: e._from }
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "errored": STATE_ERRORED,
                        "file_ids": file_ids,
                    },
                ),
            ),
        )
        edges = cast("list[dict[str, str]]", list(cursor))
        if not edges:
            return 0

        keys = [edge["key"] for edge in edges]
        from_ids = [edge["from_id"] for edge in edges]

        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR k IN @keys
                REMOVE k IN file_has_state
            """,
            bind_vars=cast("dict[str, Any]", {"keys": keys}),
        )
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR fid IN @from_ids
                INSERT { _from: fid, _to: @not_errored } INTO file_has_state
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {"from_ids": from_ids, "not_errored": STATE_NOT_ERRORED},
            ),
        )
        return len(edges)

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize_file_states(self, file_id: str) -> None:
        """Create all-negative edges for a new file (one per axis)."""
        negative_states = [pair[1] for pair in AXIS_PAIRS.values()]
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR state IN @negative_states
                INSERT { _from: @file_id, _to: state } INTO file_has_state
                OPTIONS { ignoreErrors: true }
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {"file_id": file_id, "negative_states": negative_states},
            ),
        )

    def initialize_file_states_batch(self, file_ids: list[str]) -> None:
        """Create all-negative edges for multiple new files in a single AQL query."""
        if not file_ids:
            return
        negative_states = [pair[1] for pair in AXIS_PAIRS.values()]
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR file_id IN @file_ids
                FOR state IN @negative_states
                    INSERT { _from: file_id, _to: state } INTO file_has_state
                    OPTIONS { ignoreErrors: true }
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {"file_ids": file_ids, "negative_states": negative_states},
            ),
        )

    # ------------------------------------------------------------------
    # Discovery queries (INBOUND traversal on negative state vertices)
    # ------------------------------------------------------------------

    def discover_next_untagged_file(
        self,
        library_id: str | None = None,
        exclude_claimed: bool = True,
    ) -> dict[str, Any] | None:
        """Find next file needing ML tagging via INBOUND traversal.

        Uses negative state vertex ``not_tagged`` for O(1) discovery.
        Excludes files that are ``too_short`` or ``errored`` via set difference.

        Args:
            library_id: Optional library ``_id`` to scope the search.
            exclude_claimed: If True, skip files with active worker claims.

        Returns:
            File dict or None if no work available.
        """
        parts: list[str] = []
        bind_vars: dict[str, Any] = {
            "not_tagged": STATE_NOT_TAGGED,
            "too_short": STATE_TOO_SHORT,
            "errored": STATE_ERRORED,
        }

        parts.append("LET too_short_ids = (FOR f IN INBOUND @too_short file_has_state RETURN f._id)")
        parts.append("LET errored_ids = (FOR f IN INBOUND @errored file_has_state RETURN f._id)")

        if library_id is not None:
            parts.append("LET lib_files = (FOR f IN OUTBOUND @library_id library_contains_file RETURN f._id)")
            bind_vars["library_id"] = library_id

        parts.append("FOR file IN INBOUND @not_tagged file_has_state")
        parts.append("    FILTER file._id NOT IN too_short_ids")
        parts.append("    FILTER file._id NOT IN errored_ids")

        if library_id is not None:
            parts.append("    FILTER file._id IN lib_files")

        if exclude_claimed:
            parts.append(
                "    FILTER LENGTH("
                "FOR c IN worker_claims "
                'FILTER c.file_id == file._id AND c.status == "active" '
                "RETURN 1) == 0"
            )

        parts.append("    SORT file._key")
        parts.append("    LIMIT 1")
        parts.append("    RETURN file")

        query = "\n".join(parts)
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                query,
                bind_vars=cast("dict[str, Any]", bind_vars),
            ),
        )
        results = list(cursor)
        return results[0] if results else None

    def get_untagged_file_ids(self, library_id: str | None = None, limit: int = 100) -> list[str]:
        """Get IDs of files in the ``not_tagged`` state.

        Args:
            library_id: Optional library ``_id`` to scope the query.
            limit: Maximum number of IDs to return.

        Returns:
            List of file ``_id`` values.
        """
        parts: list[str] = []
        bind_vars: dict[str, Any] = {
            "not_tagged": STATE_NOT_TAGGED,
            "limit": limit,
        }

        if library_id is not None:
            parts.append("LET lib_files = (FOR f IN OUTBOUND @library_id library_contains_file RETURN f._id)")
            bind_vars["library_id"] = library_id

        parts.append("FOR file IN INBOUND @not_tagged file_has_state")

        if library_id is not None:
            parts.append("    FILTER file._id IN lib_files")

        parts.append("    SORT file._key")
        parts.append("    LIMIT @limit")
        parts.append("    RETURN file._id")

        query = "\n".join(parts)
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                query,
                bind_vars=cast("dict[str, Any]", bind_vars),
            ),
        )
        return list(cursor)

    def count_untagged_files(self, library_id: str | None = None) -> int:
        """Count files in the ``not_tagged`` state.

        Args:
            library_id: Optional library ``_id`` to scope the count.

        Returns:
            Number of untagged files.
        """
        parts: list[str] = []
        bind_vars: dict[str, Any] = {"not_tagged": STATE_NOT_TAGGED}

        if library_id is not None:
            parts.append("LET lib_files = (FOR f IN OUTBOUND @library_id library_contains_file RETURN f._id)")
            bind_vars["library_id"] = library_id

        inner = "FOR f IN INBOUND @not_tagged file_has_state"
        if library_id is not None:
            inner += " FILTER f._id IN lib_files"
        inner += " RETURN 1"

        parts.append(f"LET untagged = ({inner})")
        parts.append("RETURN LENGTH(untagged)")

        query = "\n".join(parts)
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                query,
                bind_vars=cast("dict[str, Any]", bind_vars),
            ),
        )
        results = list(cursor)
        return results[0] if results else 0

    def count_uncalibrated_files(self) -> int:
        """Count files in the ``not_calibrated`` state.

        Returns:
            Number of uncalibrated files.
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                "RETURN LENGTH(FOR f IN INBOUND @not_calibrated file_has_state RETURN 1)",
                bind_vars=cast(
                    "dict[str, Any]",
                    {"not_calibrated": STATE_NOT_CALIBRATED},
                ),
            ),
        )
        results = list(cursor)
        return results[0] if results else 0

    def get_errored_file_ids(self, library_id: str, limit: int = 500) -> list[str]:
        """Get IDs of files in the ``errored`` state, scoped by library.

        Args:
            library_id: Library key (e.g. ``"abc123"``).
            limit: Maximum number of IDs to return.

        Returns:
            List of file ``_id`` values.
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                LET lib_files = (FOR f IN OUTBOUND @library_id library_contains_file RETURN f._id)
                FOR e IN file_has_state
                    FILTER e._to == @errored AND e._from IN lib_files
                    LIMIT @limit
                    RETURN e._from
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "library_id": f"libraries/{library_id}",
                        "errored": STATE_ERRORED,
                        "limit": limit,
                    },
                ),
            ),
        )
        return list(cursor)

    def count_errored_files(self, library_id: str) -> int:
        """Count files in the ``errored`` state, scoped by library.

        Args:
            library_id: Library key (e.g. ``"abc123"``).

        Returns:
            Number of errored files.
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                LET lib_files = (FOR f IN OUTBOUND @library_id library_contains_file RETURN f._id)
                LET errored = (FOR e IN file_has_state FILTER e._to == @errored AND e._from IN lib_files RETURN 1)
                RETURN LENGTH(errored)
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "library_id": f"libraries/{library_id}",
                        "errored": STATE_ERRORED,
                    },
                ),
            ),
        )
        results = list(cursor)
        return results[0] if results else 0

    def get_uncalibrated_tagged_file_ids(self, library_id: str) -> list[str]:
        """Get IDs of files that are tagged but not calibrated, scoped by library.

        Uses set intersection of INBOUND ``tagged`` and INBOUND ``not_calibrated``.

        Args:
            library_id: Library document ``_id`` (e.g. ``"libraries/abc"``).

        Returns:
            List of file ``_id`` values.
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                LET lib_files = (FOR f IN OUTBOUND @library_id library_contains_file RETURN f._id)
                LET tagged = (FOR e IN file_has_state FILTER e._to == @tagged AND e._from IN lib_files RETURN e._from)
                LET uncalibrated = (FOR e IN file_has_state FILTER e._to == @not_calibrated AND e._from IN lib_files RETURN e._from)
                FOR id IN INTERSECTION(tagged, uncalibrated)
                    RETURN id
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "tagged": STATE_TAGGED,
                        "not_calibrated": STATE_NOT_CALIBRATED,
                        "library_id": library_id,
                    },
                ),
            ),
        )
        return list(cursor)

    def get_stale_file_ids(self, library_id: str | None = None) -> list[str]:
        """Get IDs of files in the ``tags_stale`` state.

        Args:
            library_id: Optional library ``_id`` to scope the query.

        Returns:
            List of file ``_id`` values.
        """
        parts: list[str] = []
        bind_vars: dict[str, Any] = {"tags_stale": STATE_TAGS_STALE}

        if library_id is not None:
            parts.append("LET lib_files = (FOR f IN OUTBOUND @library_id library_contains_file RETURN f._id)")
            bind_vars["library_id"] = library_id

        parts.append("FOR file IN INBOUND @tags_stale file_has_state")

        if library_id is not None:
            parts.append("    FILTER file._id IN lib_files")

        parts.append("    RETURN file._id")

        query = "\n".join(parts)
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                query,
                bind_vars=cast("dict[str, Any]", bind_vars),
            ),
        )
        return list(cursor)

    # ------------------------------------------------------------------
    # Retained / adapted methods
    # ------------------------------------------------------------------

    def get_calibration_status_by_library(self) -> list[dict[str, Any]]:
        """Get calibration status counts grouped by library."""
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR lib IN libraries
                    LET lib_file_ids = (
                        FOR f IN OUTBOUND lib._id library_contains_file RETURN f._id
                    )
                    LET calibrated_count = LENGTH(
                        FOR f IN INBOUND @calibrated file_has_state
                            FILTER f._id IN lib_file_ids
                            RETURN 1
                    )
                    LET not_calibrated_count = LENGTH(
                        FOR f IN INBOUND @not_calibrated file_has_state
                            FILTER f._id IN lib_file_ids
                            RETURN 1
                    )
                    RETURN {
                        library_id: lib._id,
                        calibrated_count: calibrated_count,
                        not_calibrated_count: not_calibrated_count
                    }
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "calibrated": STATE_CALIBRATED,
                        "not_calibrated": STATE_NOT_CALIBRATED,
                    },
                ),
            ),
        )
        return list(cursor)

    def library_has_tagged_files(self, library_id: str) -> bool:
        """Check if any file in a library has the tagged edge.

        Args:
            library_id: Library document _id.

        Returns:
            True if at least one file in the library is tagged.
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR file IN OUTBOUND @library_id library_contains_file
                    FOR edge IN @@coll
                        FILTER edge._from == file._id AND edge._to == @state
                        LIMIT 1
                        RETURN true
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "library_id": library_id,
                        "state": STATE_TAGGED,
                        "@coll": _EDGE_COLLECTION,
                    },
                ),
            ),
        )
        return bool(next(cursor, False))

    def get_files_with_incomplete_tags(
        self,
        expected_heads: list[dict[str, Any]],
        namespace_prefix: str,
        library_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find tagged files whose tag edges are incomplete.

        For each file with a ``tagged`` edge, checks whether it has at
        least one ``song_has_tags`` edge per expected head (model_key + label)
        under the given namespace prefix.

        Args:
            expected_heads: List of ``{head_key, labels, model_key_for_tag}``
                dicts describing the heads every tagged file should have.
            namespace_prefix: Namespace prefix including colon (e.g. ``"nom:"``).
            library_id: Optional library ``_id`` to restrict the scan via
                INBOUND edge traversal on ``library_contains_file``.

        Returns:
            List of ``{file_id, file_key, library_id, matched_count,
            missing_count, missing_heads}`` for **all** tagged files
            (caller filters for incomplete ones).
        """
        bind_vars: dict[str, Any] = {
            "namespace_prefix": namespace_prefix,
            "expected_heads": expected_heads,
        }
        if library_id:
            bind_vars["library_id"] = library_id
            query = """
                        LET expected = @expected_heads
                        FOR edge IN file_has_state
                            FILTER edge._to == "file_states/tagged"
                            LET file = DOCUMENT(edge._from)
                            FILTER file != null
                            FILTER LENGTH(
                                FOR lib IN INBOUND file._id library_contains_file
                                    FILTER lib._id == @library_id
                                    LIMIT 1
                                    RETURN 1
                            ) > 0
                            LET matched_heads = UNIQUE(
                                FOR tag_edge IN song_has_tags
                                    FILTER tag_edge._from == file._id
                                    LET tag = DOCUMENT(tag_edge._to)
                                    FILTER tag != null
                                    FILTER STARTS_WITH(tag.rel, @namespace_prefix)
                                    LET rel_without_prefix = SUBSTRING(tag.rel, 4)
                                    LET first_underscore = FIND_FIRST(rel_without_prefix, "_")
                                    LET label = first_underscore >= 0
                                        ? SUBSTRING(rel_without_prefix, 0, first_underscore)
                                        : rel_without_prefix
                                    FOR exp IN expected
                                        FILTER label IN exp.labels
                                        FILTER CONTAINS(rel_without_prefix, exp.model_key_for_tag)
                                        RETURN exp.head_key
                            )
                            LET missing_heads = (
                                FOR exp IN expected
                                    FILTER exp.head_key NOT IN matched_heads
                                    RETURN exp.head_key
                            )
                            RETURN {
                                file_id: file._id,
                                file_key: file._key,
                                library_id: @library_id,
                                matched_count: LENGTH(matched_heads),
                                missing_count: LENGTH(missing_heads),
                                missing_heads: missing_heads
                            }
                        """
        else:
            query = """
                        LET expected = @expected_heads
                        FOR edge IN file_has_state
                            FILTER edge._to == "file_states/tagged"
                            LET file = DOCUMENT(edge._from)
                            FILTER file != null
                            LET matched_heads = UNIQUE(
                                FOR tag_edge IN song_has_tags
                                    FILTER tag_edge._from == file._id
                                    LET tag = DOCUMENT(tag_edge._to)
                                    FILTER tag != null
                                    FILTER STARTS_WITH(tag.rel, @namespace_prefix)
                                    LET rel_without_prefix = SUBSTRING(tag.rel, 4)
                                    LET first_underscore = FIND_FIRST(rel_without_prefix, "_")
                                    LET label = first_underscore >= 0
                                        ? SUBSTRING(rel_without_prefix, 0, first_underscore)
                                        : rel_without_prefix
                                    FOR exp IN expected
                                        FILTER label IN exp.labels
                                        FILTER CONTAINS(rel_without_prefix, exp.model_key_for_tag)
                                        RETURN exp.head_key
                            )
                            LET missing_heads = (
                                FOR exp IN expected
                                    FILTER exp.head_key NOT IN matched_heads
                                    RETURN exp.head_key
                            )
                            RETURN {
                                file_id: file._id,
                                file_key: file._key,
                                library_id: file.library_id,
                                matched_count: LENGTH(matched_heads),
                                missing_count: LENGTH(missing_heads),
                                missing_heads: missing_heads
                            }
                        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                query, bind_vars=bind_vars
            ),
        )
        return list(cursor)

    # ------------------------------------------------------------------
    # Batch operations
    # ------------------------------------------------------------------

    def clear_tagged_batch(self, file_ids: list[str]) -> int:
        """Remove tagged edges and insert not_tagged edges for multiple files.

        Marks all listed files as needing re-tagging by removing their
        ``tagged`` edges and inserting ``not_tagged`` counterparts.

        Args:
            file_ids: List of document ``_id`` values.

        Returns:
            Number of files processed.
        """
        if not file_ids:
            return 0
        bind_vars = cast(
            "dict[str, Any]",
            {
                "file_ids": file_ids,
                "tagged": STATE_TAGGED,
                "not_tagged": STATE_NOT_TAGGED,
                "@coll": _EDGE_COLLECTION,
            },
        )
        self.db.aql.execute(  # type: ignore[union-attr]
            "FOR edge IN @@coll FILTER edge._from IN @file_ids AND edge._to == @tagged REMOVE edge IN @@coll",
            bind_vars=bind_vars,
        )
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR fid IN @file_ids
                INSERT { _from: fid, _to: @not_tagged } INTO @@coll
                OPTIONS { ignoreErrors: true }
            """,
            bind_vars=bind_vars,
        )
        return len(file_ids)

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

    def count_pending_tag_writes(self) -> int:
        """Count files in the ``tags_not_written`` state.

        Uses INBOUND traversal on the ``tags_not_written`` state vertex
        for O(1) discovery per ADR-003.

        Returns:
            Number of files with pending tag writes.
        """
        query = """
        RETURN LENGTH(
            FOR f IN INBOUND @tags_not_written file_has_state
                RETURN 1
        )
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                query,
                bind_vars=cast("dict[str, Any]", {"tags_not_written": STATE_TAGS_NOT_WRITTEN}),
            ),
        )
        results = list(cursor)
        return results[0] if results else 0

    def get_pending_tag_write_file_ids(self, limit: int = 100) -> list[str]:
        """Get IDs of files in the ``tags_not_written`` state.

        For commit: discover files needing tag writeback.

        Args:
            limit: Maximum number of IDs to return.

        Returns:
            List of file ``_id`` values.
        """
        query = """
        FOR file IN INBOUND @tags_not_written file_has_state
            SORT file._key
            LIMIT @limit
            RETURN file._id
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                query,
                bind_vars=cast("dict[str, Any]", {"tags_not_written": STATE_TAGS_NOT_WRITTEN, "limit": limit}),
            ),
        )
        return list(cursor)
