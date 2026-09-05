"""CPU bounded exact scorer (Plan D, Phase 2 — P2-S1..P2-S4).

Implements the fixed ledger contract ``score_bounded_exact(...) -> BoundedScoreResult``
(``scripts/embedding_research/CONTRACTS.md`` → "Disposable views and bounded scoring";
DD R12).  It reproduces, chunk-by-chunk, the exact ``max_per_candidate_segment``
semantics whose small full-matrix fixture oracle is
:func:`scoring_harness.score_max_per_candidate_segment` — that oracle is left
untouched and remains authoritative.  This module is a *pure CPU numpy kernel*:

* no DuckDB connection is required for the scoring path;
* no audio / ONNX / CUDA and no file I/O in the hot path (the candidate payload is
  an in-memory ``row_addresses`` + float32-vectors view);
* only the documented primary semantics vocabulary is used — never a generic
  mean/median/max/min/medoid aggregate label.

Semantics reproduced exactly (oracle-equivalent)
------------------------------------------------
The oracle's single ordered comparison has a *source* side (``source_vectors`` /
``source_weights``) and a *candidate* side (``candidate_vectors`` /
``candidate_weights``).  In :func:`score_bounded_exact` the **query** is the source
side and the **candidate view rows** are the candidate side::

    max_cos[b] = max over query rows a of dot(query_a, candidate_row_b)

for each candidate segment ``b``, then the explicit **tie policy** selects the
credited winner source row(s) and the explicit **collision policy** decides which
candidate segments are retained.  Each retained candidate segment contributes once
with its positive weight::

    contribution[b] = candidate_weight[b] * max_cos[b]
    score = sum(contribution[b] for retained b) / sum(candidate_weight[b] for retained b)

Matching the oracle, ``query_weights`` are validated (finite, strictly positive,
length-aligned) but do **not** enter this primary formula — only the candidate-side
weights do (exactly as ``source_weights`` are validated-but-unused inside
``score_max_per_candidate_segment``).  Candidate-side weights come from the
consumed view's optional ``candidate_weights`` (default all-ones when absent).

Ambiguity variants (same vocabulary as the oracle)::

    first_index + retain_all_candidate_segments   (primary, default)
    equal_tie_split + unique_source_max           (documented alternative)

Boundedness (P2-S2 / P2-S4)
---------------------------
The cosine matrix is never materialised in full.  Query rows and candidate rows are
processed in bounded chunks sized from ``query_chunk_size`` / ``candidate_chunk_size``
(or derived from the explicit ``working_memory`` byte budget when those are ``None``).
Each temporary query-x-candidate chunk is reduced and then released — the module never
retains the full ``n_source x n_candidate`` product and the normal path keeps no
per-pair trace.  Only reduced per-candidate scalars (max cosine, winner source index,
tie count — ``O(n_candidate)``) and per-source winner counters (``O(n_source)``) are
retained across chunks, which is the streamed-reduction result, not the product.

``expensive_trace=True`` is an EXPLICIT, labelled debug mode (default off).  It still
honours the same bounded chunk limits, but additionally retains a segment-level trace
(every candidate's contribution, winner/collision metadata and, for split ties, its
tied winner-source set) and sets ``result.trace_retained`` so the caller can see that a
full trace was retained.  The normal path keeps only aggregate summaries.

Working-memory arithmetic (P2-S4, a sizing formula — NOT a measured claim)
-------------------------------------------------------------------------
``working_memory`` is a positive-integer byte budget.  When explicit chunk sizes are
omitted they are derived so that one query-x-candidate cosine chunk (``float64``,
8 bytes/element — the module's arithmetic dtype) fits the budget with both dimensions
geometrically equal::

    chunk = max(1, int(sqrt(working_memory / 8)))

Both ``query_chunk_size`` and ``candidate_chunk_size`` default to that value.  Explicit
chunk sizes override it.  The DD's target bound ``O(n.b.mbar^2.4)`` (n = query/batch
rows, b = candidate block, mbar = mean segment dimension/cardinality term) is treated
strictly as a *sizing formula* recorded for scale planning — this implementation makes
no empirical performance or peak-memory claim.

Determinism / finite / no cross-backbone mixing
-----------------------------------------------
Tie and collision outcomes are deterministic (lowest source index / lowest candidate
index) so Phase 4 golden tests are reproducible.  All emitted values are finite;
  non-finite vectors/weights are rejected explicitly.  An empty candidate view (zero
  searchable rows) is a valid input that yields a finite EMPTY result (``score=0.0``, zero
  retained/dropped candidates) — never NaN/Inf and never a crash; the analyze scheduler
  excludes zero-searchable candidates upstream so it never feeds an empty view here.  This
  kernel has no backbone dimension of its own
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from scripts.embedding_research.scoring_harness import (
    COLLISION_POLICIES as _COLLISION_POLICIES,
)
from scripts.embedding_research.scoring_harness import (
    PRIMARY_COLLISION_POLICY as _PRIMARY_COLLISION_POLICY,
)
from scripts.embedding_research.scoring_harness import (
    PRIMARY_TIE_POLICY as _PRIMARY_TIE_POLICY,
)
from scripts.embedding_research.scoring_harness import (
    TIE_POLICIES as _TIE_POLICIES,
)
from scripts.embedding_research.scoring_harness import (
    variant_name as _variant_name,
)

__all__ = [
    "BoundedScoreResult",
    "BoundedScoreTrace",
    "CandidateSegmentSummary",
    "ScoringCandidateView",
    "SearchViewLike",
    "derive_chunk_sizes",
    "score_bounded_exact",
    "validate_policies",
]

#: Arithmetic dtype for cosine blocks — matches the oracle (float64 matmul), so
#: elementwise dot products (and thus tie/collision outcomes) are oracle-equivalent
#: within documented float tolerance independent of chunk boundaries.
_DTYPE = np.dtype(np.float64)
#: Unit-norm tolerance for validating cosine rows (mirrors the oracle harness).
_UNIT_NORM_ATOL = 1e-6
#: Bytes per cosine element assumed by the documented working-memory derivation.
_DERIVATION_BYTES = 8
#: Non-finite sentinel used for the running per-candidate cosine maximum.
_NEG_INF = -np.inf

#: Default working-memory when callers supply neither chunk sizes nor a budget.
_DEFAULT_WORKING_MEMORY = 32 * 1024 * 1024  # 32 MiB

#: Scoring-input semantics version stamped on every emitted result.  Single global value,
#: equal to ``search_views.SCORING_SEMANTICS_VERSION`` and to the old
#: ``cache_identity.SCORING_SEMANTICS_VERSION``.  It is defined locally so this pure CPU
#: kernel does not import the E-owned ``cache_identity`` module (scheduled for deletion); a
#: contract test (``test_bounded_exact_contract``) pins the equality against the search-view
#: constant so the copies cannot drift unnoticed.
SCORING_SEMANTICS_VERSION = 1

_TIE_POLICIES = tuple(_TIE_POLICIES)
_COLLISION_POLICIES = tuple(_COLLISION_POLICIES)


# ── Validation ────────────────────────────────────────────────────────────────


def validate_policies(*, tie_policy: str, collision_policy: str) -> None:
    """Reject an unlabelled/unknown tie or collision policy."""
    if tie_policy not in _TIE_POLICIES:
        raise ValueError(f"Unknown tie_policy {tie_policy!r}; expected one of {list(_TIE_POLICIES)}")
    if collision_policy not in _COLLISION_POLICIES:
        raise ValueError(f"Unknown collision_policy {collision_policy!r}; expected one of {list(_COLLISION_POLICIES)}")


# ── Candidate view protocol ───────────────────────────────────────────────────


class SearchViewLike(Protocol):
    """The lightweight candidate payload consumed by the bounded scorer.

    Only ``vectors`` and ``row_addresses`` are required (both match Phase 1's
    ``SearchViewRecord`` surface).  Optional attributes enable extra provenance /
    weighting::

    * ``key`` — an object exposing the view keyset (e.g. a record's ``keyset_hash`` /
      ``content_hash``) so the query role identity is carried as provenance;
    * ``candidate_weights`` — per-row candidate-segment weights aligned to
      ``row_addresses`` (default all-ones when absent).
    """

    vectors: np.ndarray
    row_addresses: Any

    @property
    def key(self) -> Any: ...  # pragma: no cover - protocol

    @property
    def candidate_weights(self) -> np.ndarray | None: ...  # pragma: no cover - protocol


@dataclass(frozen=True)
class ScoringCandidateView:
    """A pure, in-memory candidate payload (row_addresses + float32 vectors).

    Lets callers / tests invoke the scorer without a materialised on-disk view.  ``key``
    is optional (used only to surface the view keyset as query/candidate provenance).
    ``candidate_weights`` align to the rows of ``vectors`` (default all-ones).
    """

    vectors: np.ndarray
    row_addresses: tuple[tuple[int, str, int, int], ...] = ()
    key: Any = None
    candidate_weights: np.ndarray | None = None


# ── Result models ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CandidateSegmentSummary:
    """One candidate segment's segment-level contribution.

    Present in full (with ``winner_source_indices``) only under ``expensive_trace``;
    ``tie_count`` is always the number of source rows tied at the cosine maximum so a
    bounded segment-level summary is available even in the normal path.
    """

    candidate_index: int
    candidate_weight: float
    winner_source_index: int
    winner_source_indices: tuple[int, ...] | None
    tie_count: int
    cosine: float
    contribution: float
    collision_group: tuple[int, ...]
    retained: bool
    ambiguity_variant: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_index": int(self.candidate_index),
            "candidate_weight": float(self.candidate_weight),
            "winner_source_index": int(self.winner_source_index),
            "winner_source_indices": (
                [int(i) for i in self.winner_source_indices] if self.winner_source_indices is not None else None
            ),
            "tie_count": int(self.tie_count),
            "cosine": float(self.cosine),
            "contribution": float(self.contribution),
            "collision_group": [int(i) for i in self.collision_group],
            "retained": bool(self.retained),
            "ambiguity_variant": self.ambiguity_variant,
        }


@dataclass(frozen=True)
class BoundedScoreTrace:
    """The segment-level trace retained only when ``expensive_trace=True``.

    One entry per candidate segment — never a per-source-x-candidate pair matrix.
    Retaining it is an explicit, labelled cost (``result.trace_retained``).
    """

    contributions: tuple[CandidateSegmentSummary, ...]
    collisions: tuple[tuple[int, ...], ...]
    winner_counts: tuple[tuple[int, float], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "contributions": [c.to_dict() for c in self.contributions],
            "collisions": [[int(i) for i in group] for group in self.collisions],
            "winner_counts": [[int(s), float(n)] for s, n in self.winner_counts],
        }


@dataclass(frozen=True)
class BoundedScoreResult:
    """Result of one bounded exact score for one query against one candidate view.

    Exposes the finite ``score`` (``numerator / denominator``), the denominator, the
    variant identity (tie/collision policies + ``scoring_semantics_version``), bounded
    segment-level trace summaries (never per-pair in the normal path), query/candidate
    key provenance, and the exact chunk/working-memory configuration that produced the
    result (so a benchmark can record it).
    """

    score: float
    numerator: float
    denominator: float
    finite: bool
    tie_policy: str
    collision_policy: str
    variant: str
    scoring_semantics_version: int
    n_source_rows: int
    n_candidate_rows: int
    #: Per-source winner credit counts over retained candidates (dict form for easy use).
    winner_counts: dict[int, float]
    #: Collision groups (candidate-index tuples sharing a representative winner source).
    collisions: tuple[tuple[int, ...], ...]
    retained_count: int
    dropped_count: int
    #: ``True`` when the caller explicitly requested and we retained a full trace.
    trace_retained: bool
    #: Per-candidate segment summaries (present only when ``trace_retained``).
    trace: BoundedScoreTrace | None
    #: Query-role identity from the view keyset, if the view carries one.
    query_key_provenance: Any
    #: Candidate row addresses (the ``row_addresses`` that produced the result).
    candidate_key_provenance: Any
    #: The effective chunk/working-memory configuration (explicit or derived).
    query_chunk_size: int
    candidate_chunk_size: int
    working_memory: int

    @property
    def retained(self) -> tuple[int, ...]:
        """Indices of retained candidate segments (derived from the trace when present)."""
        if self.trace is None:
            raise ValueError("retained indices require expensive_trace=True")
        return tuple(c.candidate_index for c in self.trace.contributions if c.retained)

    def segment_summary(self) -> dict[str, float]:
        """Bounded, finite-only scalar summary of this result (normal-path surface).

        Returns only scalar aggregates (row counts, numerator/denominator/score,
        collision count, winner count, retained/dropped counts) — never the chunk
        matrices and never per-candidate arrays in the normal path.
        """
        winner_total = sum(float(v) for v in self.winner_counts.values())
        return {
            "score": float(self.score),
            "numerator": float(self.numerator),
            "denominator": float(self.denominator),
            "n_source_rows": float(self.n_source_rows),
            "n_candidate_rows": float(self.n_candidate_rows),
            "collision_count": float(len(self.collisions)),
            "winner_count": float(winner_total),
            "retained_count": float(self.retained_count),
            "dropped_count": float(self.dropped_count),
            "trace_retained": 1.0 if self.trace_retained else 0.0,
            "finite": 1.0 if self.finite else 0.0,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": float(self.score),
            "numerator": float(self.numerator),
            "denominator": float(self.denominator),
            "finite": bool(self.finite),
            "variant": self.variant,
            "tie_policy": self.tie_policy,
            "collision_policy": self.collision_policy,
            "scoring_semantics_version": int(self.scoring_semantics_version),
            "n_source_rows": int(self.n_source_rows),
            "n_candidate_rows": int(self.n_candidate_rows),
            "winner_counts": [[int(s), float(n)] for s, n in sorted(self.winner_counts.items())],
            "collisions": [[int(i) for i in g] for g in self.collisions],
            "retained_count": int(self.retained_count),
            "dropped_count": int(self.dropped_count),
            "trace_retained": bool(self.trace_retained),
            "trace": self.trace.to_dict() if self.trace is not None else None,
            "query_key_provenance": (
                self.query_key_provenance.to_dict() if self.query_key_provenance is not None else None
            ),
            "candidate_key_provenance": (
                list(self.candidate_key_provenance) if self.candidate_key_provenance is not None else None
            ),
            "query_chunk_size": int(self.query_chunk_size),
            "candidate_chunk_size": int(self.candidate_chunk_size),
            "working_memory": int(self.working_memory),
        }


# ── Working-memory arithmetic ─────────────────────────────────────────────────


def _validate_budget(working_memory: int | None) -> int:
    if working_memory is None:
        return _DEFAULT_WORKING_MEMORY
    if isinstance(working_memory, bool) or not isinstance(working_memory, int) or working_memory <= 0:
        raise ValueError("working_memory must be a positive integer byte budget")
    return working_memory


def _validate_chunk(chunk_size: int | None, name: str) -> int | None:
    if chunk_size is None:
        return None
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size <= 0:
        raise ValueError(f"{name} must be a positive integer (number of rows), got {chunk_size!r}")
    return chunk_size


def derive_chunk_sizes(working_memory: int) -> tuple[int, int]:
    """Derive default query/candidate chunk row counts from a byte budget.

    Sizing formula (P2-S4): a single ``float64`` cosine chunk of
    ``query_chunk_size x candidate_chunk_size`` elements occupies
    ``rows * cols * 8`` bytes.  With both dimensions geometrically equal and the whole
    budget dedicated to one chunk::

        chunk = max(1, int(sqrt(working_memory / 8)))

    This is documented sizing arithmetic, not a measured memory or performance claim.
    """
    budget = _validate_budget(working_memory)
    chunk = max(1, int(math.sqrt(budget / _DERIVATION_BYTES)))
    return chunk, chunk


# ── Pure array validation ─────────────────────────────────────────────────────


def _as_f64_vectors(vectors: Any, name: str, *, allow_empty: bool = False) -> np.ndarray:
    arr = np.array(vectors, dtype=np.float64)
    if arr.ndim != 2:
        raise ValueError(f"{name} must be 2-D (rows x dim), got ndim={arr.ndim}")
    if arr.shape[0] == 0 and not allow_empty:
        raise ValueError(f"{name} must have at least one row")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must be finite (no NaN/Inf)")
    norms = np.linalg.norm(arr, axis=1)
    if not np.allclose(norms, 1.0, atol=_UNIT_NORM_ATOL):
        raise ValueError(f"{name} rows must be unit-norm (cosine input)")
    return arr


def _as_f64_weights(weights: Any, n_rows: int, name: str) -> np.ndarray:
    arr = np.array(weights, dtype=np.float64)
    if arr.ndim != 1:
        raise ValueError(f"{name} must be 1-D, got ndim={arr.ndim}")
    if arr.shape[0] != n_rows:
        raise ValueError(f"{name} length {arr.shape[0]} != {n_rows} rows")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must be finite (no NaN/Inf)")
    if not np.all(arr > 0.0):
        raise ValueError(f"{name} must be strictly positive")
    return arr


def _extract_view(view: SearchViewLike) -> tuple[np.ndarray, Any, Any, np.ndarray]:
    vectors = _as_f64_vectors(getattr(view, "vectors", None), "candidate_view.vectors", allow_empty=True)
    row_addresses = getattr(view, "row_addresses", None)
    key = getattr(view, "key", None)
    weights = getattr(view, "candidate_weights", None)
    cw = (
        _as_f64_weights(weights, vectors.shape[0], "candidate_view.candidate_weights")
        if weights is not None
        else np.ones(vectors.shape[0])
    )
    return vectors, row_addresses, key, cw


# ── Internal block reducers ───────────────────────────────────────────────────


def _block_max_and_winner(
    query: np.ndarray,
    cand_block: np.ndarray,
    *,
    query_chunk_size: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return per-candidate-in-block ``(maxcos, rep_winner, tie_count)``.

    Streams query row-chunks twice against *cand_block* (never materialising the full
    query-x-block product at once): the first pass accumulates the running per-candidate
    maximum; the second, knowing the final maximum, finds each candidate's lowest tied
    source row (deterministic first-index winner) and its total tie count.  Temporary
    chunks are released after each reduction.
    """
    k_rows = int(query.shape[0])
    n_cols = int(cand_block.shape[0])
    qcs = query_chunk_size

    # Pass 1: running per-candidate maximum over all query rows.
    running = np.full(n_cols, _NEG_INF, dtype=_DTYPE)
    for q0 in range(0, k_rows, qcs):
        qb = query[q0 : q0 + qcs]
        cos = qb @ cand_block.T  # [qsz, n_cols] float64 — temporary chunk
        np.maximum(running, cos.max(axis=0), out=running)
        del cos

    # Pass 2: lowest tied source index (first_index rep) + tie count per candidate.
    rep = np.zeros(n_cols, dtype=np.int64)
    assigned = np.zeros(n_cols, dtype=bool)
    tie_count = np.zeros(n_cols, dtype=np.int64)
    for q0 in range(0, k_rows, qcs):
        qb = query[q0 : q0 + qcs]
        base = int(q0)
        cos = qb @ cand_block.T  # temporary chunk — released below
        tied = np.isclose(cos, running)  # broadcasting running as a column maxima row
        first = np.argmax(tied, axis=0)  # first True row in this chunk per column
        any_tied = tied.any(axis=0)
        fresh = any_tied & ~assigned
        rep[fresh] = base + first[fresh]
        assigned |= any_tied
        tie_count += tied.sum(axis=0)
        del cos, tied
    return running, rep, tie_count


