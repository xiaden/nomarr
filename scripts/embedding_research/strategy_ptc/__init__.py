"""PTC segment-phase strategy adapters."""

from .segment_fn import STRATEGY_NAMES, make_segment_fn

__all__ = ["STRATEGY_NAMES", "make_segment_fn"]
