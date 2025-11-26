"""
DTOs for recalibration service operations.

Cross-layer data contracts for recalibration service (used by services and interfaces).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GetStatusResult:
    """Result from recalibration_service.get_status()."""

    pending: int
    running: int
    done: int
    error: int
