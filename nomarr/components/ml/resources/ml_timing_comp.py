"""Timing summary computation for the ML processing pipeline.

Builds a human-readable timing breakdown string from raw per-operation
timings collected during audio file processing.
"""

from __future__ import annotations


def build_timing_summary(
    timings: dict[str, float],
    elapsed_ms: float,
    heads_by_backbone: dict[str, list],
) -> str:
    """Build a compact timing summary string for one processed file.

    Args:
        timings: Per-operation durations in milliseconds, keyed by operation name.
            Expected keys: ``audio_load``, ``emb_wall`` (parallel) or
            ``emb_<backbone>`` (sequential), ``heads_<backbone>``,
            ``mood_aggregation``.
        elapsed_ms: Total wall-clock time for the file in milliseconds.
        heads_by_backbone: Mapping of backbone name → list of head models,
            used only to count heads per backbone for the summary string.

    Returns:
        A compact one-line summary string, e.g.:
        ``"audio=120(12%) emb=450(45%|effnet=450) heads=300(30%|4x300) mood=10(1%)"``

    """

    def _pct(ms: float) -> str:
        return f"{ms / elapsed_ms * 100:.0f}%" if elapsed_ms > 0 else "0%"

    audio_load_ms = timings.get("audio_load", 0)

    # Embedding: use wall time if parallel, else sum of per-backbone times
    emb_per_backbone = {k: v for k, v in timings.items() if k.startswith("emb_") and k != "emb_wall"}
    emb_wall_ms = timings.get("emb_wall", sum(emb_per_backbone.values()))

    # Head: per-backbone wall times (heads_<backbone>), already wall times
    # even when individual heads within ran in parallel
    heads_wall_per_bb = {k: v for k, v in timings.items() if k.startswith("heads_")}
    heads_wall_total = sum(heads_wall_per_bb.values())

    mood_ms = timings.get("mood_aggregation", 0)

    emb_detail = "+".join(f"{k.replace('emb_', '')}={v:.0f}" for k, v in emb_per_backbone.items())

    head_parts: list[str] = []
    for bb_key, bb_wall in heads_wall_per_bb.items():
        bb_name = bb_key.replace("heads_", "")
        bb_head_count = len(heads_by_backbone.get(bb_name, []))
        head_parts.append(f"{bb_head_count}x{bb_wall:.0f}")
    head_detail = "+".join(head_parts)

    return (
        f"audio={audio_load_ms:.0f}({_pct(audio_load_ms)}) "
        f"emb={emb_wall_ms:.0f}({_pct(emb_wall_ms)}|{emb_detail}) "
        f"heads={heads_wall_total:.0f}({_pct(heads_wall_total)}|{head_detail}) "
        f"mood={mood_ms:.0f}({_pct(mood_ms)})"
    )
