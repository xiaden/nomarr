"""Mood analysis analytics - coverage, balance, top pairs, dominant vibes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.components.analytics.analytics_comp import compute_dominant_vibes

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def compute_mood_analysis(
    db: Database, library_id: str | None = None,
) -> dict[str, Any]:
    """Get mood analysis: coverage, balance, top pairs, dominant vibes.

    Args:
        db: Database instance.
        library_id: Optional library _id to filter by.

    Returns:
        Dict with: coverage, balance, top_pairs_by_tier, dominant_vibes
    """
    # Mood coverage (% tagged per tier)
    coverage = db.tags.get_mood_coverage(library_id)

    # Mood balance (value distribution per tier)
    balance = db.tags.get_mood_balance(library_id)

    # Top mood pairs for all three tiers
    top_pairs_by_tier = {
        tier: db.tags.get_top_mood_pairs(library_id, mood_tier=tier, limit=50)
        for tier in ("strict", "regular", "loose")
    }

    # Dominant vibes from balance data
    dominant_vibes = compute_dominant_vibes(balance)

    return {
        "coverage": coverage,
        "balance": balance,
        "top_pairs_by_tier": top_pairs_by_tier,
        "dominant_vibes": dominant_vibes,
    }
