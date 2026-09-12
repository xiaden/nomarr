"""Report identity and baseline delta construction for research evaluation.

Baseline values are produced by the geometry analysis phase; this module only
matches persisted evaluation rows and emits finite delta diagnostics.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

    import pandas as pd

__all__ = [
    "BASELINE_DELTA_COLUMNS",
    "GLOBAL_MEDOID_STRATEGY_KEY",
    "MEDOID_STRATEGY_TYPE",
    "BaselineDeltaResult",
    "build_baseline_delta_rows",
    "medoid_strategy_key_for",
]


# --------------------------------------------------------------------------- #
# Report identity                                                              #
# --------------------------------------------------------------------------- #
def medoid_strategy_key_for(backbone: str) -> str:
    """The observed global-medoid report identity for ``backbone`` (``global_pool:{backbone}:medoid``).

    ``GLOBAL_MEDOID_STRATEGY_KEY`` is ``medoid_strategy_key_for("effnet")``.  A per-cell
    medoid baseline row carries ``strategy_key == medoid_strategy_key_for(backbone)`` for
    that cell's backbone; build_baseline_delta_rows keys baseline rows by this exact
    identity (never the lowest-scoring class).
    """
    return f"global_pool:{backbone}:medoid"


#: Active report identity restored for the required EffNet observed baseline (not a cache).
GLOBAL_MEDOID_STRATEGY_KEY: str = "global_pool:effnet:medoid"

#: ``analyze_metrics.strategy_type`` under which the analyze phase persists the observed
#: global-medoid baseline rows.  Deliberately DISTINCT from the per-representation winner
#: strategy type so ``report._retrieval.query_analyze_metrics`` keeps excluding them from
#: ``section_analysis`` while the winners loader reads them through a distinct path.
MEDOID_STRATEGY_TYPE: str = "global_pool"


# --------------------------------------------------------------------------- #
# Baseline + delta row builder                                                #
# --------------------------------------------------------------------------- #
#: Columns emitted by :func:`build_baseline_delta_rows` (one row per
#: ``(backbone, sim_metric, k, metric)`` cell that has a finite medoid baseline AND at
#: least one finite segmented result sharing that exact scope).
BASELINE_DELTA_COLUMNS: list[str] = [
    "backbone",
    "sim_metric",
    "k",
    "metric",
    "n_segmented_classes",
    "baseline_strategy_key",
    "baseline_value",
    "winner_strategy_key",
    "winner_value",
    "delta",
]


#: Per-ruler ruler-evaluable-query COUNT cells (the ``n_queries_*`` EAV rows each segmented-class
#: writer AND the medoid-baseline writer emit).  These are query counts, not scored retrieval
#: cells, so they are excluded from the baseline/winner delta machinery in
#: :func:`build_baseline_delta_rows` — no ``n_queries_*`` medoid key ever enters winner-delta logic.
_NON_SCORED_COUNT_METRICS: frozenset[str] = frozenset({"n_queries_artist", "n_queries_genre", "n_queries_head"})


def _is_finite(v: Any) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return not (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))
    return False


def _refuse_non_finite(values: list[float], context: str) -> None:
    """Fail closed on a present non-finite baseline/segmented value (never an infinite delta)."""
    for v in values:
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            raise ValueError(f"{context} carries a non-finite value ({v!r}); baseline refuses to emit")


#: Per-row evaluation-corpus identity columns (when present on the decoded frame) that the
#: matching-only delta gate reads.  They mirror the ``evaluation_corpus_*`` keys persisted on
#: each ``analyze_scope_v2`` provenance line (execution-reporting-repair Plan A P2-S3), plus
#: the COMPLETE corpus identity/evidence extensions (Plan C Phase 1): semantics/version, the
#: eligible flag, exact digest proof of the eligible + requested membership sets, the
#: observation-binding digest the corpus was resolved against, and explicit completeness +
#: integrity self-check fields.  The equality gate compares EVERY carried field, so an altered
#: membership or observation binding that keeps an equal-looking ``corpus_hash``/``count`` is
#: still detected as unequal.  A frame row that carries NO corpus identity (no such columns /
#: empty hash) is never a structural-match candidate: it is surfaced as an incomplete
#: diagnostic (see :func:`build_baseline_delta_rows`).
CORPUS_IDENTITY_COLUMNS: tuple[str, ...] = (
    "evaluation_corpus_hash",
    "evaluation_corpus_count",
    "evaluation_corpus_comparable",
    "evaluation_corpus_missing_count",
    "evaluation_corpus_missing_digest",
    "evaluation_corpus_semantics_version",
    "evaluation_corpus_eligible",
    "evaluation_corpus_eligible_digest",
    "evaluation_corpus_requested_count",
    "evaluation_corpus_requested_digest",
    "evaluation_corpus_observation_digest",
    "evaluation_corpus_complete",
    "evaluation_corpus_integrity",
)

#: The persisted corpus keys whose equality the matching gate compares (all of
#: :data:`CORPUS_IDENTITY_COLUMNS`).  Each is either a scalar identity field or an exact
#: digest proof over a membership / observation-binding set.
_CORPUS_MISMATCH_LABELS: tuple[tuple[str, str], ...] = (
    ("evaluation_corpus_hash", "corpus hash"),
    ("evaluation_corpus_count", "eligible count"),
    ("evaluation_corpus_comparable", "comparability"),
    ("evaluation_corpus_missing_count", "missing count"),
    ("evaluation_corpus_missing_digest", "missing evidence digest"),
    ("evaluation_corpus_semantics_version", "semantics version"),
    ("evaluation_corpus_eligible", "eligible flag"),
    ("evaluation_corpus_eligible_digest", "eligible membership digest"),
    ("evaluation_corpus_requested_count", "requested count"),
    ("evaluation_corpus_requested_digest", "requested membership digest"),
    ("evaluation_corpus_observation_digest", "observation-binding digest"),
    ("evaluation_corpus_complete", "completeness marker"),
    ("evaluation_corpus_integrity", "integrity self-check"),
)


@dataclass(frozen=True)
class BaselineDeltaResult:
    """Structured result of :func:`build_baseline_delta_rows`.

    ``rows`` are the matched per-(backbone, sim_metric, k, metric) baseline/winner/delta
    records (:data:`BASELINE_DELTA_COLUMNS` each) — produced ONLY when the observed-medoid
    baseline and the winning segmented class share an equal, comparable, finite evaluation
    corpus.  ``incomplete`` are surfaced diagnostics for representations that could NOT be
    compared (population mismatch with the baseline, non-comparability, a one-sided corpus
    identity, or both sides identity-less), each retaining the representation's strategy key,
    cell provenance, and its count/hash/missing evidence so a caller never mistakes a silent
    partial comparison for a matched delta.  The observed baseline is never a winner candidate
    and never yields an incomplete row against itself.
    """

    rows: tuple[Mapping[str, object], ...]
    incomplete: tuple[Mapping[str, object], ...]


@dataclass(frozen=True)
class _CorpusIdentity:
    """The decoded per-row evaluation-corpus identity the delta gate compares.

    Carries EVERY persisted corpus identity/evidence field (the hash/count/comparability/
    missing evidence plus the Plan C Phase 1 semantics/eligible/digest-proof/completeness/integrity
    extensions).  A field is ``None`` (absent) when the row carries no value for it.
    """

    fields: Mapping[str, Any]
    hash: str

    @property
    def comparable(self) -> bool:
        return bool(self.fields.get("evaluation_corpus_comparable", False))

    @property
    def count(self) -> int:
        return int(self.fields.get("evaluation_corpus_count") or 0)

    @property
    def missing_count(self) -> int:
        return int(self.fields.get("evaluation_corpus_missing_count") or 0)

    @property
    def missing_digest(self) -> str | None:
        return self.fields.get("evaluation_corpus_missing_digest")

    def mismatched_fields(self, other: _CorpusIdentity) -> list[str]:
        """Human labels of corpus identity/evidence fields that differ (or are one-sided).

        A field is a mismatch when BOTH sides carry a value and they differ, OR when exactly one
        side carries a value (present-vs-absent = unequal/truncated evidence).  Two genuinely
        equal complete identities (every carried value equal) yield an empty list.
        """
        out: list[str] = []
        for key, label in _CORPUS_MISMATCH_LABELS:
            a = self.fields.get(key)
            b = other.fields.get(key)
            if a is None and b is None:
                continue
            if a is None or b is None:
                out.append(f"{label} present on only one side")
            elif a != b:
                out.append(f"{label} differs ({a!r} vs {b!r})")
        return out


_CORPUS_ABSENT = frozenset({None, "", float("nan")})


def _corpus_scalar(value: Any) -> Any:
    """Normalize one persisted corpus value to a comparable scalar (None when absent)."""
    if value is None:
        return None
    try:
        f = float(value)
        if math.isnan(f):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool) or (isinstance(value, (int, float)) and not isinstance(value, bool)):
        return value
    s = str(value)
    return None if s == "" else s


def _row_corpus_identity(r: Mapping[str, object]) -> _CorpusIdentity | None:
    """The row's evaluation-corpus identity, or ``None`` when the row carries none."""
    h = r.get("evaluation_corpus_hash")
    if not h or (isinstance(h, float) and math.isnan(float(h))):
        return None
    fields: dict[str, Any] = {}
    for key in CORPUS_IDENTITY_COLUMNS:
        fields[key] = _corpus_scalar(r.get(key))
    fields["evaluation_corpus_hash"] = str(h)
    return _CorpusIdentity(fields=fields, hash=str(h))


