"""Single-file state transition operations."""

from __future__ import annotations

from typing import Any, cast

from nomarr.persistence.arango_client import DatabaseLike

from ._constants import AXIS_PAIRS, StateAxis


class FileStatesTransitionsMixin:
    """Single-file transitions for the ``file_has_state`` edge graph."""

    db: DatabaseLike

    def _transition_state(self, file_id: str, axis: StateAxis, to_positive: bool) -> None:
        """Transition a file to the positive or negative vertex for one axis."""
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

    def set_tagged(self, file_id: str) -> None:
        """Set the file to the ``tagged`` state."""
        self._transition_state(file_id, "tagged", to_positive=True)

    def set_too_short(self, file_id: str) -> None:
        """Set the file to the ``too_short`` state."""
        self._transition_state(file_id, "too_short", to_positive=True)

    def set_calibrated(self, file_id: str) -> None:
        """Set the file to the ``calibrated`` state."""
        self._transition_state(file_id, "calibrated", to_positive=True)

    def set_tags_written(self, file_id: str) -> None:
        """Set the file to the ``tags_written`` state."""
        self._transition_state(file_id, "tags_written", to_positive=True)

    def set_tags_current(self, file_id: str) -> None:
        """Set the file to the ``tags_current`` state."""
        self._transition_state(file_id, "tags_current", to_positive=True)

    def set_scanned(self, file_id: str) -> None:
        """Set the file to the ``scanned`` state."""
        self._transition_state(file_id, "scanned", to_positive=True)

    def set_vectors_extracted(self, file_id: str) -> None:
        """Set the file to the ``vectors_extracted`` state."""
        self._transition_state(file_id, "vectors_extracted", to_positive=True)

    def set_errored(self, file_id: str) -> None:
        """Set the file to the ``errored`` state."""
        self._transition_state(file_id, "errored", to_positive=True)

    def set_not_tagged(self, file_id: str) -> None:
        """Set the file to the ``not_tagged`` state."""
        self._transition_state(file_id, "tagged", to_positive=False)

    def set_not_too_short(self, file_id: str) -> None:
        """Set the file to the ``not_too_short`` state."""
        self._transition_state(file_id, "too_short", to_positive=False)

    def set_not_calibrated(self, file_id: str) -> None:
        """Set the file to the ``not_calibrated`` state."""
        self._transition_state(file_id, "calibrated", to_positive=False)

    def set_tags_not_written(self, file_id: str) -> None:
        """Set the file to the ``tags_not_written`` state."""
        self._transition_state(file_id, "tags_written", to_positive=False)

    def set_tags_stale(self, file_id: str) -> None:
        """Set the file to the ``tags_stale`` state."""
        self._transition_state(file_id, "tags_current", to_positive=False)

    def set_not_scanned(self, file_id: str) -> None:
        """Set the file to the ``not_scanned`` state."""
        self._transition_state(file_id, "scanned", to_positive=False)

    def set_not_vectors_extracted(self, file_id: str) -> None:
        """Set the file to the ``not_vectors_extracted`` state."""
        self._transition_state(file_id, "vectors_extracted", to_positive=False)

    def set_not_errored(self, file_id: str) -> None:
        """Set the file to the ``not_errored`` state."""
        self._transition_state(file_id, "errored", to_positive=False)