def _split_winner_credits(
    query: np.ndarray,
    cand_block: np.ndarray,
    cols: np.ndarray,
    maxcos: np.ndarray,
    tie_count: np.ndarray,
    winner_counts: dict[int, float],
    *,
    query_chunk_size: int,
) -> None:
    """Accumulate ``equal_tie_split`` credits (1/k per tied source) into *winner_counts*.

    Only the candidate columns in *cols* (retained candidates of this block, already
    decided) are visited; a final query pass enumerates each retained candidate's tied
    source rows and adds ``1/tie_count`` credit per tied source.  Memory stays bounded
    to the chunk; the per-source counter is ``O(n_source)``.
    """
    k_rows = int(query.shape[0])
    int(cand_block.shape[0])
    qcs = query_chunk_size
    # Local indices of the retained candidate columns.
    local = np.array(cols, dtype=np.int64)
    if local.size == 0:
        return
    # Pre-scale credits so the per-row accumulation is exact-ish.
    inv_k = 1.0 / tie_count[local]
    for q0 in range(0, k_rows, qcs):
        qb = query[q0 : q0 + qcs]
        base = int(q0)
        cos = qb @ cand_block.T  # [qsz, n_cols]
        # Ties for the retained columns only.
        tied = np.isclose(cos[:, local], maxcos[local])
        # rows x retained-cols boolean; need per-retained-col list of tied global rows.
        for r in range(local.size):
            trows = np.nonzero(tied[:, r])[0]
            if trows.size == 0:
                continue
            credit = inv_k[r]
            for tr in trows:
                src = base + int(tr)
                winner_counts[src] = winner_counts.get(src, 0.0) + credit
        del cos, tied


