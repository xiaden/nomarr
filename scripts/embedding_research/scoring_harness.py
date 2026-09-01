"""Spec-first scoring harness for the follow-on primary experiment.

This module is the authoritative definition of the **max-per-candidate-segment**
deduplicated score that replaces the broad cross-product of weighted aggregates as
the primary semantics for EffNet PTC-versus-global-medoid analysis.

It is *spec-first*: its collision and tie fixtures must pass with exact expected
values and complete traces *before* any formula is treated as authoritative.  It is
pure (reads only its arguments, performs no I/O), deterministic, and finite-only
(no NaN / Infinity in any persisted or emitted value).

Scoring semantics
-----------------
For one ordered song pair the source song supplies ``n_source`` unit-vector
segments and the candidate (target) song supplies ``n_candidate`` unit-vector
segments.  ``C[a, b] = dot(source_a, candidate_b)`` is the cosine similarity between
source segment ``a`` and candidate segment ``b``.  The max-per-candidate-segment
score takes, for each candidate segment ``b``, the *maximum* cosine over source
segments::

    max_cos[b] = max_a C[a, b]

then applies an explicit **tie policy** (which source index is credited as the
winner when several achieve the maximum) and an explicit **collision policy**
(whether every candidate segment is retained or colliding candidates are resolved).
Each retained candidate segment contributes exactly once with its positive
patch-count weight::

    contribution[b] = candidate_weight[b] * max_cos[b]

    score = sum(contribution[b] for retained b) / sum(candidate_weight[b] for retained b)

This never uses an unlabelled mean over the Cartesian matrix.  The three legacy
weighted reductions (``target_weighted``, ``bidirectional_weighted``,
``normalized_mean_pair_weighted``) remain available only as labeled
``legacy_weighted_hypothesis`` comparison formulas; passing their old fixture does
not make them authoritative primary semantics.

Ambiguity variants
------------------
At least two explicit tie/collision ambiguity variants are supported, and their
names, denominators, and retention rules are always exposed in traces/reports:

1. ``first_index + retain_all_candidate_segments`` (primary) — every candidate
   segment contributes once; collisions remain visible via ``collisions`` /
   ``winner_counts``.  The winner of a tied source maximum is the lowest source
   index.
2. ``equal_tie_split + unique_source_max`` — a candidate whose maximum cosine ties
   across multiple source segments splits its winner credit equally among them;
   each source index is then claimed by at most one retained candidate segment
   (the one with the highest cosine; ties broken by lowest candidate index).
   Dropped (colliding) contributions remain in the trace with ``retained=False``
   and are excluded from the numerator and denominator.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from scripts.embedding_research.strategy_binned._weighted import (
    bidirectional_weighted as _bidirectional_weighted,
)
from scripts.embedding_research.strategy_binned._weighted import (
    normalized_mean_pair_weighted as _normalized_mean_pair_weighted,
)
from scripts.embedding_research.strategy_binned._weighted import (
    target_weighted as _target_weighted,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "COLLISION_POLICIES",
    "PRIMARY_COLLISION_POLICY",
    "PRIMARY_TIE_POLICY",
    "TIE_POLICIES",
    "HarnessReport",
    "LegacyWeightedFixture",
    "ScoringFixture",
    "SegmentContribution",
    "SegmentScoreInput",
    "SegmentScoreTrace",
    "run_scoring_harness",
    "score_max_per_candidate_segment",
    "variant_name",
]

# Tolerance for validating unit-norm vector rows.
_UNIT_NORM_ATOL = 1e-6

TIE_POLICIES: tuple[str, ...] = ("first_index", "equal_tie_split")
COLLISION_POLICIES: tuple[str, ...] = ("retain_all_candidate_segments", "unique_source_max")

# The primary (authoritative) ambiguity variant.
PRIMARY_TIE_POLICY = "first_index"
PRIMARY_COLLISION_POLICY = "retain_all_candidate_segments"


def variant_name(tie_policy: str, collision_policy: str) -> str:
    """Canonical, unambiguous name for a tie/collision variant.

    No variant is hidden behind a generic ``mean``/``median``/``max``/``min``/
    ``medoid`` label — every variant is named by its explicit policies.
    """
    return f"max_per_candidate_segment({tie_policy}+{collision_policy})"


# ────────────────────────────────────────────────────────────────────────────────
# Data models
# ────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SegmentScoreInput:
    """Immutable, co-indexed unit-vector arrays for one ordered song pair.

    ``source_vectors`` and ``candidate_vectors`` are 2-D unit-norm arrays sharing a
    common trailing dimension.  ``source_weights`` / ``candidate_weights`` are the
    positive temporal patch-count weights, one per segment, aligned to the rows of
    the matching vector array.  Optional ``source_ids`` / ``candidate_ids`` are
    aligned label tuples (one entry per row).

    Validation happens at this pure-function boundary: wrong ndim, mismatched
    trailing dimensions, non-unit-norm rows, non-finite values, non-positive
    weights, and mismatched id/weight lengths all raise ``ValueError``.
    """

    source_vectors: np.ndarray
    candidate_vectors: np.ndarray
    source_weights: np.ndarray
    candidate_weights: np.ndarray
    source_ids: tuple[str, ...] | None = None
    candidate_ids: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        # Copy before freezing: ``np.asarray(dtype=float64)`` would return the
        # caller's own array when it is already float64, and the later
        # ``setflags(write=False)`` would make that caller-owned array
        # read-only — an observable side effect on the caller.  These always
        # copy so the stored float64 arrays are exclusively ours to freeze.
        sv = np.array(self.source_vectors, dtype=np.float64, copy=True)
        cv = np.array(self.candidate_vectors, dtype=np.float64, copy=True)
        sw = np.array(self.source_weights, dtype=np.float64, copy=True)
        cw = np.array(self.candidate_weights, dtype=np.float64, copy=True)

        if sv.ndim != 2:
            raise ValueError(f"source_vectors must be 2-D, got ndim={sv.ndim}")
        if cv.ndim != 2:
            raise ValueError(f"candidate_vectors must be 2-D, got ndim={cv.ndim}")
        if sv.shape[0] == 0 or cv.shape[0] == 0:
            raise ValueError("source_vectors and candidate_vectors must each have at least one row")
        if sv.shape[1] != cv.shape[1]:
            raise ValueError(f"vector dimension mismatch: source {sv.shape[1]} != candidate {cv.shape[1]}")
        if sw.ndim != 1 or cw.ndim != 1:
            raise ValueError("source_weights and candidate_weights must be 1-D")
        if sw.shape[0] != sv.shape[0]:
            raise ValueError(f"source_weights length {sw.shape[0]} != n_source rows {sv.shape[0]}")
        if cw.shape[0] != cv.shape[0]:
            raise ValueError(f"candidate_weights length {cw.shape[0]} != n_candidate rows {cv.shape[0]}")
        if not np.all(np.isfinite(sv)) or not np.all(np.isfinite(cv)):
            raise ValueError("vectors must be finite (no NaN/Inf)")
        if not np.all(np.isfinite(sw)) or not np.all(np.isfinite(cw)):
            raise ValueError("weights must be finite (no NaN/Inf)")
        if not np.all(sw > 0.0) or not np.all(cw > 0.0):
            raise ValueError("patch-count weights must be strictly positive")

        sv_norm = np.linalg.norm(sv, axis=1)
        if not np.allclose(sv_norm, 1.0, atol=_UNIT_NORM_ATOL):
            raise ValueError("source_vectors rows must be unit-norm")
        cv_norm = np.linalg.norm(cv, axis=1)
        if not np.allclose(cv_norm, 1.0, atol=_UNIT_NORM_ATOL):
            raise ValueError("candidate_vectors rows must be unit-norm")

        if self.source_ids is not None and len(self.source_ids) != sv.shape[0]:
            raise ValueError(f"source_ids length {len(self.source_ids)} != n_source rows {sv.shape[0]}")
        if self.candidate_ids is not None and len(self.candidate_ids) != cv.shape[0]:
            raise ValueError(f"candidate_ids length {len(self.candidate_ids)} != n_candidate rows {cv.shape[0]}")

        # Immutability: store read-only float64 copies so callers cannot mutate.
        sv.setflags(write=False)
        cv.setflags(write=False)
        sw.setflags(write=False)
        cw.setflags(write=False)
        object.__setattr__(self, "source_vectors", sv)
        object.__setattr__(self, "candidate_vectors", cv)
        object.__setattr__(self, "source_weights", sw)
        object.__setattr__(self, "candidate_weights", cw)
        object.__setattr__(
            self,
            "source_ids",
            tuple(self.source_ids) if self.source_ids is not None else None,
        )
        object.__setattr__(
            self,
            "candidate_ids",
            tuple(self.candidate_ids) if self.candidate_ids is not None else None,
        )

    @property
    def n_source(self) -> int:
        return int(self.source_vectors.shape[0])

    @property
    def n_candidate(self) -> int:
        return int(self.candidate_vectors.shape[0])


@dataclass(frozen=True)
class SegmentContribution:
    """One auditable record per candidate segment.

    ``winner_source_indices`` lists every source segment achieving the maximum
    cosine for this candidate (the tie group).  ``winner_source_index`` is the
    deterministic representative winner after the tie policy (the lowest tied
    source index; an explicit split tie is visible through ``winner_source_indices``
    and the fractional ``winner_counts`` in the trace).  ``contribution`` is the
    candidate-weight-weighted cosine; it is only counted in the numerator when
    ``retained`` is True (a dropped colliding candidate still records its
    contribution in the trace).
    """

    candidate_index: int
    candidate_weight: float
    winner_source_indices: tuple[int, ...]
    winner_source_index: int
    cosine: float
    contribution: float
    collision_group: tuple[int, ...]
    retained: bool
    ambiguity_variant: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_index": int(self.candidate_index),
            "candidate_weight": float(self.candidate_weight),
            "winner_source_indices": [int(i) for i in self.winner_source_indices],
            "winner_source_index": int(self.winner_source_index),
            "cosine": float(self.cosine),
            "contribution": float(self.contribution),
            "collision_group": [int(i) for i in self.collision_group],
            "retained": bool(self.retained),
            "ambiguity_variant": self.ambiguity_variant,
        }


@dataclass(frozen=True)
class SegmentScoreTrace:
    """JSON-safe pair score and all provenance required to reproduce it.

    ``score = numerator / denominator``.  ``collisions`` exposes the collision
    groups (tuples of candidate indices sharing a representative winner source,
    only groups of size >= 2).  ``winner_counts`` is a sorted tuple of
    ``(source_index, count)`` pairs over retained candidate segments, where a split
    tie yields fractional counts.
    """

    score: float
    numerator: float
    denominator: float
    contributions: tuple[SegmentContribution, ...]
    collisions: tuple[tuple[int, ...], ...]
    winner_counts: tuple[tuple[int, float], ...]
    variant: str
    tie_policy: str
    collision_policy: str
    finite: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": float(self.score),
            "numerator": float(self.numerator),
            "denominator": float(self.denominator),
            "contributions": [c.to_dict() for c in self.contributions],
            "collisions": [[int(i) for i in group] for group in self.collisions],
            "winner_counts": [[int(s), float(n)] for s, n in self.winner_counts],
            "variant": self.variant,
            "tie_policy": self.tie_policy,
            "collision_policy": self.collision_policy,
            "finite": bool(self.finite),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


@dataclass(frozen=True)
class ScoringFixture:
    """A named deterministic fixture for the max-per-candidate score.

    ``expected_maxima`` is the per-candidate maximum source cosine, in candidate
    order.  ``expected_collisions`` are the expected collision groups.  ``expected_retain_all_score``
    pins the primary-variant score.  ``expected_unique_max_score`` optionally pins
    the ``equal_tie_split + unique_source_max`` variant score.
    """

    name: str
    input: SegmentScoreInput
    expected_maxima: tuple[float, ...]
    expected_collisions: tuple[tuple[int, ...], ...]
    expected_retain_all_score: float
    expected_unique_max_score: float | None = None


@dataclass(frozen=True)
class LegacyWeightedFixture:
    """A named deterministic fixture for the three legacy weighted reductions.

    ``similarity`` is a 2-D source-x-target similarity matrix; ``source_weights``
    and ``target_weights`` are positive patch-count weights.  These reductions are
    ``legacy_weighted_hypothesis`` comparison formulas only — passing their old
    fixture does not make them authoritative primary semantics.
    """

    name: str
    similarity: np.ndarray
    source_weights: np.ndarray
    target_weights: np.ndarray

    def values(self) -> dict[str, float]:
        s = self.similarity
        wa = self.source_weights
        wt = self.target_weights
        return {
            "target_weighted": float(_target_weighted(s, wt)),
            "normalized_mean_pair_weighted": float(_normalized_mean_pair_weighted(s, wa, wt)),
            "bidirectional_weighted": float(_bidirectional_weighted(s, s.T, wt, wa)),
        }


@dataclass(frozen=True)
class HarnessReport:
    """Deterministic execution report for the scoring harness.

    ``traces`` maps ``variant -> fixture_name -> SegmentScoreTrace``.
    ``legacy_weighted`` maps the three legacy reduction names to their fixture
    values (labeled comparison hypotheses).  ``expected`` pins the fixture maxima
    and retain-all scores.  ``comparisons`` gives a compact per-variant/per-fixture
    summary (score, numerator, denominator, retained/dropped counts).  ``finite``
    and ``deterministic`` are global gates over every executed variant/fixture.
    """

    fixtures: tuple[str, ...]
    variants: tuple[str, ...]
    traces: dict[str, dict[str, SegmentScoreTrace]]
    legacy_weighted: dict[str, float]
    expected: dict[str, dict[str, Any]]
    invariants: tuple[str, ...]
    comparisons: dict[str, dict[str, dict[str, Any]]]
    finite: bool
    deterministic: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixtures": list(self.fixtures),
            "variants": list(self.variants),
            "traces": {
                variant: {name: trace.to_dict() for name, trace in by_fx.items()}
                for variant, by_fx in self.traces.items()
            },
            "legacy_weighted": {k: float(v) for k, v in self.legacy_weighted.items()},
            "expected": self.expected,
            "invariants": list(self.invariants),
            "comparisons": self.comparisons,
            "finite": bool(self.finite),
            "deterministic": bool(self.deterministic),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)


# ────────────────────────────────────────────────────────────────────────────────
# Primary score
# ────────────────────────────────────────────────────────────────────────────────


def score_max_per_candidate_segment(
    input: SegmentScoreInput,
    *,
    tie_policy: str = PRIMARY_TIE_POLICY,
    collision_policy: str = PRIMARY_COLLISION_POLICY,
) -> SegmentScoreTrace:
    """Compute the max-per-candidate-segment deduplicated score for one ordered pair.

    For each candidate segment take the maximum source-segment cosine, apply the
    explicit tie policy, count/report source-winner collisions, and contribute that
    candidate segment once with its positive patch-count weight.  It never uses an
    unlabelled mean/median/max/min/medoid aggregate over the Cartesian matrix.

    Parameters
    ----------
    input:
        The validated, co-indexed unit-vector song pair.
    tie_policy:
        ``"first_index"`` (primary) credits the lowest source index on a tied source
        maximum; ``"equal_tie_split"`` splits the winner credit equally among all
        tied source indices (visible as fractional ``winner_counts``).
    collision_policy:
        ``"retain_all_candidate_segments"`` (primary) retains every candidate segment
        and contributes it once; ``"unique_source_max"`` retains at most one candidate
        segment per source index (the highest-cosine one, ties by lowest candidate
        index) and records dropped contributions with ``retained=False``.

    Returns a ``SegmentScoreTrace`` whose every field is finite and JSON-safe.
    """
    if tie_policy not in TIE_POLICIES:
        raise ValueError(f"Unknown tie_policy {tie_policy!r}; expected one of {list(TIE_POLICIES)}")
    if collision_policy not in COLLISION_POLICIES:
        raise ValueError(f"Unknown collision_policy {collision_policy!r}; expected one of {list(COLLISION_POLICIES)}")

    sv = input.source_vectors
    cv = input.candidate_vectors
    cw = input.candidate_weights
    n_cand = int(cv.shape[0])
    vname = variant_name(tie_policy, collision_policy)

    # Cosine matrix C[a, b] over unit vectors (values in [-1, 1]).
    cos = sv @ cv.T  # shape (n_source, n_candidate), float64
    if not np.all(np.isfinite(cos)):
        raise ValueError("cosine matrix contains non-finite values")

    max_cos = cos.max(axis=0)  # per-candidate maximum over source segments
    if not np.all(np.isfinite(max_cos)):
        raise ValueError("cosine maxima contain non-finite values")

    # Winning source indices (tie group) per candidate.
    winning_sources: list[tuple[int, ...]] = []
    for b in range(n_cand):
        tied = tuple(int(i) for i in np.where(np.isclose(cos[:, b], max_cos[b]))[0])
        winning_sources.append(tied)
    # Deterministic representative winner (lowest tied source index) per candidate.
    rep_winners = [ws[0] for ws in winning_sources]

    def credits_for(b: int) -> dict[int, float]:
        if tie_policy == "first_index":
            return {rep_winners[b]: 1.0}
        # equal_tie_split
        k = len(winning_sources[b])
        return dict.fromkeys(winning_sources[b], 1.0 / k)

    # Collision groups over all candidate segments sharing a representative winner.
    rep_groups: dict[int, list[int]] = {}
    for b in range(n_cand):
        rep_groups.setdefault(rep_winners[b], []).append(b)
    collisions = tuple(tuple(sorted(group)) for group in rep_groups.values() if len(group) >= 2)

    # Collision policy: which candidate segments are retained.
    if collision_policy == "retain_all_candidate_segments":
        retained: set[int] = set(range(n_cand))
    else:  # unique_source_max: at most one retained candidate per source.
        retained = set()
        for cands in rep_groups.values():
            best = min(cands, key=lambda b: (-max_cos[b], b))
            retained.add(best)

    # winner_counts over retained candidate segments (fractional for split ties).
    counts: dict[int, float] = {}
    for b in retained:
        for s, credit in credits_for(b).items():
            counts[s] = counts.get(s, 0.0) + credit
    winner_counts = tuple(sorted(counts.items()))

    contributions: list[SegmentContribution] = []
    numerator = 0.0
    denominator = 0.0
    for b in range(n_cand):
        value = float(cw[b] * max_cos[b])
        is_retained = b in retained
        contributions.append(
            SegmentContribution(
                candidate_index=b,
                candidate_weight=float(cw[b]),
                winner_source_indices=winning_sources[b],
                winner_source_index=rep_winners[b],
                cosine=float(max_cos[b]),
                contribution=value,
                collision_group=tuple(sorted(rep_groups[rep_winners[b]])),
                retained=is_retained,
                ambiguity_variant=vname,
            )
        )
        if is_retained:
            numerator += value
            denominator += float(cw[b])

    if denominator <= 0.0:
        raise ValueError("denominator must be positive; no retained candidate segments")

    score = float(numerator / denominator)
    finite = bool(
        np.isfinite(score)
        and np.isfinite(numerator)
        and np.isfinite(denominator)
        and all(np.isfinite(c.cosine) and np.isfinite(c.contribution) for c in contributions)
    )

    return SegmentScoreTrace(
        score=score,
        numerator=float(numerator),
        denominator=float(denominator),
        contributions=tuple(contributions),
        collisions=collisions,
        winner_counts=winner_counts,
        variant=vname,
        tie_policy=tie_policy,
        collision_policy=collision_policy,
        finite=finite,
    )


# ────────────────────────────────────────────────────────────────────────────────
# Harness driver
# ────────────────────────────────────────────────────────────────────────────────


def _summarize(trace: SegmentScoreTrace) -> dict[str, Any]:
    retained = [c for c in trace.contributions if c.retained]
    dropped = [c for c in trace.contributions if not c.retained]
    return {
        "score": trace.score,
        "numerator": trace.numerator,
        "denominator": trace.denominator,
        "variant": trace.variant,
        "retained": [c.candidate_index for c in retained],
        "dropped": [c.candidate_index for c in dropped],
        "winner_counts": [[int(s), float(n)] for s, n in trace.winner_counts],
    }


def run_scoring_harness(
    fixtures: Sequence[ScoringFixture],
    variants: Sequence[tuple[str, str]],
    *,
    legacy_fixtures: Sequence[LegacyWeightedFixture] | None = None,
) -> HarnessReport:
    """Execute deterministic fixtures and return a full, auditable harness report.

    For every ``(tie_policy, collision_policy)`` variant it runs every fixture and
    collects the trace; each variant/fixture is re-run several times to prove
    determinism.  It also executes the three legacy weighted reductions over the
    supplied legacy fixtures (labeled comparison hypotheses).  The returned report
    carries expected values, traces, invariants, variant comparisons, and global
    ``finite`` / ``deterministic`` gates.
    """
    fixture_names = tuple(fx.name for fx in fixtures)
    variant_names = tuple(variant_name(tp, cp) for tp, cp in variants)

    traces: dict[str, dict[str, SegmentScoreTrace]] = {vn: {} for vn in variant_names}
    comparisons: dict[str, dict[str, dict[str, Any]]] = {vn: {} for vn in variant_names}
    finite = True
    deterministic = True

    for (tp, cp), vn in zip(variants, variant_names, strict=False):
        for fx in fixtures:
            trace = score_max_per_candidate_segment(fx.input, tie_policy=tp, collision_policy=cp)
            traces[vn][fx.name] = trace
            comparisons[vn][fx.name] = _summarize(trace)
            if not trace.finite:
                finite = False
            # Determinism: re-run several times; identical JSON means reproducible.
            canonical = trace.to_json()
            for _ in range(3):
                rerun = score_max_per_candidate_segment(fx.input, tie_policy=tp, collision_policy=cp)
                if rerun.to_json() != canonical:
                    deterministic = False

    legacy_values: dict[str, float] = {}
    if legacy_fixtures:
        for lf in legacy_fixtures:
            for name, value in lf.values().items():
                legacy_values[f"{lf.name}:{name}"] = value

    expected: dict[str, dict[str, Any]] = {
        fx.name: {
            "expected_maxima": list(fx.expected_maxima),
            "expected_collisions": [list(g) for g in fx.expected_collisions],
            "expected_retain_all_score": fx.expected_retain_all_score,
            "expected_unique_max_score": fx.expected_unique_max_score,
        }
        for fx in fixtures
    }

    invariants = (
        "max-per-candidate uses the per-candidate maximum source cosine",
        "no unlabelled Cartesian mean/median/max/min/medoid aggregate is used",
        "legacy weighted reductions are labeled comparison hypotheses, not primary semantics",
        "all outputs are finite (no NaN/Inf)",
        "every variant is deterministic across repeated runs",
        "collision groups, winner indices, weights, cosine maxima, retention, and "
        "numeric contributions are all exposed in the trace",
    )

    return HarnessReport(
        fixtures=fixture_names,
        variants=variant_names,
        traces=traces,
        legacy_weighted=legacy_values,
        expected=expected,
        invariants=invariants,
        comparisons=comparisons,
        finite=finite,
        deterministic=deterministic,
    )
