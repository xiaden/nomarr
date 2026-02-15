"""Workflow for computing mood analysis analytics.

Orchestrates persistence queries for mood coverage, balance, top pairs,
and component computation for dominant vibes.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.analytics.analytics_comp import compute_dominant_vibes

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def mood_analysis_workflow(
    db: Database,
    library_id: str | None = None,
    mood_tier: str = "strict",
) -> dict[str, Any]:
    """Get mood analysis data for Insights tab.

    Orchestrates coverage, balance, top pairs, and dominant vibes.

    Args:
        db: Database instance.
        library_id: Optional library _id to filter by.
        mood_tier: Mood tier for top pairs ("strict", "regular", or "loose").

    Returns:
        Dict with: coverage, balance, top_pairs, dominant_vibes
    """
    # Step 1: Get mood coverage (% tagged per tier)
    coverage = db.tags.get_mood_coverage(library_id)

    # Step 2: Get mood balance (value distribution per tier)
    balance = db.tags.get_mood_balance(library_id)

    # Step 3: Get top mood pairs (within selected tier)
    top_pairs = db.tags.get_top_mood_pairs(library_id, mood_tier=mood_tier)

    # Step 4: Compute dominant vibes from balance data
    dominant_vibes = compute_dominant_vibes(balance)

    return {
        "coverage": coverage,
        "balance": balance,
        "top_pairs": top_pairs,
        "dominant_vibes": dominant_vibes,
    }
