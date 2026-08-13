"""Library and pipeline-state sub-facade for the library surface.

Holds all library-domain (``libraries`` table) and pipeline-axis intent
methods. Wired into ``LibraryDb`` as its ``regions`` namespace
(namespaced-forwarding split per DD-persistence-intent-facade-rebuild
§Phase 1). Methods moved verbatim from ``LibraryDb`` — signatures and
behavior unchanged.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, scoped_session

    from nomarr.helpers.dto.repo_dto import LibraryRow
    from nomarr.persistence.database.library_repo import LibraryRepository
    from nomarr.persistence.database.song_state_repo import SongStateRepository


class LibraryRegionsDb:
    """Persistence sub-facade for library and pipeline-state operations.

    Domain identity: the ``name`` and ``path`` library columns. Owns
    library CRUD plus pipeline-state reads. Pipeline-axis state now
    lives in ``pipeline_states`` rows (no columns on ``libraries``): the
    read methods below forward to ``LibraryRepository``, which delegates
    to ``PipelineRepository`` for the row-backed lookups.
    """

    def __init__(
        self,
        *,
        session: scoped_session[Session],
        library_repo: LibraryRepository,
        song_state_repo: SongStateRepository,
    ) -> None:
        self._session = session
        self._library_repo = library_repo
        self._song_state_repo = song_state_repo

    def add_library(self, payload: dict[str, Any]) -> int:
        """Create a new library and return its ID."""
        return self._library_repo.add_library(payload)

    def get_library(self, library_id: int) -> LibraryRow | None:
        """Get a library by its ID."""
        return self._library_repo.get_library(library_id)

    def get_library_by_name(self, name: str) -> LibraryRow | None:
        """Get a library by its name."""
        return self._library_repo.get_library_by_name(name)

    def list_libraries(self, *, enabled_only: bool = False) -> list[LibraryRow]:
        """List all libraries, optionally filtering to enabled only."""
        return self._library_repo.list_libraries(enabled_only=enabled_only)

    def list_library_keys(self) -> list[int]:
        """Return the IDs of all libraries."""
        return self._library_repo.list_library_keys()

    def update_library(self, library_id: int, fields: dict[str, Any]) -> None:
        """Update fields on a library."""
        self._library_repo.update_library(library_id, fields)

    def get_pipeline_state(self, library_id: int) -> dict[str, str] | None:
        """Return the four pipeline axis values for a library."""
        return self._library_repo.get_pipeline_state(library_id)

    def get_libraries_in_axis_state(self, axis_field: str, axis_value: str) -> list[int]:
        """Return library IDs where the given axis field matches the value."""
        return self._library_repo.get_libraries_in_axis_state(axis_field, axis_value)

    def remove_library(self, library_id: int) -> bool:
        """Delete a library and all associated data.

        Returns True if the library was found and deleted, False if not found.
        Delegates to the LibraryRepository cascade delete.
        Orphaned tag rows are not cleaned up — callers should invoke
        cleanup_orphaned_tags() separately if needed.
        """
        if not self._library_repo.get_library(library_id):
            return False
        self._library_repo.remove_library(library_id)
        return True
