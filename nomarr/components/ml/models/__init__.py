"""
Models package.
"""

from .discovery import (
    HeadInfo,
    HeadOutput,
    Sidecar,
    discover_heads,
    get_embedding_output_node,
    get_head_output_node,
)
from .embed import (
    Segments,
    analyze_with_segments,
    pool_scores,
    score_segments,
    segment_waveform,
)
from .heads import (
    Cascade,
    HeadDecision,
    HeadSpec,
    decide_multiclass_adaptive,
    decide_multilabel,
    decide_regression,
    head_is_multiclass,
    head_is_multilabel,
    head_is_regression,
    run_head_decision,
)

__all__ = [
    "Cascade",
    "HeadDecision",
    "HeadInfo",
    "HeadOutput",
    "HeadSpec",
    "Segments",
    "Sidecar",
    "analyze_with_segments",
    "decide_multiclass_adaptive",
    "decide_multilabel",
    "decide_regression",
    "discover_heads",
    "get_embedding_output_node",
    "get_head_output_node",
    "head_is_multiclass",
    "head_is_multilabel",
    "head_is_regression",
    "pool_scores",
    "run_head_decision",
    "score_segments",
    "segment_waveform",
]
