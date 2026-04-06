"""Library pipeline state edge operations for ArangoDB.

CRUD operations on the ``library_has_pipeline_state`` edge collection which
connects ``libraries/*`` vertices to ``library_pipeline_states/*`` singleton
vertices.

Each library has exactly one pipeline state edge at a time. State transitions
use atomic REMOVE+INSERT queries to preserve the single-edge invariant.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor

_EDGE_COLLECTION = "library_has_pipeline_state"

PIPELINE_IDLE = "library_pipeline_states/idle"
PIPELINE_SCANNING = "library_pipeline_states/scanning"
PIPELINE_ML_RUNNING = "library_pipeline_states/ml_running"
PIPELINE_TOO_SMALL = "library_pipeline_states/too_small"
PIPELINE_AWAITING_CALIBRATION = "library_pipeline_states/awaiting_calibration"
PIPELINE_CALIBRATING = "library_pipeline_states/calibrating"
PIPELINE_APPLYING = "library_pipeline_states/applying"
PIPELINE_WRITE_READY = "library_pipeline_states/write_ready"
PIPELINE_WRITING = "library_pipeline_states/writing"
PIPELINE_DONE = "library_pipeline_states/done"


class LibraryPipelineStatesOps:
    """CRUD operations for the library_has_pipeline_state edge collection."""

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db
        self.collection = db.collection(_EDGE_COLLECTION)  # type: ignore[union-attr]

    def transition_state(self, library_id: str, to_state: str) -> None:
        """Transition a library to a new pipeline state.

        Issues sequential AQL queries: reads the current edge, removes it if present (and not
        already in the target state), then inserts a new edge.

        Args:
            library_id: Document ``_id`` of the library.
            to_state: Target state document ID (e.g., ``PIPELINE_IDLE``).
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR e IN library_has_pipeline_state
                    FILTER e._from == @library_id
                    LIMIT 1
                    RETURN { key: e._key, to: e._to }
                """,
                bind_vars=cast("dict[str, Any]", {"library_id": library_id}),
            ),
        )
        current_edge = cast("dict[str, str] | None", next(cursor, None))

        if current_edge is not None and current_edge["to"] == to_state:
            return

        if current_edge is not None:
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                REMOVE @old_key IN library_has_pipeline_state
                """,
                bind_vars=cast("dict[str, Any]", {"old_key": current_edge["key"]}),
            )

        self.db.aql.execute(  # type: ignore[union-attr]
            """
            INSERT { _from: @library_id, _to: @to_state } INTO library_has_pipeline_state
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "library_id": library_id,
                    "to_state": to_state,
                },
            ),
        )

    def get_state(self, library_id: str) -> str:
        """Get the current pipeline state key for a library.

        Args:
            library_id: Document ``_id`` of the library.

        Returns:
            The ``_key`` of the current pipeline state vertex (e.g. ``"idle"``).

        Raises:
            ValueError: If no pipeline state edge exists for the library.
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR state IN OUTBOUND @library_id library_has_pipeline_state
                    LIMIT 1
                    RETURN state._key
                """,
                bind_vars=cast("dict[str, Any]", {"library_id": library_id}),
            ),
        )
        state_key = cast("str | None", next(cursor, None))
        if state_key is None:
            msg = f"No pipeline state edge found for library {library_id}"
            raise ValueError(msg)
        return state_key

    def get_libraries_in_state(self, state: str) -> list[str]:
        """Get library document IDs currently in the given pipeline state."""
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR library IN INBOUND @state library_has_pipeline_state
                    RETURN library._id
                """,
                bind_vars=cast("dict[str, Any]", {"state": state}),
            ),
        )
        return list(cursor)

    def bulk_transition(self, from_state: str, to_state: str) -> int:
        """Transition all libraries from one pipeline state to another.

        Args:
            from_state: Source pipeline state document ID (e.g., ``PIPELINE_SCANNING``).
            to_state: Target pipeline state document ID (e.g., ``PIPELINE_IDLE``).

        Returns:
            Number of libraries transitioned.
        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR e IN library_has_pipeline_state
                    FILTER e._to == @from_state
                    RETURN { key: e._key, from_id: e._from }
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "from_state": from_state,
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
            FOR edge_key IN @keys
                REMOVE edge_key IN library_has_pipeline_state
            """,
            bind_vars=cast("dict[str, Any]", {"keys": keys}),
        )
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR library_id IN @from_ids
                INSERT { _from: library_id, _to: @to_state } INTO library_has_pipeline_state
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "from_ids": from_ids,
                    "to_state": to_state,
                },
            ),
        )
        return len(edges)
