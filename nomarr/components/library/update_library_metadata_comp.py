"""Update library metadata component."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.components.library.library_records_comp import update_library_record

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
        library_auto_write: bool | None = None,
    ) -> None:
        """Update library metadata fields.

        Args:
            library_id: Library _id
            name: New name (optional)
            is_enabled: New enabled status (optional)
            watch_mode: New watch mode (optional)
            file_write_mode: New file write mode (optional)
            library_auto_write: New auto-write setting (optional).

        """
        update_library_record(
            self.db,
            library_id,
            name=name,
            is_enabled=is_enabled,
            watch_mode=watch_mode,
            file_write_mode=file_write_mode,
            library_auto_write=library_auto_write,
        )