def _identity_from_corpus(evaluation_corpus: Any) -> _CorpusIdentity | None:
    """Decode an optional evaluation-corpus identity object for the gate."""
    if evaluation_corpus is None:
        return None
    raw = {
        "evaluation_corpus_hash": str(evaluation_corpus.corpus_hash),
        "evaluation_corpus_count": int(evaluation_corpus.count),
        "evaluation_corpus_comparable": bool(evaluation_corpus.comparable),
        "evaluation_corpus_missing_count": int(evaluation_corpus.missing_count),
        "evaluation_corpus_missing_digest": evaluation_corpus.missing_digest or None,
        "evaluation_corpus_semantics_version": int(evaluation_corpus.semantics_version),
        "evaluation_corpus_eligible": bool(evaluation_corpus.eligible),
        "evaluation_corpus_eligible_digest": evaluation_corpus.eligible_digest or None,
        "evaluation_corpus_requested_count": int(evaluation_corpus.requested_count),
        "evaluation_corpus_requested_digest": evaluation_corpus.requested_digest or None,
        "evaluation_corpus_observation_digest": evaluation_corpus.observation_digest or None,
        "evaluation_corpus_complete": bool(evaluation_corpus.completeness),
        "evaluation_corpus_integrity": evaluation_corpus.integrity or None,
    }
    return _CorpusIdentity(fields=raw, hash=str(evaluation_corpus.corpus_hash))


