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
    # writer contract (parallel lists keyed by song_ids).
    db.clear_song_retrieval_metrics(con, strategy_key, sim_metric, result.k)
    song_ids = sorted(result.per_song)
    per_song = {
        "song_ids": song_ids,
        "ap_k": [float(result.per_song[s]["map_k"]) for s in song_ids],
        "mrr": [float(result.per_song[s]["mrr"]) for s in song_ids],
        "recall_k": [float(result.per_song[s]["recall_k"]) for s in song_ids],
        "disc_artist_contrib": [float(result.per_song[s]["within"] - result.per_song[s]["cross"]) for s in song_ids],
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
