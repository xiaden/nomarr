"""
Config domain DTOs.

Data transfer objects for configuration service results.
These form cross-layer contracts between services and interfaces.

Rules:
- Import only stdlib and typing (no nomarr.* imports)
- Pure data structures only (no I/O, no DB access, no business logic)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class GetInternalInfoResult:
    """Result from config_service.get_internal_info."""

    namespace: str
    version_tag: str
    min_duration_s: int
    allow_short: bool
    poll_interval: int
    library_scan_poll_interval: int
    worker_enabled: bool


@dataclass
class ConfigResult:
    """Result from config_service.get_config and reload - wraps configuration dict."""

    config: dict[str, Any]
