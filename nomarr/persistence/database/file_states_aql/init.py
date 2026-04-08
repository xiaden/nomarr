"""Initialization operations for file state edges."""

from __future__ import annotations

from typing import Any, cast

from nomarr.persistence.arango_client import DatabaseLike

from ._constants import _EDGE_COLLECTION, AXIS_PAIRS


class FileStatesInitMixin:
    """Lifecycle entry points for creating file state edges."""

    db: DatabaseLike

    def initialize_file_states(self, file_id: str) -> None:
        """Create all-negative state edges for one file."""
        negative_states = [pair[1] for pair in AXIS_PAIRS.values()]
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR state IN @negative_states
                INSERT { _from: @file_id, _to: state } INTO @@coll
                OPTIONS { ignoreErrors: true }
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "file_id": file_id,
                    "negative_states": negative_states,
                    "@coll": _EDGE_COLLECTION,
                },
            ),
        )

    def initialize_file_states_batch(self, file_ids: list[str]) -> None:
        """Create all-negative state edges for multiple files in one query."""
        if not file_ids:
            return

        negative_states = [pair[1] for pair in AXIS_PAIRS.values()]
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            FOR file_id IN @file_ids
                FOR state IN @negative_states
                    INSERT { _from: file_id, _to: state } INTO @@coll
                    OPTIONS { ignoreErrors: true }
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "file_ids": file_ids,
                    "negative_states": negative_states,
                    "@coll": _EDGE_COLLECTION,
                },
            ),
        )
