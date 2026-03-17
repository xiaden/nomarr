"""Status operations for library_files collection."""

from typing import TYPE_CHECKING, Any

from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


class LibraryFilesStatusMixin:
    """Status operations for library_files."""

    db: DatabaseLike
    collection: Any
    parent_db: "Database | None"

    def mark_file_tagged(self, file_id: str, tagged_version: str) -> None:
        """Mark file as tagged.

        Delegates to edge-based state via ``db.file_states.set_ml_tagged()``.
        Creates or updates the ``file_has_state`` edge to ``file_states/ml_tagged``.

        Args:
            file_id: Document _id (e.g., "library_files/12345")
            tagged_version: Tagged version string

        """
        assert self.parent_db is not None, "parent_db required for edge-based state"
        self.parent_db.file_states.set_ml_tagged(file_id, version=tagged_version)

    def library_has_tagged_files(self, library_id: str) -> bool:
        """Check if library has any files with ML tags.

        Queries for existence of any ``file_has_state`` edge to
        ``file_states/ml_tagged`` for the library's files.

        Args:
            library_id: Library ID

        Returns:
            True if library has at least one tagged file

        """
        assert self.parent_db is not None, "parent_db required for edge-based state"
        return self.parent_db.file_states.library_has_tagged_files(library_id)

    def discover_next_unprocessed_file(
        self,
        min_duration_s: int | None = None,
        allow_short: bool = True,
    ) -> dict[str, Any] | None:
        """Discover next file needing ML tagging for worker discovery.

        Delegates to ``db.file_states.discover_next_untagged_file()``.

        Args:
            min_duration_s: Minimum duration in seconds for ML processing.
                If provided and allow_short=False, files shorter than this
                are excluded from discovery.
            allow_short: If True, skip duration filtering (process all files).

        Returns:
            File dict or None if no work available
        """
        assert self.parent_db is not None, "parent_db required for edge-based state"
        return self.parent_db.file_states.discover_next_untagged_file(
            min_duration_s=min_duration_s,
            allow_short=allow_short,
        )
