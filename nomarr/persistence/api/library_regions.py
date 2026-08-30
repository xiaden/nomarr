"""Library and pipeline-state sub-facade for the library surface.

Holds all library-domain (``libraries`` table) and pipeline-axis intent
methods. Wired into ``LibraryDb`` as its ``regions`` namespace.

Domain boundary (ADR-032/ADR-041): every public method accepts and returns
domain ``Library`` values and the typed ``LibraryUpdate`` / ``LibraryPipelineState``
commands. ``LibraryRow``, storage aliases (``path``, ``library_type``,
``auto_tag``, ``auto_curate``), SQL rows, and generated ``id`` values stay
inside persistence: they are translated by
``nomarr/persistence/mappers/library_mapper.py`` and resolved through
``LibraryRepository`` / ``PipelineRepository``. Callers know nothing of the
underlying tables or primary keys.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.helpers.constants.pipeline_states import (
    PIPELINE_AXIS_FIELDS,
    VALID_PIPELINE_TRANSITIONS,
)
from nomarr.helpers.dataclasses.library_domain_dataclasses import LibraryPipelineState, LibraryUpdate
from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.mappers.library_mapper import (
    library_from_row,
    library_insert_payload,
    library_update_payload,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, scoped_session

    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.persistence.database.library_repo import LibraryRepository
    from nomarr.persistence.database.pipeline_repo import PipelineRepository
    from nomarr.persistence.database.song_state_repo import SongStateRepository


class LibraryRegionsDb:
    """Persistence sub-facade for library and pipeline-state operations.

    Domain identity is the natural ``(name, root_path)`` ``Library`` key.
    Owns library CRUD plus pipeline-state reads. Pipeline-axis state lives in
    ``pipeline_states`` rows (no columns on ``libraries``): the read/write
    methods below forward to ``LibraryRepository`` / ``PipelineRepository``,
    mapping rows to ``LibraryPipelineState`` internally so no row payload
    leaks to callers.
    """

    def __init__(
        self,
        *,
        session: scoped_session[Session],
        library_repo: LibraryRepository,
        song_state_repo: SongStateRepository,
        pipeline_repo: PipelineRepository,
    ) -> None:
        self._session = session
        self._library_repo = library_repo
        self._song_state_repo = song_state_repo
        self._pipeline_repo = pipeline_repo

    # ── natural-key resolution (persistence-internal) ────────────────────

    def _resolve_library_id(self, library: Library) -> int | None:
        """Resolve a ``Library``'s natural key to its storage row id.

        Returns ``None`` when no library matches ``(name, root_path)``.
        The id is used only to reach the row; it never crosses this facade.
        """
        row = self._library_repo.get_library_by_natural_key(library.name, library.root_path)
        return None if row is None else row["id"]

    def _library_by_id(self, library_id: int) -> Library:
        """Map a storage row (by id) to a domain ``Library``."""
        row = self._library_repo.get_library(library_id)
        if row is None:
            raise LookupError(f"Library with id {library_id} no longer exists")
        return library_from_row(row)

    # ── library CRUD ─────────────────────────────────────────────────────

    def create_library(self, library: Library) -> Library:
        """Create a library and return the persisted ``Library``.

        Timestamps are supplied by persistence when absent on the input
        ``Library`` (per ADR-032 — persistence owns them). The returned
        ``Library`` always carries the persisted ``created_at``/``updated_at``.
        """
        payload = library_insert_payload(library)
        if payload.get("created_at") is None or payload.get("updated_at") is None:
            timestamp = now_ms().value
            payload["created_at"] = payload["created_at"] or timestamp
            payload["updated_at"] = payload["updated_at"] or timestamp
        library_id = self._library_repo.add_library(payload)
        return self._library_by_id(library_id)

    def get_library(self, library: Library) -> Library | None:
        """Get a library by its natural ``(name, root_path)`` identity."""
        library_id = self._resolve_library_id(library)
        if library_id is None:
            return None
        row = self._library_repo.get_library(library_id)
        return None if row is None else library_from_row(row)

    def get_library_by_name(self, name: str) -> Library | None:
        """Get a library by its name."""
        row = self._library_repo.get_library_by_name(name)
        return None if row is None else library_from_row(row)

    def list_libraries(self, *, enabled_only: bool = False) -> list[Library]:
        """List all libraries, optionally filtering to enabled only."""
        return [library_from_row(row) for row in self._library_repo.list_libraries(enabled_only=enabled_only)]

    def update_library(self, library: Library, changes: LibraryUpdate) -> Library:
        """Apply a typed ``LibraryUpdate`` and return the updated ``Library``.

        The library is located by its natural ``(name, root_path)`` identity;
        ``changes`` fields are translated to storage columns internally. The
        returned ``Library`` reflects the freshly persisted row.
        """
        library_id = self._resolve_library_id(library)
        if library_id is None:
            raise LookupError(f"Library {library.name!r} at {library.root_path!r} does not exist")
        payload = library_update_payload(changes)
        if payload:
            self._library_repo.update_library(library_id, payload)
        return self._library_by_id(library_id)

    def remove_library(self, library: Library) -> bool:
        """Delete a library and all associated data.

        Returns True if the library was found and deleted, False if not found.
        Delegates to the ``LibraryRepository`` cascade delete. Orphaned tag
        rows are not cleaned up — callers should invoke
        ``cleanup_orphaned_tags()`` separately if needed.
        """
        library_id = self._resolve_library_id(library)
        if library_id is None:
            return False
        self._library_repo.remove_library(library_id)
        return True

    # ── pipeline-state (row-backed, domain value) ────────────────────────

    def get_pipeline_state(self, library: Library) -> LibraryPipelineState:
        """Return the pipeline state for a library, defaulting when no rows.

        Missing axes fall back to ``PIPELINE_DEFAULTS`` (preserving today's
        behavior); ``pipeline_states`` rows and their ``state_data`` payloads
        never leave this facade.
        """
        library_id = self._resolve_library_id(library)
        if library_id is None:
            return LibraryPipelineState.defaults()
        state = self._library_repo.get_pipeline_state(library_id)
        return LibraryPipelineState.defaults() if state is None else LibraryPipelineState.from_mapping(state)

    def set_pipeline_axis(self, library: Library, axis: str, state: str) -> LibraryPipelineState:
        """Set one library pipeline axis and return the updated state.

        Validates that ``axis`` is a canonical ``PIPELINE_AXIS_FIELDS`` key and
        that ``state`` is a canonical pole for that axis (via
        ``VALID_PIPELINE_TRANSITIONS``). Raises ``ValueError`` on an invalid
        axis or state.
        """
        if axis not in PIPELINE_AXIS_FIELDS:
            raise ValueError(f"Unknown pipeline axis: {axis!r}")
        if state not in VALID_PIPELINE_TRANSITIONS[axis]:
            raise ValueError(f"Invalid state {state!r} for pipeline axis {axis!r}")
        library_id = self._resolve_library_id(library)
        if library_id is None:
            raise LookupError(f"Library {library.name!r} does not exist")
        self._pipeline_repo.upsert_pipeline_state(library_id, axis, {"state": state})
        return self.get_pipeline_state(library)

    def get_libraries_in_axis_state(self, axis: str, state: str) -> list[Library]:
        """Return the ``Library`` values whose pipeline axis equals ``state``.

        Resolved ids from ``pipeline_states`` are mapped back to ``Library``
        via the repository/mapper; no id or row crosses the boundary.
        """
        if axis not in PIPELINE_AXIS_FIELDS:
            raise ValueError(f"Unknown pipeline axis: {axis!r}")
        ids = self._pipeline_repo.list_libraries_in_pipeline_state(axis, state)
        libraries: list[Library] = []
        for library_id in ids:
            row = self._library_repo.get_library(library_id)
            if row is not None:
                libraries.append(library_from_row(row))
        return libraries

    def remove_pipeline_state(self, library: Library) -> None:
        """Remove all pipeline state for a library."""
        library_id = self._resolve_library_id(library)
        if library_id is None:
            return
        self._pipeline_repo.delete_pipeline_state(library_id)
