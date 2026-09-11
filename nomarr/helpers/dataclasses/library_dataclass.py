"""Domain representation of a configured music library."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class Library:
    """A configured music library.

    ``library_uuid`` is the immutable Nomarr-owned application identity used by
    the ``SongLocator`` (ADR-049); it is minted by persistence on creation and
    never changes across rename or root-path updates. ``name`` and ``root_path``
    are mutable configuration metadata, not Song identity. The object
    deliberately contains no database-generated integer identifier or storage
    vocabulary. ``library_uuid``, ``created_at`` and ``updated_at`` are optional
    only while constructing a new library; persistence supplies/mints them when
    absent. Returned objects always contain the persisted values.
    """

    name: str
    root_path: str
    library_uuid: str | None = None
    is_enabled: bool = True
    watch_mode: Literal["off", "event", "poll"] = "off"
    file_write_mode: Literal["none", "minimal", "full"] = "full"
    library_auto_write: bool = False
    created_at: int | None = None
    updated_at: int | None = None


__all__ = ["Library"]
