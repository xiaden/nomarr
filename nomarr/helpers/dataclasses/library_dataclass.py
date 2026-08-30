"""Domain representation of a configured music library."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class Library:
    """A music library identified by its natural ``(name, root_path)`` key.

    The object deliberately contains no database-generated identifier or
    storage vocabulary.  ``created_at`` and ``updated_at`` are optional only
    while constructing a new library; persistence supplies them when absent.
    Returned objects always contain the persisted timestamp values.
    """

    name: str
    root_path: str
    is_enabled: bool = True
    watch_mode: Literal["off", "event", "poll"] = "off"
    file_write_mode: Literal["none", "minimal", "full"] = "full"
    library_auto_write: bool = False
    created_at: int | None = None
    updated_at: int | None = None


__all__ = ["Library"]
