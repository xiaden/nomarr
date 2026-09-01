"""Module-level constants derived from research config TOML."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as _np

from scripts.embedding_research.helpers.toml import load_research_config as _load_research_config

if TYPE_CHECKING:
    from collections.abc import Callable as _Callable
    from collections.abc import Iterable as _Iterable

_cfg = _load_research_config()

_ALLOWED_REP_TYPES: tuple[str, ...] = ("mean", "median", "medoid", "max", "min")
# Part B: only the weighted directional reductions are supported.  Legacy
# generic reductions (mean/median/max/min) and agg_method=medoid are rejected
# at this validation boundary (they are absent from the allowed set).
_ALLOWED_AGG_METHODS: tuple[str, ...] = (
    "target_weighted",
    "bidirectional_weighted",
    "normalized_mean_pair_weighted",
)

# Follow-on primary scoring semantics (Phase 2).  ``max_per_candidate_segment``
# is the authoritative PRIMARY score variant; the three Part B reductions remain
# implemented and numerically tested but are labelled legacy weighted hypothesis
# comparison formulas — opt-in only, never authoritative primary semantics.
# A generic mean/median/max/min/medoid aggregate must never re-enter as a score
# variant (``validate_score_variant`` enforces this at the request boundary).
_ALLOWED_SCORE_VARIANTS: tuple[str, ...] = (
    "max_per_candidate_segment",
    *_ALLOWED_AGG_METHODS,
)
PRIMARY_SCORE_VARIANT: str = "max_per_candidate_segment"

# Generic aggregate names forbidden as a scoring method anywhere in the research
# package.  Rep types may still use mean/median/max/min as *representations*.
_FORBIDDEN_SCORE_VARIANTS: frozenset[str] = frozenset({"mean", "median", "max", "min", "medoid"})


def validate_score_variant(name: str) -> str:
    """Validate a score-variant name against the allowed scoring surface.

    Rejects unknown names and, critically, any unlabelled generic aggregate
    (``mean`` / ``median`` / ``max`` / ``min`` / ``medoid``) so it can never
    re-enter as a primary scoring method.
    """
    if name not in _ALLOWED_SCORE_VARIANTS:
        if name in _FORBIDDEN_SCORE_VARIANTS:
            raise ValueError(
                f"score_variant={name!r} is a generic aggregate and is not a labelled scoring "
                "method; an unlabelled generic mean/median/max/min/medoid aggregate must not "
                "re-enter. Use one of "
                f"{list(_ALLOWED_SCORE_VARIANTS)} (or rep_type=medoid for a representation)."
            )
        raise ValueError(f"Unknown score_variant {name!r}. Allowed: {list(_ALLOWED_SCORE_VARIANTS)}")
    return name


def _validated_choices(name: str, values: _Iterable[str], allowed: tuple[str, ...]) -> list[str]:
    out = [str(v) for v in values]
    bad = sorted({v for v in out if v not in allowed})
    if bad:
        raise ValueError(f"Unknown {name}: {bad}. Allowed: {list(allowed)}")
    return out


# AGG_METHODS sources from the labelled ``[pooling.hypotheses]`` weighted-reductions
# block (the legacy weighted hypothesis declarations) when present; when that key is
# absent it falls back to the hardcoded canonical list (identical values).  This keeps
# the code's source in step with CONTRACTS.md.  ``pooling.agg_methods`` is not a
# recognized key.
AGG_METHODS: list[str] = _validated_choices(
    "pooling.hypotheses.weighted_reductions",
    _cfg.get("pooling", {})
    .get("hypotheses", {})
    .get(
        "weighted_reductions",
        ["target_weighted", "bidirectional_weighted", "normalized_mean_pair_weighted"],
    ),
    _ALLOWED_AGG_METHODS,
)

# Full scoring surface actually evaluated for binned analysis: the primary
# ``max_per_candidate_segment`` variant plus any weighted hypotheses.  When the
# config does not restrict ``pooling.score_variants`` (Phase 3 owns the default
# config), the primary variant is evaluated together with the three weighted
# reductions so the hypothesis path remains exercised.
_configured_score_variants = _cfg.get("pooling", {}).get("score_variants")
if _configured_score_variants:
    SCORE_VARIANTS: list[str] = _validated_choices(
        "pooling.score_variants",
        _configured_score_variants,
        _ALLOWED_SCORE_VARIANTS,
    )
else:
    SCORE_VARIANTS = [PRIMARY_SCORE_VARIANT, *AGG_METHODS]
REP_TYPES: list[str] = _validated_choices(
    "pooling.rep_types",
    _cfg.get("pooling", {}).get("rep_types", ["mean", "median", "max", "min"]),
    _ALLOWED_REP_TYPES,
)

if "medoid" in AGG_METHODS:
    raise ValueError(
        "agg_method=medoid is not implemented; supported weighted reductions are "
        "target_weighted, bidirectional_weighted, normalized_mean_pair_weighted. "
        "rep_type=medoid remains a valid representation, not an aggregation method."
    )

SIM_METRICS: list[str] = _cfg.get("similarity", {}).get("metrics", ["cosine"])

_BACKBONE_SR: int = 16_000
_EXPECTED_ROWS_PER_CONFIG = len(REP_TYPES) * len(REP_TYPES) * len(SIM_METRICS) * len(AGG_METHODS)

_BIN_POOL_STRATEGIES: dict[str, _Callable[[_np.ndarray], _np.ndarray]] = {
    "mean": lambda x: x.mean(axis=0).astype(_np.float32),
    # coordinate-wise median (synthetic, not necessarily an observed segment row)
    "median": lambda x: _np.median(x, axis=0).astype(_np.float32),
    # medoid: actual observed patch closest to the centroid (not synthetic)
    "medoid": lambda x: x[int(_np.argmin(_np.linalg.norm(x - x.mean(axis=0), axis=1)))].astype(_np.float32),
    "max": lambda x: x.max(axis=0).astype(_np.float32),
    "min": lambda x: x.min(axis=0).astype(_np.float32),
}
