"""
Tagging domain DTOs.

Data transfer objects for tagging components and operations.
These form cross-layer contracts between components, workflows, and services.

Rules:
- Import only stdlib and typing (no nomarr.* imports)
- Pure data structures only (no I/O, no DB access, no business logic)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BuildTierTermSetsResult:
    """Result from _build_tier_term_sets (internal tagging aggregation helper)."""

    strict_terms: set[str]
    regular_terms: set[str]
    loose_terms: set[str]
