"""Mood analysis analytics - coverage, balance, top pairs, dominant vibes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from typing import TypedDict

from nomarr.components.analytics.analytics_comp import DominantVibeResult, compute_dominant_vibes

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


class MoodAnalysisResult(TypedDict):
    """Result shape for compute_mood_analysis."""

    coverage: dict[str, Any]
    balance: dict[str, Any]
    top_pairs_by_tier: dict[str, Any]
    dominant_vibes: list[DominantVibeResult]


def compute_mood_analysis(
    db: Database,
    library_id: str | None = None,
) -> MoodAnalysisResult:
    """Compute mood analysis: coverage, balance, top pairs, dominant vibes.

    Args:
        db: Database instance.
        library_id: Optional library _id to filter by.
    """
    coverage = db.tags.get_mood_coverage(library_id)
    balance = db.tags.get_mood_balance(library_id)
    top_pairs_by_tier = {
        tier: db.tags.get_top_mood_pairs(library_id, mood_tier=tier, limit=50)
        for tier in ("strict", "regular", "loose")
    }
    dominant_vibes = compute_dominant_vibes(balance)

    return {
        "coverage": coverage,
        "balance": balance,
        "top_pairs_by_tier": top_pairs_by_tier,
        "dominant_vibes": dominant_vibes,
    }
