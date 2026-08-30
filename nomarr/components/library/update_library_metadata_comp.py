"""Update library metadata component."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.components.library.library_records_comp import update_library_record
from nomarr.helpers.exceptions import DuplicateEntityError

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.persistence.db import Database


class UpdateLibraryMetadataComp:
    """Component for updating library metadata."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def update(
        self,
        library: Library,
        *,
        name: str | None = None,
        is_enabled: bool | None = None,
        watch_mode: str | None = None,
        file_write_mode: str | None = None,
        library_auto_write: bool | None = None,
    ) -> None:
        """Update library metadata fields via library_records_comp."""
        try:
            update_library_record(
                self.db,
                library,
                name=name,
                is_enabled=is_enabled,
                watch_mode=watch_mode,
                file_write_mode=file_write_mode,
                library_auto_write=library_auto_write,
            )
        except DuplicateEntityError as e:
            raise ValueError(f"Library name already exists: {name}") from e