def _enumerate_ties_for_col(
    query: np.ndarray,
    cand_block: np.ndarray,
    col: int,
    max_val: float,
    *,
    query_chunk_size: int,
) -> tuple[int, ...]:
    """Return all tied source rows (ascending) for one candidate column in *cand_block*."""
    k_rows = int(query.shape[0])
    qcs = query_chunk_size
    colvec = cand_block[col]
    hits: list[int] = []
    for q0 in range(0, k_rows, qcs):
        qb = query[q0 : q0 + qcs]
        cos = qb @ colvec  # [qsz]
        tied = np.isclose(cos, max_val)
        hits.extend(int(q0 + i) for i in np.nonzero(tied)[0])
        del cos, tied
    return tuple(sorted(hits))


# ── Main entry point ──────────────────────────────────────────────────────────


def score_bounded_exact(
    query_vectors: Any,
    query_weights: Any,
    candidate_view: SearchViewLike,
    *,
    query_chunk_size: int | None = None,
    candidate_chunk_size: int | None = None,
    working_memory: int | None = None,
    tie_policy: str = _PRIMARY_TIE_POLICY,
    collision_policy: str = _PRIMARY_COLLISION_POLICY,
    expensive_trace: bool = False,
) -> BoundedScoreResult:
    """Exact, bounded, chunk-streamed max-per-candidate-segment score.

    Parameters
    ----------
    query_vectors:
        The **query (source)** segment rows, 2-D unit-norm ``(n_source, D)``.  A single
        query song's rows are passed directly; a bounded query batch is passed as the
        concatenated source rows (chunked internally).  Each source row is a segment.
    query_weights:
        Positive per-row weights aligned to ``query_vectors`` rows.  Validated but not
        used in the primary formula (mirroring the oracle, where source weights do not
        enter ``max_per_candidate_segment``).
    candidate_view:
        An in-memory candidate payload exposing ``vectors`` (float32/float64 ``(n_cand, D)``)
        and ``row_addresses`` (Phase 1 ``SearchViewRecord`` surface), optionally
        ``candidate_weights`` (default all-ones) and ``key`` (view keyset provenance).
    query_chunk_size, candidate_chunk_size:
        Bounded row counts per temporary matmul chunk.  When ``None`` they are derived
        from ``working_memory`` (P2-S4 arithmetic).  Explicit values override the
        derived default.
    working_memory:
        Positive-integer byte budget used to derive default chunk sizes (ignored when
        both chunk sizes are given explicitly).  Surfaced on the result.
    tie_policy:
        ``"first_index"`` (primary) or ``"equal_tie_split"`` (alternative).
    collision_policy:
        ``"retain_all_candidate_segments"`` (primary) or ``"unique_source_max"``
        (alternative).
    expensive_trace:
        Default ``False``.  When ``True`` the segment-level trace is retained and
        ``result.trace_retained`` is set; chunk limits are still honoured.  Off by
        default — the normal path retains no per-candidate trace.

    Returns
    -------
    :class:`BoundedScoreResult` with finite ``score``/``denominator`` and bounded
    segment-level summaries + variant identity + query/candidate provenance + the exact
    chunk configuration.
    """
    validate_policies(tie_policy=tie_policy, collision_policy=collision_policy)

    q = _as_f64_vectors(query_vectors, "query_vectors")
    # Source weights are validated (finite, strictly positive, length-aligned) but, as
    # in the oracle, do not enter the primary max-per-candidate-segment formula.
    _as_f64_weights(query_weights, int(q.shape[0]), "query_weights")
    cand, row_addresses, key, cw = _extract_view(candidate_view)
    m_rows = int(cand.shape[0])
    k_rows = int(q.shape[0])

    qcs = _validate_chunk(query_chunk_size, "query_chunk_size")
    ccs = _validate_chunk(candidate_chunk_size, "candidate_chunk_size")
    budget = _validate_budget(working_memory)
    if qcs is None or ccs is None:
        derived_q, derived_c = derive_chunk_sizes(budget)
        qcs = qcs if qcs is not None else derived_q
        ccs = ccs if ccs is not None else derived_c

    if m_rows == 0:
        # An empty candidate view (no searchable rows) is a valid input and yields a finite,
        # EMPTY result: no comparison is performed, nothing is retained/dropped, score is 0.0
        # (finite) — never NaN/Inf and never a crash.  The analyze scheduler excludes
        # zero-searchable candidates upstream (CONTRACTS §D), so it never feeds an empty view
        # here; this is the scorer's own fail-safe contract for the degenerate empty input.
        empty_trace = BoundedScoreTrace(contributions=(), collisions=(), winner_counts=()) if expensive_trace else None
        return BoundedScoreResult(
            score=0.0,
            numerator=0.0,
            denominator=0.0,
            finite=True,
            tie_policy=tie_policy,
            collision_policy=collision_policy,
            variant=_variant_name(tie_policy, collision_policy),
            scoring_semantics_version=SCORING_SEMANTICS_VERSION,
            n_source_rows=k_rows,
            n_candidate_rows=0,
            winner_counts={},
            collisions=(),
            retained_count=0,
            dropped_count=0,
            trace_retained=bool(expensive_trace),
            trace=empty_trace,
            query_key_provenance=key,
            candidate_key_provenance=row_addresses,
            query_chunk_size=qcs,
            candidate_chunk_size=ccs,
            working_memory=budget,
        )

    # ---- Streaming reduction over candidate blocks --------------------------
    # Per-candidate reduced scalars across ALL candidate rows are retained (O(M)),
    # never the source-x-candidate product.
    maxcos_all = np.empty(m_rows, dtype=_DTYPE)
    rep_all = np.empty(m_rows, dtype=np.int64)
    tie_all = np.empty(m_rows, dtype=np.int64)
    for b0 in range(0, m_rows, ccs):
        b1 = min(b0 + ccs, m_rows)
        cand_block = cand[b0:b1]
        int(cand_block.shape[0])
        maxcos, rep, tie_count = _block_max_and_winner(q, cand_block, query_chunk_size=qcs)
        maxcos_all[b0:b1] = maxcos
        rep_all[b0:b1] = rep
        tie_all[b0:b1] = tie_count

    # ---- Collision grouping / retention (vectorised over reduced O(M) arrays) -
    groups: dict[int, list[int]] = defaultdict(list)
    for ci in range(m_rows):
        groups[int(rep_all[ci])].append(ci)
    collisions = tuple(tuple(sorted(g)) for g in groups.values() if len(g) >= 2)

    if collision_policy == _PRIMARY_COLLISION_POLICY:
        retained_set = set(range(m_rows))
        dropped: set[int] = set()
    else:  # unique_source_max
        retained_set = set()
        for cands in groups.values():
            best = min(cands, key=lambda b: (-float(maxcos_all[b]), b))
            retained_set.add(best)
        dropped = set(range(m_rows)) - retained_set

    # ---- Numerator / denominator over retained candidates --------------------
    numerator = 0.0
    denominator = 0.0
    for ci in range(m_rows):
        if ci in retained_set:
            numerator += float(cw[ci]) * float(maxcos_all[ci])
            denominator += float(cw[ci])
    if denominator <= 0.0:
        raise ValueError("denominator must be positive; no retained candidate segments")

    score = float(numerator / denominator)

    # ---- Winner counts (over retained candidates) ---------------------------
    if tie_policy == _PRIMARY_TIE_POLICY:  # first_index
        winner_counts: dict[int, float] = {}
        for ci in retained_set:
            s = int(rep_all[ci])
            winner_counts[s] = winner_counts.get(s, 0.0) + 1.0
    else:  # equal_tie_split — needs a final per-block query pass over retained candidates
        winner_counts = {}
        for b0 in range(0, m_rows, ccs):
            b1 = min(b0 + ccs, m_rows)
            cand_block = cand[b0:b1]
            cols = np.array([ci - b0 for ci in sorted(retained_set) if b0 <= ci < b1], dtype=np.int64)
            if cols.size == 0:
                continue
            _split_winner_credits(
                q,
                cand_block,
                cols,
                maxcos_all[b0:b1],
                tie_all[b0:b1],
                winner_counts,
                query_chunk_size=qcs,
            )

    # ---- Trace construction (only when expensive_trace) ----------------------
    trace: BoundedScoreTrace | None = None
    if expensive_trace:
        contributions: list[CandidateSegmentSummary] = []
        for b0 in range(0, m_rows, ccs):
            b1 = min(b0 + ccs, m_rows)
            cand_block = cand[b0:b1]
            for col in range(b1 - b0):
                ci = b0 + col
                winner_idx = int(rep_all[ci])
                tied_sources = _enumerate_ties_for_col(q, cand_block, col, float(maxcos_all[ci]), query_chunk_size=qcs)
                is_retained = ci in retained_set
                contributions.append(
                    CandidateSegmentSummary(
                        candidate_index=ci,
                        candidate_weight=float(cw[ci]),
                        winner_source_index=winner_idx,
                        winner_source_indices=tied_sources,
                        tie_count=int(tie_all[ci]),
                        cosine=float(maxcos_all[ci]),
                        contribution=float(cw[ci]) * float(maxcos_all[ci]),
                        collision_group=tuple(sorted(groups[winner_idx])),
                        retained=is_retained,
                        ambiguity_variant=_variant_name(tie_policy, collision_policy),
                    )
                )
        trace = BoundedScoreTrace(
            contributions=tuple(contributions),
            collisions=collisions,
            winner_counts=tuple(sorted(winner_counts.items())),
        )

    finite = bool(
        np.isfinite(score)
        and np.isfinite(numerator)
        and np.isfinite(denominator)
        and np.all(np.isfinite(maxcos_all))
        and np.isfinite(cw).all()
    )

    return BoundedScoreResult(
        score=score,
        numerator=float(numerator),
        denominator=float(denominator),
        finite=finite,
        tie_policy=tie_policy,
        collision_policy=collision_policy,
        variant=_variant_name(tie_policy, collision_policy),
        scoring_semantics_version=SCORING_SEMANTICS_VERSION,
        n_source_rows=k_rows,
        n_candidate_rows=m_rows,
        winner_counts=dict(winner_counts),
        collisions=collisions,
        retained_count=len(retained_set),
        dropped_count=len(dropped),
        trace_retained=bool(expensive_trace),
        trace=trace,
        query_key_provenance=key,
        candidate_key_provenance=row_addresses,
        query_chunk_size=qcs,
        candidate_chunk_size=ccs,
        working_memory=budget,
    )
