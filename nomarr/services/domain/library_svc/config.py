"""Library service configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LibraryServiceConfig:
    """Configuration for LibraryService.

    Attributes:
        namespace: Tag namespace for Nomarr tags (e.g., "NOMARR")
        library_root: Path to the library root directory (optional, can be configured later)
    """

    namespace: str
    library_root: str | None = None

    def __post_init__(self) -> None:
        if not self.namespace:
            raise ValueError("namespace cannot be empty")
