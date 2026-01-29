"""Update library metadata component."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


class UpdateLibraryMetadataComp:
    """Component for updating library metadata."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def update(
        self,
        library_id: str,
        *,
        name: str | None = None,
        is_enabled: bool | None = None,
        watch_mode: str | None = None,
        file_write_mode: str | None = None,
    ) -> None:
        """
        Update library metadata fields.

        Args:
            library_id: Library _id
            name: New name (optional)
            is_enabled: New enabled status (optional)
            watch_mode: New watch mode (optional)
            file_write_mode: New file write mode (optional)
        """
        self.db.libraries.update_library(
            library_id, name=name, is_enabled=is_enabled, watch_mode=watch_mode, file_write_mode=file_write_mode
        )