def _incomplete_entry(
    key: tuple[str, str, int, str],
    seg: Mapping[str, object],
    medoid_key: str,
    *,
    reason: str,
    baseline_identity: _CorpusIdentity | None,
    seg_identity: _CorpusIdentity | None,
) -> dict[str, object]:
    """One surfaced incomplete diagnostic for a representation that cannot be compared."""
    backbone, sim_metric, k, metric = key
    entry: dict[str, object] = {
        "backbone": backbone,
        "sim_metric": sim_metric,
        "k": int(k),
        "metric": metric,
        "strategy_key": str(seg["strategy_key"]),
        "baseline_strategy_key": medoid_key,
        "reason": reason,
        # The observed-medoid baseline's corpus evidence (when the baseline carries an identity).
        "baseline_evaluation_corpus_hash": baseline_identity.hash if baseline_identity else None,
        "baseline_evaluation_corpus_count": baseline_identity.count if baseline_identity else None,
        "baseline_evaluation_corpus_comparable": baseline_identity.comparable if baseline_identity else None,
        # The representation's own corpus evidence + excluded-song missing evidence (count/digest;
        # individual missing song ids are not persisted on scope lines).
        "representation_evaluation_corpus_hash": seg_identity.hash if seg_identity else None,
        "representation_evaluation_corpus_count": seg_identity.count if seg_identity else None,
        "representation_evaluation_corpus_comparable": seg_identity.comparable if seg_identity else None,
        "representation_missing_count": seg_identity.missing_count if seg_identity else None,
        "representation_missing_digest": seg_identity.missing_digest if seg_identity else None,
    }
    return entry


