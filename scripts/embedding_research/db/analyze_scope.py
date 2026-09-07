"""Run-scoped analyze write + scope bookkeeping contract (one current run-scoped schema).

``analyze_metrics`` carries a physical ``run_id`` column with ONE current meaning: the run that
produced the row.  There is no pre-cut / legacy partition and no reserved legacy run id — every
row is written by a run-scoped caller that supplies the current ``run_id`` (a stale pre-cut or
legacy-partitioned table is refused at schema setup, never relabeled).  This module is the scope
bookkeeping + writer surface layered on that column:

  * the encode/parse/record scope contracts below are preserved — a run's output-row scope is still
    recorded in ``run_provenance.output_artifact_hashes`` as a canonical parseable scope line (the
    atomicity/audit layer, Phase C/D) — while run-scoped WRITES additionally stamp the
    physical ``run_id`` on every aggregate row they own.
  * since the execution-reporting-repair Plan B corrective hard cut, the runtime has EXACTLY ONE
    analyze-scope schema — **``analyze_scope_v2``** — carrying the complete durable semantic catalog
    identity of the analyzed scope plus an explicit ``scope_kind`` discriminator.  There is no v1
    prefix, encoder, decoder, parser branch, compatibility/fallback reader, dual writer, historical-v1
    runtime branch, or test-only v1 producer anywhere in the runtime (the v1 machine was removed by
    the corrective phase).  The complete v2 fields are: ``catalog_id``/``catalog_fingerprint``, the
    *semantic* ``search_representation_hash`` (the real ``catalog_identity.search_representation_hash``
    value of the analyzed search-representation class — never a disposable view/keyset hash), the
    ordered per-member ``config_ids``/``alias_ids``/``canonical_config_id`` with per-member configured
    + effective thresholds / ``bin_mode`` / ``exact_segmentation_hash``, the ``score_variant`` +
    ``scoring_semantics_version``, and the evaluation-corpus hash/count/comparability + missing-song
    evidence.  The **disposable** per-run search-view identity is carried separately as
    ``view_keyset_hash`` (the per-run strategy-key keyset component) and ``view_content_hash`` — the
    two are distinct from one another and from the semantic representation hash.
  * the ``scope_kind`` discriminator makes non-class observed-medoid/baseline semantics EXPLICIT in
    v2 rather than encoding them as empty-field exemptions: ``catalog_class`` (a real anchored class),
    ``observed_baseline`` (the observed ``global_pool:{backbone}:medoid`` non-class pass), and
    ``structural_fixture`` (a deliberately catalog-less loader/structural row whose missing anchor is
    represented BY THE TAG, never as a silently-empty "apparently complete" catalog class).  A scope
    that cannot encode as complete for its declared kind is REFUSED (fail-closed) — there is no
    identity-less exemption that turns an incomplete scope into a usable one.
  * an analysis run only ever touches rows it owns.  The aggregate writer
    ``db.write_analyze_metrics`` (called from :func:`write_catalog_analyze_rows`) deletes/replaces ONLY
    its own ``(run_id, strategy_key, sim_metric, k)`` scope — never another run's rows and never
    unrelated / retained runs.  No code path here or in the analysis callers performs a global
    ``DELETE FROM analyze_metrics``.
  * the run-scoped reader contracts that gained a ``run_id`` filter (``load_analyze_metrics`` in
    db/flat.py, ``query_analysis_done`` in db/queries.py) restrict to rows whose physical ``run_id``
    column equals that run.  ``query_analyze_metrics`` (report/_retrieval.py) gained the same optional
    ``run_id`` filter.  Default ``run_id=None`` keeps the whole-table read (unchanged on a single
    generation DB).
  * :func:`run_row_scopes` remains the provenance/atomicity bookkeeping query (a scope may be recorded
    before any row is physically written, and recorded scopes are retained as the run's audit record);
    the physical column is the row-level realization used by reader filters and run-scoped reset.

Finite-only guarantee is enforced by the analysis layer (common.catalog_analysis raises
``NonFiniteResultError`` before a non-finite value can reach a writer).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

_ANALYZE_PHASE = "analyze"
#: The ONE versioned scope-record prefix current writers emit (analyze_scope_v2, complete identity).
_SCOPE_V2_PREFIX = "analyze_scope_v2"

#: Explicit ``scope_kind`` discriminators.  A scope's completeness is defined per kind, so a
#: non-class baseline or a catalog-less structural row is represented BY ITS TAG — never by the
#: old identity-less empty-field exemption that let an incomplete scope masquerade as complete.
SCOPE_KIND_CATALOG_CLASS = "catalog_class"
SCOPE_KIND_OBSERVED_BASELINE = "observed_baseline"
SCOPE_KIND_STRUCTURAL_FIXTURE = "structural_fixture"


# --------------------------------------------------------------------------- #
# Analyze-scope v2 identity DTOs                                              #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ScopeMemberIdentity:
    """Per-member (per-``config_id``) identity inside one analyzed search-representation class.

    ``config_id`` is one ordered member of the class's ``AnalyzeScopeIdentity.config_ids``.  The
    configured + effective thresholds and ``bin_mode`` are read from the compact ``seg_config`` row;
    ``exact_segmentation_hash`` is the member's ``catalog_identity.exact_segmentation_hash`` (the
    EXACT per-config segmentation hash — distinct per config even when search-collapsed).
    """

    config_id: int
    threshold_configured: float | None = None
    threshold_effective: float | None = None
    bin_mode: str = ""
    exact_segmentation_hash: str = ""


@dataclass(frozen=True)
class AnalyzeScopeIdentity:
    """The full durable identity of one analyzed output scope (the analyze_scope_v2 payload).

    Carries BOTH the *semantic* catalog identity (``catalog_id``/``catalog_fingerprint`` and the
    semantic ``search_representation_hash`` sourced from
    ``catalog_identity.search_representation_hash`` of the analyzed search-representation class)
    AND the *disposable* per-run search-view identity (``view_keyset_hash`` — the trailing component
    of the run's strategy key — and ``view_content_hash``), kept as SEPARATE fields so a disposable
    keyset/view hash never masquerades as semantic identity.

    ``scope_kind`` (:data:`SCOPE_KIND_CATALOG_CLASS` by default) discriminates the scope's semantics:

    * ``catalog_class`` — a real anchored search-representation class (the analyzed outcome of a
      compact catalog class).  Its completeness REQUIRES the full semantic anchor + per-member
      records; a partial class scope refuses to encode.
    * ``observed_baseline`` — the observed ``global_pool:{backbone}:medoid`` NON-class pass.  It is
      never a class: ``config_ids``/``members``/``search_representation_hash`` stay empty BY THE TAG
      (there is no class identity to carry), while the score/scoring semantics and any genuine
      catalog anchor + evaluation-corpus identity it has are carried.
    * ``structural_fixture`` — a deliberately catalog-less loader/structural row whose missing
      catalog anchor + semantic hash are represented BY THE TAG (a structural fixture genuinely has
      no real catalog to anchor to); its structural ``config_ids`` membership is required.

    ``config_ids`` is the ordered (ascending) tuple of every member of the analyzed class — the
    canonical (lowest) member first.  ``canonical_config_id`` and ``alias_ids`` are derived from it
    (canonical = ``config_ids[0]``, aliases = ``config_ids[1:]``), and ``members`` (when present) is
    aligned to ``config_ids`` order — this ordering is the deterministic form the round-trip contract
    and the ordered-member/alias determinism tests rely on.
    """

    strategy_key: str
    sim_metric: str
    k: int
    backbone: str
    scope_kind: str = SCOPE_KIND_CATALOG_CLASS
    catalog_id: str = ""
    catalog_fingerprint: str = ""
    search_representation_hash: str = ""
    config_ids: tuple[int, ...] = ()
    members: tuple[ScopeMemberIdentity, ...] = ()
    score_variant: str = ""
    scoring_semantics_version: int = 0
    view_keyset_hash: str = ""
    view_content_hash: str = ""
    evaluation_corpus_hash: str | None = None
    evaluation_corpus_count: int | None = None
    evaluation_corpus_comparable: bool = False
    evaluation_corpus_missing_count: int = 0
    evaluation_corpus_missing_digest: str = ""
    # ── COMPLETE persisted corpus identity / evidence (Plan C Phase 1) ───────────────
    # The compact per-row corpus-identity carries exact digest proof of the eligible +
    # requested membership sets, the observation-binding digest the corpus was resolved
    # against, the semantics/version identity, and explicit completeness + integrity
    # self-check fields — so the baseline delta / report equality gate can detect an altered
    # membership or observation binding that keeps an equal-looking hash/count.  These are
    # backward-readable additions to the five legacy ``evaluation_corpus_*`` keys (which are
    # preserved unchanged).
    evaluation_corpus_semantics_version: int | None = None
    evaluation_corpus_eligible: bool = False
    evaluation_corpus_eligible_digest: str = ""
    evaluation_corpus_requested_count: int | None = None
    evaluation_corpus_requested_digest: str = ""
    evaluation_corpus_observation_digest: str = ""
    evaluation_corpus_complete: bool = False
    evaluation_corpus_integrity: str = ""

    def __post_init__(self) -> None:
        # Deterministic canonical ordering: config_ids ascending => canonical = lowest member,
        # aliases = the rest (a search-representation class always canonicalizes to its lowest id).
        config_ids = tuple(sorted(int(c) for c in self.config_ids))
        object.__setattr__(self, "config_ids", config_ids)
        if config_ids and self.members:
            members = tuple(self.members)
            if [m.config_id for m in members] != list(config_ids):
                raise ValueError(
                    "AnalyzeScopeIdentity.members must be ordered to match config_ids "
                    f"(members config_ids={[m.config_id for m in members]}, config_ids={list(config_ids)})"
                )

    @property
    def canonical_config_id(self) -> int | None:
        """The class canonical (lowest) member id, or None for a non-class scope."""
        return self.config_ids[0] if self.config_ids else None

    @property
    def alias_ids(self) -> tuple[int, ...]:
        """Ordered non-canonical members (empty for a singleton class or a non-class scope)."""
        return self.config_ids[1:]


def _corpus_scope_fields(evaluation_corpus) -> dict[str, Any] | None:
    """The evaluation-corpus identity keys carried on an analyze-scope line (None when no identity)."""
    if evaluation_corpus is None:
        return None
    return {
        "evaluation_corpus_hash": evaluation_corpus.corpus_hash,
        "evaluation_corpus_count": int(evaluation_corpus.count),
        "evaluation_corpus_comparable": bool(evaluation_corpus.comparable),
        "evaluation_corpus_missing_count": int(evaluation_corpus.missing_count),
        "evaluation_corpus_missing_digest": evaluation_corpus.missing_digest or "",
        "evaluation_corpus_semantics_version": int(evaluation_corpus.semantics_version),
        "evaluation_corpus_eligible": bool(evaluation_corpus.eligible),
        "evaluation_corpus_eligible_digest": evaluation_corpus.eligible_digest or "",
        "evaluation_corpus_requested_count": int(evaluation_corpus.requested_count),
        "evaluation_corpus_requested_digest": evaluation_corpus.requested_digest or "",
        "evaluation_corpus_observation_digest": evaluation_corpus.observation_digest or "",
        "evaluation_corpus_complete": bool(evaluation_corpus.completeness),
        "evaluation_corpus_integrity": evaluation_corpus.integrity or "",
    }


def _identity_payload(identity: AnalyzeScopeIdentity) -> dict[str, Any]:
    """Canonical v2 payload dict for *identity* (legacy key names preserved where they overlap)."""
    return {
        "scope_kind": identity.scope_kind,
        "strategy_key": identity.strategy_key,
        "sim_metric": identity.sim_metric,
        "k": identity.k,
        "backbone": identity.backbone,
        "catalog_id": identity.catalog_id or "",
        "catalog_fingerprint": identity.catalog_fingerprint or "",
        "search_representation_hash": identity.search_representation_hash or "",
        "canonical_config_id": identity.canonical_config_id,
        "config_ids": [int(c) for c in identity.config_ids],
        "alias_ids": [int(a) for a in identity.alias_ids],
        "members": [
            {
                "config_id": int(m.config_id),
                "threshold_configured": m.threshold_configured,
                "threshold_effective": m.threshold_effective,
                "bin_mode": m.bin_mode or "",
                "exact_segmentation_hash": m.exact_segmentation_hash or "",
            }
            for m in identity.members
        ],
        "score_variant": identity.score_variant or "",
        "scoring_semantics_version": int(identity.scoring_semantics_version),
        "view_keyset_hash": identity.view_keyset_hash or "",
        "view_content_hash": identity.view_content_hash or "",
        "evaluation_corpus_hash": identity.evaluation_corpus_hash,
        "evaluation_corpus_count": identity.evaluation_corpus_count,
        "evaluation_corpus_comparable": bool(identity.evaluation_corpus_comparable),
        "evaluation_corpus_missing_count": int(identity.evaluation_corpus_missing_count),
        "evaluation_corpus_missing_digest": identity.evaluation_corpus_missing_digest or "",
        "evaluation_corpus_semantics_version": identity.evaluation_corpus_semantics_version,
        "evaluation_corpus_eligible": bool(identity.evaluation_corpus_eligible),
        "evaluation_corpus_eligible_digest": identity.evaluation_corpus_eligible_digest or "",
        "evaluation_corpus_requested_count": identity.evaluation_corpus_requested_count,
        "evaluation_corpus_requested_digest": identity.evaluation_corpus_requested_digest or "",
        "evaluation_corpus_observation_digest": identity.evaluation_corpus_observation_digest or "",
        "evaluation_corpus_complete": bool(identity.evaluation_corpus_complete),
        "evaluation_corpus_integrity": identity.evaluation_corpus_integrity or "",
    }


def _raise_if_incomplete(identity: AnalyzeScopeIdentity) -> None:
    """Reject a scope that is not COMPLETE for its declared ``scope_kind`` (fail closed).

    There is no identity-less exemption: a scope that cannot carry its kind's required identity is
    refused rather than silently recorded as an apparently-complete outcome.  Per-kind requirements:

    * ``catalog_class`` — the full durable anchor: ``catalog_id`` + ``catalog_fingerprint`` + the
      semantic ``search_representation_hash``, non-empty ordered ``config_ids``, an ordered per-member
      record for EVERY member with configured + effective thresholds, ``bin_mode`` and
      ``exact_segmentation_hash``, plus ``score_variant`` / ``scoring_semantics_version``.
    * ``observed_baseline`` — a NON-class scope: ``config_ids``/``members``/
      ``search_representation_hash`` must be empty (represented BY THE TAG), and the score/scoring
      semantics it genuinely carries must be present.  A real catalog anchor + evaluation-corpus
      identity are carried when present.
    * ``structural_fixture`` — a deliberately catalog-less structural row: ``catalog_id`` and
      ``search_representation_hash`` are empty BY THE TAG, but the structural ``config_ids``
      membership and score/scoring semantics are required.
    """
    missing: list[str] = []
    kind = identity.scope_kind

    def _require_score() -> None:
        if not identity.score_variant:
            missing.append("score_variant")
        if identity.scoring_semantics_version < 1:
            missing.append("scoring_semantics_version")

    if kind == SCOPE_KIND_CATALOG_CLASS:
        if not identity.catalog_id:
            missing.append("catalog_id")
        if not identity.catalog_fingerprint:
            missing.append("catalog_fingerprint")
        if not identity.search_representation_hash:
            missing.append("search_representation_hash")
        if not identity.config_ids:
            missing.append("config_ids")
        if not identity.members:
            missing.append("members")
        elif [m.config_id for m in identity.members] != list(identity.config_ids):
            missing.append("members ordered to config_ids")
        else:
            for m in identity.members:
                if not m.exact_segmentation_hash:
                    missing.append(f"member {m.config_id} exact_segmentation_hash")
                if m.threshold_configured is None or m.threshold_effective is None:
                    missing.append(f"member {m.config_id} configured/effective thresholds")
                if not m.bin_mode:
                    missing.append(f"member {m.config_id} bin_mode")
        _require_score()
    elif kind == SCOPE_KIND_OBSERVED_BASELINE:
        if identity.config_ids:
            missing.append("config_ids must be empty for a non-class observed baseline")
        if identity.members:
            missing.append("members must be empty for a non-class observed baseline")
        if identity.search_representation_hash:
            missing.append("a non-class observed baseline carries no class search_representation_hash")
        _require_score()
    elif kind == SCOPE_KIND_STRUCTURAL_FIXTURE:
        if identity.catalog_id:
            missing.append("a structural_fixture scope must not claim a catalog_id")
        if identity.search_representation_hash:
            missing.append("a structural_fixture scope carries no semantic search_representation_hash")
        if not identity.config_ids:
            missing.append("config_ids (structural membership)")
        _require_score()
    else:
        missing.append(f"unknown scope_kind {kind!r}")
    if missing:
        raise ValueError(
            f"refusing to record an incomplete {kind} analyze scope as complete; "
            "missing/contradictory mandatory fields: " + ", ".join(missing)
        )


def encode_analyze_scope_v2(identity: AnalyzeScopeIdentity) -> str:
    """Canonical single-line ``analyze_scope_v2`` record for *identity*.

    Refuses to encode an incomplete scope (see :func:`_raise_if_incomplete`) so a partial
    configuration is never persisted as a complete outcome — the v2 schema is the sole runtime schema
    and there is no v1/identity-less fallback.  Parsable back to an :class:`AnalyzeScopeIdentity` with
    :func:`decode_analyze_scope_v2` and to a payload dict with :func:`parse_analyze_scope`.
    """
    _raise_if_incomplete(identity)
    payload = _identity_payload(identity)
    return f"{_SCOPE_V2_PREFIX}|{json.dumps(payload, sort_keys=True, separators=(',', ':'))}"


def decode_analyze_scope_v2(text: str) -> AnalyzeScopeIdentity | None:
    """Decode an ``analyze_scope_v2`` line back to an :class:`AnalyzeScopeIdentity`.

    Returns None for any line that is not an ``analyze_scope_v2`` record.  There is no v1 line format
    in the runtime, so a non-v2 line is simply not a v2 scope (never reinterpreted as current data).
    """
    if not text.startswith(_SCOPE_V2_PREFIX + "|"):
        return None
    p = json.loads(text.split("|", 1)[1])
    members = tuple(
        ScopeMemberIdentity(
            config_id=int(m["config_id"]),
            threshold_configured=m.get("threshold_configured"),
            threshold_effective=m.get("threshold_effective"),
            bin_mode=m.get("bin_mode", "") or "",
            exact_segmentation_hash=m.get("exact_segmentation_hash", "") or "",
        )
        for m in p.get("members", [])
    )
    return AnalyzeScopeIdentity(
        strategy_key=p["strategy_key"],
        sim_metric=p["sim_metric"],
        k=int(p["k"]),
        backbone=p["backbone"],
        scope_kind=p.get("scope_kind", SCOPE_KIND_CATALOG_CLASS),
        catalog_id=p.get("catalog_id", "") or "",
        catalog_fingerprint=p.get("catalog_fingerprint", "") or "",
        search_representation_hash=p.get("search_representation_hash", "") or "",
        config_ids=tuple(int(c) for c in p.get("config_ids", ())),
        members=members,
        score_variant=p.get("score_variant", "") or "",
        scoring_semantics_version=int(p.get("scoring_semantics_version", 0)),
        view_keyset_hash=p.get("view_keyset_hash", "") or "",
        view_content_hash=p.get("view_content_hash", "") or "",
        evaluation_corpus_hash=p.get("evaluation_corpus_hash"),
        evaluation_corpus_count=p.get("evaluation_corpus_count"),
        evaluation_corpus_comparable=bool(p.get("evaluation_corpus_comparable", False)),
        evaluation_corpus_missing_count=int(p.get("evaluation_corpus_missing_count", 0)),
        evaluation_corpus_missing_digest=p.get("evaluation_corpus_missing_digest", "") or "",
        evaluation_corpus_semantics_version=p.get("evaluation_corpus_semantics_version"),
        evaluation_corpus_eligible=bool(p.get("evaluation_corpus_eligible", False)),
        evaluation_corpus_eligible_digest=p.get("evaluation_corpus_eligible_digest", "") or "",
        evaluation_corpus_requested_count=p.get("evaluation_corpus_requested_count"),
        evaluation_corpus_requested_digest=p.get("evaluation_corpus_requested_digest", "") or "",
        evaluation_corpus_observation_digest=p.get("evaluation_corpus_observation_digest", "") or "",
        evaluation_corpus_complete=bool(p.get("evaluation_corpus_complete", False)),
        evaluation_corpus_integrity=p.get("evaluation_corpus_integrity", "") or "",
    )


def parse_analyze_scope(text: str) -> dict[str, Any] | None:
    """Parse an ``analyze_scope_v2`` scope line into its payload dict; None otherwise.

    Recognizes ONLY the current ``analyze_scope_v2`` record.  The v1 scope line format is REMOVED
    from the runtime (no v1 prefix, encoder, or parser branch), so any non-v2 line — including a
    historical v1 line — parses to None and is never reinterpreted as current data.  v2 payloads keep
    the legacy key names (``strategy_key``/``sim_metric``/``k``/``backbone``/``config_ids``/
    ``view_content_hash``/``score_variant``/``scoring_semantics_version`` and the
    ``evaluation_corpus_*`` keys) so the existing report/delta readers keep working unchanged, plus
    the semantic v2 keys and the ``scope_kind`` discriminator.
    """
    if not text.startswith(_SCOPE_V2_PREFIX + "|"):
        return None
    return json.loads(text.split("|", 1)[1])


def _scope_row_scope(text: str) -> tuple[str, str, int] | None:
    scope = parse_analyze_scope(text)
    if scope is None:
        return None
    return (scope["strategy_key"], scope["sim_metric"], int(scope["k"]))


def run_row_scopes(con, *, run_id: str) -> frozenset[tuple[str, str, int]]:
    """The set of ``(strategy_key, sim_metric, k)`` output-row scopes recorded for *run_id*.

    Read from the run's ``phase='analyze'`` ``run_provenance`` rows' ``output_artifact_hashes``
    (each may carry many scope lines).  Empty when the run has no recorded analyze scope.
    """
    scopes: set[tuple[str, str, int]] = set()
    rows = con.execute(
        "SELECT output_artifact_hashes FROM run_provenance WHERE run_id=? AND phase=?",
        (run_id, _ANALYZE_PHASE),
    ).fetchall()
    for (blob,) in rows:
        if not blob:
            continue
        for line in blob.splitlines():
            parsed = _scope_row_scope(line.strip())
            if parsed is not None:
                scopes.add(parsed)
    return frozenset(scopes)


def record_analyze_run_scope(
    con,
    *,
    run_id: str,
    identity: AnalyzeScopeIdentity,
) -> None:
    """Record *run_id*'s output-row scope in ``run_provenance.output_artifact_hashes``.

    The scope is encoded as the versioned :func:`encode_analyze_scope_v2` record carrying the full
    semantic/disposable identity + ``scope_kind`` carried by *identity*.  Encoding an incomplete scope
    raises (see :func:`_raise_if_incomplete`), so a partial configuration is never recorded as a
    complete outcome.

    Merge semantics: appends this strategy scope to every ``phase='analyze'`` provenance row of the
    run, deduped by ``(strategy_key, sim_metric, k)``.  If the run has no ``phase='analyze'`` row yet
    (no view was materialized for it), one is created (status ``complete``) so the scope anchor always
    exists.  Other runs' rows — including ``retained`` rows — are never modified.
    """
    line = encode_analyze_scope_v2(identity)
    existing = con.execute(
        "SELECT rowid FROM run_provenance WHERE run_id=? AND phase=?",
        (run_id, _ANALYZE_PHASE),
    ).fetchall()
    if not existing:
        from scripts.embedding_research.db.provenance import write_run_provenance

        write_run_provenance(
            con,
            run_id=run_id,
            phase=_ANALYZE_PHASE,
            status="complete",
            started_at=_now_ms(),
            finished_at=_now_ms(),
            output_artifact_hashes=line,
        )
        return
    # Merge into each existing phase='analyze' row.
    for (rowid,) in existing:
        (blob,) = con.execute("SELECT output_artifact_hashes FROM run_provenance WHERE rowid=?", (rowid,)).fetchone()
        lines = [ln for ln in (blob or "").splitlines() if ln.strip()] if blob else []
        if line not in lines:
            lines.append(line)
        con.execute(
            "UPDATE run_provenance SET output_artifact_hashes=? WHERE rowid=?",
            ("\n".join(lines), rowid),
        )


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)


# --------------------------------------------------------------------------- #
# Invocation obligations + terminal state (execution-reporting Plan B P1)      #
# --------------------------------------------------------------------------- #
# An analyze invocation's obligations and its single terminal outcome are recorded as
# canonical single-line records APPENDED into the SAME ``run_provenance.output_artifact_hashes``
# that already carries the ``analyze_scope_v2`` scope lines (the existing ``prefix|json`` line
# store).  Scope lines are append-only EVIDENCE and never terminalize the invocation; only a
# matching terminal record (appended after every obligation resolved) does.  The producer starts
# an invocation with ``analyze_invocation_v1|...`` (its declared obligations), then appends
# ``analyze_terminal_v1|...`` (outcome ``completed``) ONLY when every obligation resolves.
#
# The terminal record is the report-completion signal the grouped run predicate requires, so a
# run whose scope rows exist but whose invocation is still open (running, no terminal) is never a
# completed analyze scope.  A same-run ``status == 'failed'`` analyze provenance row (written by
# ``_run_single_phase`` on any exception) continues to veto the whole run.  The marker lines do
# not affect ``parse_analyze_scope``/``run_row_scopes`` (they skip non-``analyze_scope_v2``
# lines) or report provenance rendering (which surfaces ``output_artifact_hashes`` verbatim).

#: Single-line invocation-obligations record prefix (the invocation is ``running`` from this line).
_INVOCATION_PREFIX = "analyze_invocation_v1"
#: Single-line terminal-outcome record prefix (appended once, only after obligations resolve).
_TERMINAL_PREFIX = "analyze_terminal_v1"
#: The one terminal outcome that makes a run a clean completed analyze scope.
_TERMINAL_COMPLETED = "completed"

#: Canonical single-line markers (record-kind discriminators) — kept importable for predicates.
INVOCATION_MARKER_PREFIX = _INVOCATION_PREFIX
TERMINAL_MARKER_PREFIX = _TERMINAL_PREFIX
TERMINAL_OUTCOME_COMPLETED = _TERMINAL_COMPLETED


class AnalyzeInvocationError(RuntimeError):
    """The invocation-obligations/terminal lifecycle contract was violated (duplicate/conflict)."""


class AnalyzeInvocationIncompleteError(AnalyzeInvocationError):
    """An invocation obligation is unresolved, so the run cannot terminalize ``completed``.

    Raised by :func:`terminalize_analyze_completed` when a declared obligation (a requested
    backbone's MANDATORY observed ``global_pool:{backbone}:medoid`` baseline) has no persisted
    evidence, or when no obligations-start record exists to terminalize.  The caller fails
    closed (propagates -> a ``failed`` analyze provenance row) rather than recording a terminal
    ``completed`` for an invocation whose obligations are not all resolved.
    """


def _output_lines(blob: str | None) -> list[str]:
    return [ln for ln in (blob or "").splitlines() if ln.strip()] if blob else []


def _marker_payload(line: str, prefix: str) -> dict | None:
    """Parse a ``<prefix>|<json>`` line to its payload dict; None for any other line."""
    if not line.startswith(prefix + "|"):
        return None
    try:
        payload = json.loads(line.split("|", 1)[1])
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _analyze_row_blobs(con, *, run_id: str) -> list[str]:
    rows = con.execute(
        "SELECT output_artifact_hashes FROM run_provenance WHERE run_id=? AND phase=?",
        (run_id, _ANALYZE_PHASE),
    ).fetchall()
    return [(b or "") for (b,) in rows]


def encode_invocation_obligations(backbones) -> dict:
    """Canonical obligations payload for an analyze invocation over *backbones*.

    *backbones* is an ordered iterable of ``(backbone, baseline_key)`` pairs (the requested
    backbone + its MANDATORY observed ``global_pool:{backbone}:medoid`` baseline strategy key),
    deterministically sorted by backbone.  Each entry is a per-backbone obligation: analyze every
    search-representation class over that backbone AND emit its mandatory medoid baseline.
    """
    ordered = sorted((str(b), str(k)) for b, k in backbones)
    return {
        "version": 1,
        "backbones": [{"backbone": b, "mandatory_baseline": k} for b, k in ordered],
    }


def record_analyze_invocation(
    con,
    *,
    run_id: str,
    backbones,
    started_at: int | None = None,
) -> None:
    """Start an analyze invocation by recording its declared obligations (``running``).

    Appends the ``analyze_invocation_v1|...`` record onto the run's ``phase='analyze'``
    provenance row(s) (creating a ``complete``-status row when none exists yet, so the invocation
    ledger anchor always precedes/coincides with the scope evidence).  Raises
    :class:`AnalyzeInvocationError` if the run already has an invocation record (a run starts its
    invocation exactly once).  Views/scopes recorded later are evidence on the same append-only
    rows and never terminalize this invocation.
    """
    payload = encode_invocation_obligations(backbones)
    line = f"{_INVOCATION_PREFIX}|{json.dumps(payload, sort_keys=True, separators=(',', ':'))}"
    for blob in _analyze_row_blobs(con, run_id=run_id):
        if any(_marker_payload(ln, _INVOCATION_PREFIX) is not None for ln in _output_lines(blob)):
            raise AnalyzeInvocationError(
                f"analyze invocation obligations already recorded for run_id={run_id!r}; "
                "an invocation starts exactly once"
            )
    _append_analyze_line(con, run_id=run_id, line=line, started_at=started_at)


def invocation_state(con, *, run_id: str) -> dict:
    """Return the run's invocation-obligations/terminal state for report-completion predicates.

    Returns ``{"obligations_present": bool, "obligations": dict|None,
    "terminal_completed": bool}``.  ``obligations_present`` is True when the run carries an
    ``analyze_invocation_v1`` record; ``terminal_completed`` is True when it additionally carries
    a ``completed`` ``analyze_terminal_v1`` record.  A run with obligations but no completed
    terminal is an OPEN (running / incompletely-obligated) invocation.
    """
    obligations_present = False
    terminal_completed = False
    obligations_payload: dict | None = None
    for blob in _analyze_row_blobs(con, run_id=run_id):
        for ln in _output_lines(blob):
            inv = _marker_payload(ln, _INVOCATION_PREFIX)
            if inv is not None:
                obligations_present = True
                obligations_payload = inv
                continue
            term = _marker_payload(ln, _TERMINAL_PREFIX)
            if term is not None and term.get("outcome") == _TERMINAL_COMPLETED:
                terminal_completed = True
    return {
        "obligations_present": obligations_present,
        "obligations": obligations_payload,
        "terminal_completed": terminal_completed,
    }


def terminalize_analyze_completed(
    con,
    *,
    run_id: str,
    finished_at: int | None = None,
) -> None:
    """Terminalize *run_id*'s analyze invocation to ``completed`` after every obligation resolves.

    Appends the ``analyze_terminal_v1|{"outcome":"completed"}`` record onto the run's
    ``phase='analyze'`` provenance row(s) and stamps ``finished_at`` on them.  Refuses (raises)
    without recording anything when:

    * the run has NO obligations-start record (nothing to terminalize) — :class:`AnalyzeInvocationIncompleteError`;
    * a terminal record already exists (duplicate terminalization) — :class:`AnalyzeInvocationError`;
    * a declared obligation's MANDATORY observed baseline has no persisted ``analyze_metrics``
      evidence under its strategy key (an obligation is unresolved) — :class:`AnalyzeInvocationIncompleteError`.

    The ``completed`` terminal is therefore written exactly once and only for a clean all-obligation
    invocation.  On any refusal the caller fails closed (propagates -> a ``failed`` analyze row),
    leaving any partial scope evidence append-only (never deleted, never reportable as completed).
    """
    if finished_at is None:
        finished_at = _now_ms()
    state = invocation_state(con, run_id=run_id)
    if not state["obligations_present"]:
        raise AnalyzeInvocationIncompleteError(
            f"cannot terminalize run_id={run_id!r} completed: no analyze invocation obligations "
            "record exists (the invocation was never started)"
        )
    if state["terminal_completed"]:
        raise AnalyzeInvocationError(
            f"refusing duplicate terminalization of run_id={run_id!r}: a completed terminal "
            "already exists (an invocation has exactly one terminal outcome)"
        )
    obligations = state["obligations"] or {}
    unresolved: list[str] = []
    for entry in obligations.get("backbones", []):
        key = str(entry.get("mandatory_baseline", ""))
        backbone = str(entry.get("backbone", ""))
        if not key:
            unresolved.append(f"{backbone}: missing mandatory baseline key")
            continue
        n = con.execute(
            "SELECT count(*) FROM analyze_metrics WHERE run_id=? AND strategy_key=?",
            (run_id, key),
        ).fetchone()[0]
        if not n:
            unresolved.append(f"{backbone}: no {key} baseline evidence")
    if unresolved:
        raise AnalyzeInvocationIncompleteError(
            f"refusing to terminalize run_id={run_id!r} completed with unresolved obligations: " + "; ".join(unresolved)
        )
    line = f"{_TERMINAL_PREFIX}|{json.dumps({'outcome': _TERMINAL_COMPLETED}, sort_keys=True, separators=(',', ':'))}"
    _append_analyze_line(con, run_id=run_id, line=line, started_at=None, finished_at=finished_at)


def _append_analyze_line(
    con,
    *,
    run_id: str,
    line: str,
    started_at: int | None = None,
    finished_at: int | None = None,
) -> None:
    """Append one canonical single-line record onto the run's ``phase='analyze'`` row(s).

    Mirrors ``record_analyze_run_scope`` merge semantics: appends *line* (deduped) to every
    existing ``phase='analyze'`` row of the run; when no such row exists yet one is created
    (status ``complete``) so the record's anchor always exists.  Rows of other runs (incl.
    retained) are never modified.  ``finished_at`` is stamped only when supplied (terminalize).
    """
    existing = con.execute(
        "SELECT rowid FROM run_provenance WHERE run_id=? AND phase=?",
        (run_id, _ANALYZE_PHASE),
    ).fetchall()
    if not existing:
        from scripts.embedding_research.db.provenance import write_run_provenance

        write_run_provenance(
            con,
            run_id=run_id,
            phase=_ANALYZE_PHASE,
            status="complete",
            started_at=started_at if started_at is not None else _now_ms(),
            finished_at=finished_at if finished_at is not None else _now_ms(),
            output_artifact_hashes=line,
        )
        return
    stamp_sql = "output_artifact_hashes = ?"
    params: list[object] = []
    for (rowid,) in existing:
        (blob,) = con.execute("SELECT output_artifact_hashes FROM run_provenance WHERE rowid=?", (rowid,)).fetchone()
        lines = _output_lines(blob)
        if line not in lines:
            lines.append(line)
        if finished_at is not None:
            stamp_sql = "output_artifact_hashes = ?, finished_at = ?"
            params = ["\n".join(lines), int(finished_at)]
        else:
            params = ["\n".join(lines)]
        con.execute(f"UPDATE run_provenance SET {stamp_sql} WHERE rowid=?", (*params, rowid))


def infer_scope_kind(result) -> str:
    """The v2 ``scope_kind`` an analyze *result* producer should record.

    A result carrying a real ``catalog_id`` anchor is a ``catalog_class``; a result with NO catalog
    anchor is a deliberately catalog-less ``structural_fixture`` (represented BY THE TAG, never as an
    identity-less catalog class).  Non-class baseline passes are recorded directly as
    ``observed_baseline`` by the medoid-baseline producer, not through this helper.
    """
    catalog_id = getattr(result, "catalog_id", "") or ""
    return SCOPE_KIND_CATALOG_CLASS if catalog_id else SCOPE_KIND_STRUCTURAL_FIXTURE


def write_catalog_analyze_rows(
    con,
    *,
    run_id: str,
    result,
) -> str:
    """Run-scoped writer for a :class:`CatalogAnalysisResult` (finite, identity-carrying).

    Writes the aggregate ``analyze_metrics`` rows and per-song ``song_retrieval_metrics`` rows under
    ``result.strategy_key`` (which embeds backbone/score-variant/keyset) and records the run's output
    scope in provenance as the versioned :func:`encode_analyze_scope_v2` record.  Returns
    ``result.strategy_key``.

    Finite- and comparable-only: refuses non-finite results and non-comparable (partial) results.
    For the finite gate it asserts ``result.finite`` and refuses to write otherwise (the analysis
    layer raises ``NonFiniteResultError`` before ever building a non-finite result, so this is a
    defensive final gate at the trust boundary).  A complete scope is constructed and
    encode/decode-validated BEFORE any aggregate or per-song metric row is written, so an incomplete
    catalog-class scope (which :func:`encode_analyze_scope_v2` => :func:`_raise_if_incomplete`
    refuses) fails closed and leaves ZERO metric rows behind — no orphans, no partial writes.  No
    global delete occurs anywhere in this path.
    """
    if not result.finite:
        raise ValueError(f"refusing to write non-finite catalog analysis result for run {run_id!r}")
    if not result.comparable:
        raise ValueError(
            f"refusing to write non-comparable (partial) catalog analysis result for run {run_id!r}: "
            f"{result.missing_count} eligible song(s) lost a searchable medoid "
            f"({', '.join(result.missing_song_ids)}); a partial configuration is never recorded complete"
        )
    from scripts.embedding_research import db

    strategy_key = result.strategy_key
    sim_metric = "cosine"  # primary sim-metric dimension (mirrors similarity.METRICS == {cosine})
    # Build and validate the complete analyze-scope identity BEFORE writing any metrics rows, so an
    # incomplete catalog-class / baseline scope (which encode_analyze_scope_v2 => _raise_if_incomplete
    # refuses) can never leave orphaned identity-less rows behind with no scope line.
    corpus = _corpus_scope_fields(getattr(result, "evaluation_corpus", None))
    identity = AnalyzeScopeIdentity(
        strategy_key=strategy_key,
        sim_metric=sim_metric,
        k=result.k,
        backbone=result.backbone,
        scope_kind=infer_scope_kind(result),
        catalog_id=getattr(result, "catalog_id", "") or "",
        catalog_fingerprint=getattr(result, "catalog_fingerprint", "") or "",
        search_representation_hash=getattr(result, "search_representation_hash", "") or "",
        config_ids=tuple(int(c) for c in result.config_ids),
        members=getattr(result, "members", ()) or (),
        score_variant=result.score_variant,
        scoring_semantics_version=result.scoring_semantics_version,
        view_keyset_hash=getattr(result, "view_keyset_hash", "") or "",
        view_content_hash=result.view_content_hash,
        evaluation_corpus_hash=(corpus or {}).get("evaluation_corpus_hash"),
        evaluation_corpus_count=(corpus or {}).get("evaluation_corpus_count"),
        evaluation_corpus_comparable=bool((corpus or {}).get("evaluation_corpus_comparable", False)),
        evaluation_corpus_missing_count=int((corpus or {}).get("evaluation_corpus_missing_count", 0)),
        evaluation_corpus_missing_digest=(corpus or {}).get("evaluation_corpus_missing_digest", "") or "",
        evaluation_corpus_semantics_version=(corpus or {}).get("evaluation_corpus_semantics_version"),
        evaluation_corpus_eligible=bool((corpus or {}).get("evaluation_corpus_eligible", False)),
        evaluation_corpus_eligible_digest=(corpus or {}).get("evaluation_corpus_eligible_digest", "") or "",
        evaluation_corpus_requested_count=(corpus or {}).get("evaluation_corpus_requested_count"),
        evaluation_corpus_requested_digest=(corpus or {}).get("evaluation_corpus_requested_digest", "") or "",
        evaluation_corpus_observation_digest=(corpus or {}).get("evaluation_corpus_observation_digest", "") or "",
        evaluation_corpus_complete=bool((corpus or {}).get("evaluation_corpus_complete", False)),
        evaluation_corpus_integrity=(corpus or {}).get("evaluation_corpus_integrity", "") or "",
    )
    # Preflight encode + decode-validate the complete v2 scope (raises on an incomplete scope for its
    # inferred kind) BEFORE the first metric-row insert — the fail-closed atomicity boundary.
    encoded = encode_analyze_scope_v2(identity)
    if decode_analyze_scope_v2(encoded) != identity:
        raise ValueError(f"analyze-scope encode/decode round trip failed for run {run_id!r}")
    # Aggregate rows: stamped with this run's physical run_id; write_analyze_metrics replaces
    # only this run's own (run_id, strategy scope) rows, never another run's rows.
    db.write_analyze_metrics(con, strategy_key, "catalog", sim_metric, result.k, dict(result.metrics), run_id=run_id)
    # Per-song rows: clear only this strategy scope, then write using the song_retrieval_metrics
    # writer contract (parallel lists keyed by song_ids).  The FIXED historical per-song columns
    # are the artist-ruler-only surface (no DDL): bare ``ap_k``/``mrr``/``recall_k`` are populated
    # from the artist-suffixed ``map_k_artist``/``mrr_artist``/``recall_k_artist`` active values and
    # ``disc_artist_contrib`` from the artist per-song contribution; genre/head per-song is not
    # representable in the flat schema and stays explicitly historical-empty (the writer never
    # pretends a genre/head ruler).
    db.clear_song_retrieval_metrics(con, strategy_key, sim_metric, result.k)
    song_ids = sorted(result.per_song)
    per_song = {
        "song_ids": song_ids,
        "ap_k": [float(result.per_song[s]["map_k_artist"]) for s in song_ids],
        "mrr": [float(result.per_song[s]["mrr_artist"]) for s in song_ids],
        "recall_k": [float(result.per_song[s]["recall_k_artist"]) for s in song_ids],
        "disc_artist_contrib": [float(result.per_song[s]["disc_artist"]) for s in song_ids],
        "disc_genre_contrib": [],
        "disc_head_contrib": [],
    }
    db.write_song_retrieval_metrics(con, strategy_key, sim_metric, result.k, per_song)

    record_analyze_run_scope(
        con,
        run_id=run_id,
        identity=identity,
    )
    return strategy_key