def build_baseline_delta_rows(
    analysis_df: pd.DataFrame,
    *,
    evaluation_corpus=None,
) -> BaselineDeltaResult:
    """Per-(backbone, sim_metric, k, metric) observed-medoid baseline/winner/delta rows.

    ``analysis_df`` is a decoded long-form frame (the shape returned by
    ``report._retrieval.query_winners_metrics``) whose rows carry at least ``backbone``,
    ``sim_metric``, ``k``, ``metric``, ``strategy_key``, and ``value``, AND which already
    contains the medoid baseline value row per cell
    with ``strategy_key == medoid_strategy_key_for(backbone)`` (e.g.
    ``global_pool:effnet:medoid``).  When the frame's rows carry the persisted evaluation-
    corpus identity columns (:data:`CORPUS_IDENTITY_COLUMNS`, read from each row's
    ``analyze_scope_v2`` provenance line) the builder enforces MATCHING-ONLY deltas:

    * **matching gate** — a segmented class may win a cell ONLY when it shares the
      observed-medoid baseline's evaluation-corpus identity (equal complete corpus
      identity/evidence — ``_CorpusIdentity.mismatched_fields`` empty) AND is
      comparable AND finite.  Equal ``{A,B,C,D}`` baseline vs segmented ``{A,B,C,D}``
      matches; a segmented ``{A,B,C}`` never matches a ``{A,B,C,D}`` baseline and never
      partially matches on the shared subset (no silent intersection).
    * **surfaced incomplete** — a segmented class that does NOT match (different
      population, non-comparable, a one-sided identity, or both sides identity-less) is
      excluded from winner candidacy and surfaced in the result's ``incomplete``
      diagnostics, retaining its strategy key, cell provenance, corpus hash/count/
      comparability and excluded-song missing count/digest evidence.
    * There is NO identity-less structural path: a cell whose segmented class and
      medoid baseline BOTH lack a corpus identity (or a one-sided identity) never yields a
      matched delta — it is always surfaced as an ``incomplete`` diagnostic.  Every cell
      must carry an explicit, equal, comparable evaluation-corpus identity to match.

    For each matched cell the returned record carries the medoid **baseline** value (the
    observed global medoid scored under the SAME corpus / sim_metric / k / metric — never a
    winner candidate), the highest *finite* matched segmented class (**winner**; ties break
    to the lowest ``strategy_key``), and ``delta = winner_value - baseline_value``.

    ``evaluation_corpus`` (an optional evaluation-corpus identity object) supplies the
    baseline's authoritative identity when
    the medoid row itself carries none; it never widens the gate (a row identity, when
    present, is authoritative).  A present non-finite value raises ``ValueError`` (fail
    closed).  Returns a :class:`BaselineDeltaResult` (matched ``rows`` + surfaced
    ``incomplete`` diagnostics); both are empty when there is nothing to match.
    """
    import pandas as pd

    if analysis_df is None or analysis_df.empty:
        return BaselineDeltaResult(rows=(), incomplete=())
    required = {"backbone", "sim_metric", "k", "metric", "strategy_key", "value"}
    missing = required - set(analysis_df.columns)
    if missing:
        raise ValueError(f"build_baseline_delta_rows frame is missing columns: {sorted(missing)}")
    sel = [
        "backbone",
        "sim_metric",
        "k",
        "metric",
        "strategy_key",
        "value",
    ] + [c for c in CORPUS_IDENTITY_COLUMNS if c in analysis_df.columns]
    recs = analysis_df[sel].to_dict("records")

    cells: dict[tuple[str, str, int, str], list[dict]] = {}
    for r in recs:
        key = (str(r["backbone"]), str(r["sim_metric"]), int(r["k"]), str(r["metric"]))
        cells.setdefault(key, []).append(r)

    out: list[dict] = []
    incomplete: list[dict] = []
    for key in sorted(cells):
        backbone, sim_metric, k, metric = key
        if metric in _NON_SCORED_COUNT_METRICS:
            # ``n_queries_*`` are per-ruler ruler-evaluable-query COUNTS (persisted as EAV rows by
            # both each segmented-class writer and the medoid-baseline writer), not scored
            # retrieval cells.  They never form a baseline/winner delta or an ``incomplete``
            # diagnostic, so these cells are excluded from the winner-delta machinery entirely.
            continue
        rows = cells[key]
        medoid_key = medoid_strategy_key_for(backbone)
        medoid_rows = [r for r in rows if str(r["strategy_key"]) == medoid_key]
        seg_rows = [r for r in rows if str(r["strategy_key"]) != medoid_key]
        if not medoid_rows:
            # No observed medoid baseline for this backbone/cell -> no delta and nothing to compare.
            continue
        # Fail closed on any present non-finite value (the medoid's or a segmented class's).
        _refuse_non_finite([float(r["value"]) for r in medoid_rows + seg_rows], key)
        baseline = medoid_rows[0]
        baseline_value = float(baseline["value"])
        if not math.isfinite(baseline_value):
            raise ValueError(f"{key} medoid baseline is non-finite; baseline refuses to emit")
        # The baseline's authoritative identity: the persisted row identity wins; the explicit
        # evaluation_corpus kwarg supplies it only when the row carries none.
        baseline_identity = _row_corpus_identity(baseline)
        if baseline_identity is None:
            baseline_identity = _identity_from_corpus(evaluation_corpus)

        matchable: list[dict] = []
        for seg in seg_rows:
            seg_identity = _row_corpus_identity(seg)
            reason: str | None = None
            if baseline_identity is not None and seg_identity is not None:
                if not baseline_identity.comparable:
                    reason = "observed-medoid baseline representation is non-comparable"
                elif not seg_identity.comparable:
                    reason = "segmented representation is non-comparable (lost a baseline-eligible song)"
                else:
                    # Complete corpus identity/evidence equality: a segmented class may win a cell
                    # ONLY when EVERY carried corpus identity/evidence field (membership, missing
                    # evidence, observation binding, semantics/version, completeness/integrity)
                    # equals the observed-medoid baseline's — not merely an equal-looking hash/
                    # count or a compatible subset.  A mismatch on ANY field excludes the cell.
                    mismatches = seg_identity.mismatched_fields(baseline_identity)
                    if mismatches:
                        reason = (
                            "segmented representation's evaluation corpus differs from the observed-medoid "
                            "baseline corpus on: "
                            + "; ".join(mismatches)
                            + " (unequal/truncated populations or evidence never partially match)"
                        )
            elif baseline_identity is not None or seg_identity is not None:
                reason = "evaluation-corpus identity present on only one side of the baseline/segmented comparison"
            else:
                # Both sides identity-less (no corpus identity on the segmented row nor the medoid
                # baseline).  There is NO structural path for identity-less cells: they can
                # never be a matched delta under the matching-only gate.
                reason = (
                    "evaluation-corpus identity absent on both sides of the baseline/segmented "
                    "comparison; identity-less rows never produce a matched delta (every cell must "
                    "carry an explicit equal, comparable evaluation-corpus identity)"
                )
            if reason is not None:
                incomplete.append(
                    _incomplete_entry(
                        key,
                        seg,
                        medoid_key,
                        reason=reason,
                        baseline_identity=baseline_identity,
                        seg_identity=seg_identity,
                    )
                )
            else:
                matchable.append(seg)

        finite_matchable = [r for r in matchable if _is_finite(r.get("value"))]
        if not finite_matchable:
            continue
        winner = min(finite_matchable, key=lambda r: (-float(r["value"]), str(r["strategy_key"])))
        winner_value = float(winner["value"])
        out.append(
            {
                "backbone": backbone,
                "sim_metric": sim_metric,
                "k": int(k),
                "metric": metric,
                "n_segmented_classes": len({str(r["strategy_key"]) for r in seg_rows}),
                "baseline_strategy_key": medoid_key,
                "baseline_value": baseline_value,
                "winner_strategy_key": str(winner["strategy_key"]),
                "winner_value": winner_value,
                "delta": winner_value - baseline_value,
            }
        )

    rows: tuple[Mapping[str, object], ...] = ()
    if out:
        order = ["backbone", "sim_metric", "k", "metric"]
        frame = pd.DataFrame(out)
        frame = frame.sort_values(order, kind="mergesort").reset_index(drop=True)
        rows = tuple(frame.to_dict("records"))
    return BaselineDeltaResult(rows=rows, incomplete=tuple(incomplete))
