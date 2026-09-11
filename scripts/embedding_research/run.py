"""
CLI entrypoint for the embedding research pipeline.

The CLI exposes EXACTLY twelve commands — eight phase verbs plus four maintenance
commands:

  ingest  embed  infer-heads  catalog  catalog-report
  analyze  head-analysis  report
  verify  reindex  cleanup  reset

Only the first three phases (ingest, embed, infer-heads) may discover audio,
load ONNX models, create ML sessions, or run inference.  The five derived
phases (catalog, catalog-report, analyze, head-analysis, report) are CPU-only:
they consume only DuckDB catalog/registry rows, manifests, search views and
frozen stream + head artifacts and never touch audio/models/ONNX/CUDA.

Run one command:

  python run.py <command>

Stratification is catalog input (config/corpus selection), NOT a separate phase.
Any unrecognized command — including the retired legacy names ``stratify``,
``segment``, ``classify``, ``head`` — exits 2 as an ordinary unknown command.
No named alias or compatibility rejection path special-cases them.

Maintenance:

  python run.py verify [--strict]           current-format manifest/digest/WAL audit
  python run.py reindex                      rebuild registry rows from current manifests
  python run.py cleanup --scope {staging|stray|views} [--dry-run]
  python run.py reset --scope analysis [--dry-run]

A single local exclusive run lock guards every command that opens the research
DB or mutates artifacts (all eight phases and the four maintenance commands).
Lock contention exits nonzero (code 2).

All configuration lives in research_config.toml next to this file.  Each phase is
individually idempotent against the frozen DB/streams.  Each of the eight phases records an
auditable run_provenance row (run_id is fresh per invocation) when it performs work; the four
maintenance commands (verify/reindex/cleanup/reset) and a derived phase that skips for lack of
a published catalog are not run_provenance producers.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import logging
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import numpy as np

if TYPE_CHECKING:
    from collections.abc import Callable

# Ensure the workspace root is on sys.path so the package resolves correctly
# when run as `python run.py` inside the container.
_pkg_root = Path(__file__).resolve().parent.parent.parent  # /workspace
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

from scripts.embedding_research.config import DB_PATH, OUTPUT_ROOT
from scripts.embedding_research.helpers.binning import DIST_THRESHOLDS as STD_THRESHOLDS
from scripts.embedding_research.helpers.toml import load_research_config as _load_research_config
from scripts.embedding_research.helpers.toml import load_research_config_bytes as _load_raw_cfg

_log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 4 — explicit phase CLI + run provenance (DD "CLI and provenance").
# ═══════════════════════════════════════════════════════════════════════════════
#
# The CLI exposes EXACTLY eight phases: ingest, embed, infer-heads, catalog,
# catalog-report, analyze, head-analysis, report — plus cleanup and reset as
# EXPLICIT SEPARATE maintenance operations (wired to cleanup.py scopes,
# not to the phase sequence).
#
# CPU/inference boundaries (DD): only the first three phases may discover audio,
# load models, create ML sessions or run ONNX.  The five derived phases are
# routed exclusively through the canonical CPU modules below; they never reach
# the audio/model/ONNX/CUDA surfaces in this file (legacy orchestration,
# model-cache builders).  The former classify.py/head_pooling.py live-ONNX
# surfaces were DELETED in Plan E P1-S5 and no longer exist.  Each derived-phase
# runner imports ONLY from CPU-only modules — see tests
# test_phase4_dispatch_boundaries.py for the structural (phase-call-graph) proof.
#
# Corpus selection is catalog input, NOT a phase: the `catalog` phase catalogs the
# FULL song registry (the legacy common.stratify subset-selection path was deleted in
# the corrective-pass hard cut, so no config-level subset selection remains) and then
# builds the segmentation catalog over that full corpus.  There is no `stratify` CLI
# phase.
#
# run_id scheme: every phase records one auditable run_provenance row per
# invocation.  run_id = "{phase}-{started_at_ms}" (INTEGER millisecond
# timestamp) — FRESH per invocation.  Idempotency is provided by each canonical
# phase's own skip/replace semantics (embed/infer-heads skip already-ready
# streams; catalog reuses config_id by canonical hash and replaces only that
# config's rows; analyze writes run-scoped replace), so run_id is deliberately
# NOT reused across invocations.  `--retained` opts a run into retained=true so
# `cleanup --scope views` GC protects the run's referenced view keyset dirs (view_refs).
# `reset --scope analysis` removes the whole disposable tier (research.duckdb + views)
# regardless — retention never survives reset.  embed / infer-heads / analyze record their own
# run_provenance row(s) inside their canonical modules (single-source); ingest,
# catalog, catalog-report, head-analysis and report have their row recorded
# here by the CLI.
# ═══════════════════════════════════════════════════════════════════════════════

CLI_PHASES: tuple[str, ...] = (
    "ingest",
    "embed",
    "infer-heads",
    "catalog",
    "catalog-report",
    "analyze",
    "head-analysis",
    "report",
)

AUDIO_PHASES: frozenset[str] = frozenset({"ingest", "embed", "infer-heads"})
DERIVED_PHASES: frozenset[str] = frozenset(CLI_PHASES) - AUDIO_PHASES

# A derived-phase runner may import/reference ONLY from these CPU-only modules
# (research-relative dotted paths under ``scripts.embedding_research``).
# (Used by tests/test_phase4_dispatch_boundaries.py as the phase-call-graph
# proof that derived paths cannot reach audio/model/ONNX/CUDA surfaces.)
DERIVED_ALLOWED_IMPORT_ROOTS: frozenset[str] = frozenset(
    {
        # top-level CPU modules
        "catalog",
        "catalog_binding",
        "catalog_identity",
        "catalog_report",
        "config",
        "report",
        "streams",
        # db/* CPU persistence modules
        "db.analyze_scope",
        "db.songs",
        "db.head_phase",
        "db.incomplete_diagnostics",
        # common/* canonical CPU analysis modules
        "common.catalog_analysis",
        "common.head_analysis",
    }
)

# Forbidden on derived-phase paths.  (mirrors the P2-S3 sentinel surfaces)
DERIVED_FORBIDDEN_TOKENS: frozenset[str] = frozenset(
    {
        "discover_audio",
        "create_session",
        "inference_session",
        "_run_in_batches",
        "run_in_batches_fn",
        "onnxruntime",
        "torch",
        "cuda",
        "bootstrap_nomarr",
        "model_cache",
        "classify",
        "head_pooling",
        "segment_fn",
    }
)


# ── provenance / run helpers ───────────────────────────────────────────────────


def _software_versions() -> str:
    """Compact software-version line recorded in run_provenance."""
    return f"python={sys.version.split()[0]} duckdb={duckdb.__version__} numpy={np.__version__}"


def _command_line() -> str:
    """The argv line that invoked this CLI (recorded in run_provenance)."""
    return " ".join(sys.argv)


def _record_phase_run(
    con,
    *,
    run_id: str,
    phase: str,
    status: str,
    started_at: int,
    finished_at: int,
    config_hash: str = "",
    song_count: int = 0,
    warning_count: int = 0,
    retained: bool = False,
    output_artifact_hashes: str = "",
    input_artifact_hashes: str = "",
    structural_change_summary: str = "",
) -> None:
    """Append one run_provenance row for a phase invocation (INTEGER-ms stamps)."""
    from scripts.embedding_research.db.provenance import write_run_provenance

    write_run_provenance(
        con,
        run_id=run_id,
        phase=phase,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        output_artifact_hashes=output_artifact_hashes,
        input_artifact_hashes=input_artifact_hashes,
        config_hash=config_hash,
        song_count=song_count,
        warning_count=warning_count,
        software_versions=_software_versions(),
        command_line=_command_line(),
        structural_change_summary=structural_change_summary,
        retained=retained,
    )


def _mark_run_retained(con, run_id: str, phase: str) -> None:
    """Flip a phase's own provenance row(s) to retained=true (post --retained)."""
    con.execute(
        "UPDATE run_provenance SET retained = 1 WHERE run_id = ? AND phase = ?",
        (run_id, phase),
    )


# ── catalog input generation (stratification-as-input, never a phase) ──────────


def _catalog_seg_configs(cfg: dict) -> list:
    """Build the segmentation-config list for one pass over the frozen binning grid.

    One :class:`~scripts.embedding_research.catalog.SegConfigInput` per
    (backbone, bin_mode, threshold) combination.  Backbones/bin-modes/thresholds
    come from ``cfg``; main populates the bin modes/thresholds from the FROZEN
    helpers/binning constants (``BIN_MODES`` / ``DIST_THRESHOLDS``) — the strict
    loader rejects any ``research_config.toml`` ``[binning]`` section — and they are
    overridable only in tests.
    """
    from scripts.embedding_research.catalog import SegConfigInput

    backbones = cfg.get("backbones") or ["effnet"]
    # Experiment One is the temporal-global/L2 sweep.  Secondary Chebyshev
    # experiments remain possible only through an explicit caller override;
    # they are never mixed into the default primary catalog.
    bin_modes = cfg.get("catalog_bin_modes") or ["temporal_global"]
    thresholds = [float(t) for t in (cfg.get("catalog_thresholds") or STD_THRESHOLDS)]
    return [
        SegConfigInput(
            backbone=backbone,
            bin_mode=bin_mode,
            threshold_configured=threshold,
            threshold_effective=threshold,
            semantics="direct_distance",
        )
        for backbone in backbones
        for bin_mode in bin_modes
        for threshold in thresholds
    ]


def _catalog_corpus_song_ids(con) -> list[str]:
    """Select the corpus subset the `catalog` phase catalogs.

    Corpus selection is canonical ingestion only: the full song registry (the
    set of songs with persisted ingest rows).  The legacy stratification path
    (``common.stratify.run_stratify``) was deleted in the corrective-pass hard
    cut; no config-level subset selection remains, so ``[pipeline].limit`` no
    longer shrinks the cataloged corpus.
    """
    from scripts.embedding_research.db.songs import load_all_songs

    return sorted(r["song_id"] for r in load_all_songs(con))


def _analysis_corpus_song_ids(con, backbone: str) -> list[str]:
    """The catalog-REQUESTED ``(song, backbone)`` population for *backbone* (pre-segmentation).

    *con* is a COMPACT snapshot connection (``handle.con``).  The evaluation-corpus requested
    population is the catalog's requested ``(song_id, backbone)`` surface — every distinct
    song the catalog was built over for *backbone* (``catalog_song`` leaves under its
    canonical ``seg_config`` rows) — resolved BEFORE ``seg_meta`` / representation
    searchability.  A fully-silent requested song (``metadata_only`` ``catalog_song`` leaf,
    no ``seg_meta`` rows) is retained in this requested set so the corpus resolution carries
    it as excluded ``missing`` evidence rather than silently dropping it.
    """
    from scripts.embedding_research.catalog_identity import catalog_requested_song_ids

    return list(catalog_requested_song_ids(con, backbone))


# ── phase runners ──────────────────────────────────────────────────────────────
# ingest / embed / infer-heads are AUDIO phases (may load models / run ONNX).


def _run_ingest(con, cfg: dict, _run_id: str) -> dict:
    """ingest: discover audio + register normalized corpus songs (AUDIO phase)."""
    from scripts.embedding_research.db.songs import load_all_songs
    from scripts.embedding_research.strategy_meta import ingest as _strategy_meta_ingest

    _strategy_meta_ingest(con, force=bool(cfg.get("force", False)))
    return {"song_count": len(load_all_songs(con))}


def _run_embed(con, cfg: dict, run_id: str) -> dict:
    """embed: bounded backbone inference -> immutable streams/registry (AUDIO phase).

    ``cfg['regenerate_masks']`` selects the CPU-only mask-regeneration submode, which
    runs zero ONNX/model/session work and re-derives masks only when the current audio
    fingerprint still equals the committed observation group's.
    """
    from scripts.embedding_research.common.embed import embed as _embed
    from scripts.embedding_research.common.embed import regenerate_masks as _regenerate_masks

    if bool(cfg.get("regenerate_masks", False)):
        tally = _regenerate_masks(
            con,
            backbones=cfg.get("backbones"),
            run_id=run_id,
        )
        # Regeneration is CPU-only (no new stream rows); keep provenance minimal.
        return {
            "self_recorded": True,
            "regenerated": tally["regenerated"],
            "skipped": tally["skipped"],
            "refused": tally["refused"],
            "errors": tally["errors"],
        }

    _embed(
        con,
        force=bool(cfg.get("force", False)),
        backbones=cfg.get("backbones"),
        device=cfg.get("device", "cpu"),
        run_id=run_id,
    )
    # embed records its own run_provenance row (single source).
    return {"self_recorded": True}


def _run_infer_heads(con, cfg: dict, run_id: str) -> dict:
    """infer-heads: aligned classifier head streams -> registry (AUDIO phase)."""
    from scripts.embedding_research.common.infer_heads import infer_heads as _infer_heads

    _infer_heads(
        con,
        force=bool(cfg.get("force", False)),
        backbones=cfg.get("backbones"),
        device=cfg.get("device", "cpu"),
        run_id=run_id,
    )
    # infer-heads records its own run_provenance row (single source).
    return {"self_recorded": True}


# ── phase runners: DERIVED (CPU-only) ──────────────────────────────────────────
# Each derived runner imports only from DERIVED_ALLOWED_IMPORT_ROOTS and never
# references DERIVED_FORBIDDEN_TOKENS (proved by test_phase4_dispatch_boundaries.py).


def _run_catalog(con, cfg: dict, run_id: str) -> dict:
    """catalog: verify streams, select corpus + configs, build seg catalog (CPU)."""
    from scripts.embedding_research.catalog import build_segmentation_catalog
    from scripts.embedding_research.streams import (
        StreamStore,
        make_current_mask_resolver,
        make_current_stream_resolver,
    )

    out_root = cfg.get("output_root") or OUTPUT_ROOT
    configs = _catalog_seg_configs(cfg)
    song_ids = _catalog_corpus_song_ids(con)
    # Catalog producer contract: the catalog phase consumes the SAME complete committed
    # observation group (immutable stream + aligned committed silence mask + commit/identity
    # metadata) that FS reindex and every head-analysis read use.  One store is bound and the
    # SOLE store-backed resolver is constructed per role: the current-stream resolver
    # (``.load(song, backbone) -> float32[P,D] | None``) and the committed-mask resolver
    # (``.load(song, backbone) -> uint8[P] | None``).  ``build_segmentation_catalog`` REFUSES
    # (typed per-input ``MaskRefusalError``) any song whose committed mask is absent or
    # invalid — silence is never inferred from a missing mask, and no ad-hoc or no-mask loader
    # is ever passed here.
    store = StreamStore(con, output_root=str(out_root))
    build_segmentation_catalog(
        make_current_stream_resolver(store),
        make_current_mask_resolver(store),
        configs,
        song_ids,
        output_root=out_root,
        run_id=run_id,
        verify=bool(cfg.get("verify", False)),
    )
    # Durable publication: the catalog phase checkpoints/closes the staged snapshot, derives
    # its manifest, and publishes it under ``catalogs/<catalog_id>/`` + ``catalogs/current.json``
    # LAST (DD L268-287).  Derived phases select the catalog by current.json.
    from scripts.embedding_research import catalog_storage as _cs

    staging_dir = out_root / "catalogs" / f".staging-{run_id}"
    derive_con = duckdb.connect(str(staging_dir / _cs.CATALOG_DB_FILE), read_only=True)
    try:
        manifest = _cs.derive_catalog_manifest(derive_con)
    finally:
        derive_con.close()
    pub_handle = _cs.publish_catalog_snapshot(staging_dir, manifest=manifest)
    _log.info("catalog: published current catalog_id=%s (song_count=%d)", pub_handle.catalog_id, len(song_ids))
    pub_handle.close()
    return {"song_count": len(song_ids)}


def _open_derived_catalog(out_root, phase: str, *, verify: bool = False) -> object | None:
    """Open the AUTHORITATIVE current catalog (``catalogs/current.json``) for a derived phase.

    Delegates to :func:`catalog_storage.open_current_catalog` (never rebuilds, never falls
    back to newest-mtime staging).  ``verify=False`` still enforces selection by
    ``current.json`` plus WAL-bearing / incomplete / structural / identity refusals cheaply;
    ``verify=True`` additionally re-cross-checks the recorded manifest against live logical
    state (the full-content rehash is owned by the standalone ``verify`` command and by
    ``--verify`` derived runs).  Returns a :class:`CatalogHandle` the caller MUST
    ``.close()``, or ``None`` for the true pre-catalog case (``current.json`` has never been
    published because ``catalog`` has not run).  Every typed refusal of an EXISTING-but-unclean
    current catalog (WAL-bearing / incomplete / corrupt / manifest-mismatch) is re-raised as a
    :class:`_CatalogRefusalError` directing the operator to ``verify`` (which owns read-write
    WAL recovery/checkpoint + corruption reporting).  Per DD L272-273 analysis/catalog-report/
    head-analysis therefore refuse on an unclean current catalog instead of silently reading
    a stale/newest candidate.
    """
    from scripts.embedding_research import catalog_storage as _cs

    try:
        return _cs.open_current_catalog(Path(out_root), verify=verify)
    except _cs.CatalogMissingError:
        # No current.json yet (``catalog`` never published) -> the pre-catalog warn/skip case.
        return None
    except _cs.CatalogWalError as exc:
        raise _CatalogRefusalError(
            f"phase {phase!r}: current catalog is WAL-bearing (not clean-closed): {exc}. "
            "Run `verify` to recover/checkpoint it; a read-only analysis never recovers a WAL."
        ) from exc
    except _cs.CatalogIncompleteError as exc:
        raise _CatalogRefusalError(
            f"phase {phase!r}: current catalog is incomplete: {exc}. Run `verify` for details."
        ) from exc
    except _cs.CatalogCorruptionError as exc:
        raise _CatalogRefusalError(
            f"phase {phase!r}: current catalog is corrupt: {exc}. Run `verify` for details."
        ) from exc
    except _cs.CatalogMismatchError as exc:
        raise _CatalogRefusalError(
            f"phase {phase!r}: current catalog disagrees with its recorded manifest: {exc}. "
            "Run `verify` to confirm corruption."
        ) from exc


def _warn_no_catalog(phase: str) -> None:
    _log.warning(
        "%s: no canonical catalog published yet (catalogs/current.json absent); run `catalog` first",
        phase,
    )


def _run_catalog_report(_con, cfg: dict, _run_id: str) -> dict:
    """catalog-report: render catalog configs/aliases/segments + provenance (CPU).

    Reads the COMPACT snapshot: opens the current catalog handle and passes
    ``catalog_report(handle.con, handle)`` (the §C handle form) so the fingerprint /
    exact-search hash / catalog reads hit the compact tables.  When no compact snapshot
    exists it warns and skips (never routes the research connection into the now-compact-only
    readers).
    """
    from scripts.embedding_research.catalog_report import catalog_report, report_to_text

    out_root = Path(cfg.get("output_root") or OUTPUT_ROOT)
    handle = _open_derived_catalog(out_root, "catalog-report")
    if handle is None:
        _warn_no_catalog("catalog-report")
        return {"song_count": 0}
    try:
        report = catalog_report(handle.con, handle)
    finally:
        handle.close()
    out_dir = Path(cfg.get("report_dir") or OUTPUT_ROOT)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "catalog_report.txt").write_text(report_to_text(report), encoding="utf-8")
    _log.info("catalog-report: canonical configs=%d aliases=%d", len(report.canonical_config_ids), report.alias_count)
    return {"song_count": 0, "output_artifact_hashes": "catalog_report.txt"}


def _run_analyze(con, cfg: dict, run_id: str) -> dict:
    """analyze: gather disposable views + bounded exact scoring -> run-scoped metrics (CPU).

    Two-connection model (S6/S8 established): the corpus + every catalog read
    (configs / ``seg_meta`` / ``searchable_weight``) comes from the COMPACT snapshot
    via ``handle.con``; the research *con* is retained for disposable
    view/analyze-metrics/provenance writes.  Both the handle and *con* stay open
    for the whole phase; the handle is closed in ``finally``.

    The phase emits one leave-one-out scored ``analyze_metrics`` pass per current
    SearchRepresentationClass (per-class scheduling), and — MANDATORILY, never behind any
    config flag or argparse option — exactly ONE observed ``global_pool:{backbone}:medoid``
    baseline row per successfully analyzed backbone, emitted AFTER the per-class loop, over
    the SAME resolved evaluation corpus / scorer / ``k`` / sim_metric (``cosine``) / lenses as
    the segmented class passes.  A requested backbone that cannot yield that observed baseline
    (its evaluation corpus is not analyzable, or fewer than two searchable medoid songs make
    leave-one-out undefined) FAILS the analyze scope with :class:`AnalyzeRefusalError` — never
    a successful baseline-less scope and never a fabricated baseline vector.

    One explicit :class:`~scripts.embedding_research.catalog_identity.EvaluationCorpusIdentity`
    is resolved per backbone at this analyze boundary and threaded into every segmented class pass
    and the whole-song baseline, so all passes share the SAME eligible population.  A sub-2 eligible
    corpus (``eligible == False``) refuses the analyze scope (no partial complete outcome); a
    segmented class whose representation loses an eligible song's searchable medoid is
    ``not comparable`` — never an ``analyze_metrics`` row or a complete ``analyze_scope_v2`` line —
    and is RETAINED to be persisted as a durable versioned diagnostic only after that backbone's
    mandatory observed baseline succeeds (Plan B P2).

    Invocation lifecycle (execution-reporting Plan B P1/P2): before the per-backbone loop the
    invocation anchors its declared obligations via ``record_analyze_invocation`` (every requested
    backbone that will actually be analyzed, each carrying that backbone's MANDATORY observed
    ``global_pool:{backbone}:medoid`` baseline key) so the ledger starts ``running`` BEFORE any
    segmented pass.  Within each backbone, per-class catalog-bound corpus resolution + segmented
    analysis runs and every non-comparable representation is retained in a per-backbone pending
    list.  Only after that backbone's mandatory observed ``global_pool:{backbone}:medoid`` baseline
    succeeds (``run_and_persist_medoid_baseline`` returned non-None) is each retained non-comparable
    result durably persisted via ``write_incomplete_analyze_diagnostic`` — never as an
    ``analyze_metrics`` row or a complete ``analyze_scope_v2`` line.  After the WHOLE loop body
    succeeds, ``terminalize_analyze_completed`` re-validates each declared baseline's
    ``analyze_metrics`` evidence and raises (-> a ``failed`` analyze row) if any obligation is
    unresolved, so a partial scope is never recorded as a clean completed invocation.  Any exception
    mid-body (after an earlier class or on a later backbone) propagates past the terminalize point,
    leaving the invocation open + a ``failed`` provenance row; partial evidence is never deleted.
    """
    from scripts.embedding_research.common.catalog_analysis import (
        AnalyzeRefusalError,
        CatalogAnalysisConfig,
        analyze_catalog_corpus,
        resolve_head_ruler_labels,
        run_and_persist_medoid_baseline,
    )
    from scripts.embedding_research.db.analyze_scope import write_catalog_analyze_rows
    from scripts.embedding_research.db.incomplete_diagnostics import write_incomplete_analyze_diagnostic
    from scripts.embedding_research.db.songs import load_all_songs
    from scripts.embedding_research.streams import StreamStore

    out_root = Path(cfg.get("output_root") or OUTPUT_ROOT)
    handle = _open_derived_catalog(out_root, "analyze")
    if handle is None:
        _warn_no_catalog("analyze")
        return {"song_count": 0, "self_recorded": True}
    try:
        store = StreamStore(con, output_root=str(out_root))
        # Ruler label sources (amended P3-S1) come from the PERSISTED ``songs`` table.  A null/blank
        # artist or genre is a MISSING label for that ruler (a per-ruler exclusion) and is NEVER
        # substituted with ``"unknown"`` — the historic ``(r["artist"] or "unknown")`` coercion is
        # gone so a missing label is not fabricated into a same-artist relevance group.
        _song_rows = load_all_songs(con)
        artists = {r["song_id"]: r["artist"] for r in _song_rows}
        genres = {r["song_id"]: r["genre"] for r in _song_rows}
        total = 0
        # Obligation-backed invocation lifecycle (execution-reporting Plan B P1): an analyze
        # invocation records its declared obligations (every requested backbone that will be
        # analyzed, plus that backbone's MANDATORY observed ``global_pool:{backbone}:medoid``
        # baseline) as a RUNNING ledger record BEFORE any segmented pass, then terminalizes
        # ``completed`` only after the whole phase body finishes with every obligation resolved.
        # Scope/evidence rows are append-only and NEVER terminalize the invocation; any exception
        # (after an earlier class or on a later backbone) propagates past the terminalize point,
        # leaving the invocation open and a ``failed`` analyze provenance row in its place.
        from scripts.embedding_research.db.analyze_scope import (
            record_analyze_invocation,
            terminalize_analyze_completed,
        )

        requested = cfg.get("backbones") or ["effnet"]
        # A requested backbone is an obligation only when it has a cataloged corpus that will
        # ACTUALLY be analyzed (mirrors the loop's eligibility gating): corpus-less backbones are
        # skipped with a warning, and a sub-2-eligible corpus REFUSES below — so a backbone that
        # will refuse is never claimed as an obligation and never leaves a ``complete`` invocation
        # anchor behind (the whole run fails closed on the refused backbone instead).  Each
        # obligation carries its backbone's MANDATORY observed ``global_pool:{backbone}:medoid``
        # baseline key (the same literal the baseline writer persists under).
        from scripts.embedding_research.catalog_identity import resolve_evaluation_corpus

        _attempted: list[tuple[str, str]] = []
        for _bb in requested:
            _songs = _analysis_corpus_song_ids(handle.con, _bb)
            if not _songs:
                continue
            _identity = resolve_evaluation_corpus(handle.con, store, _songs, backbone=_bb)
            if not _identity.eligible:
                continue
            _attempted.append((str(_bb), f"global_pool:{_bb}:medoid"))
        if _attempted:
            record_analyze_invocation(con, run_id=run_id, backbones=_attempted)
        for backbone in requested:
            song_ids = _analysis_corpus_song_ids(handle.con, backbone)
            if not song_ids:
                _log.warning("analyze: no cataloged corpus for backbone %r — run `catalog` first", backbone)
                continue
            # Resolve the backbone's ONE explicit evaluation-corpus identity at the analyze boundary
            # and reuse that SAME population (never re-derived from a later catalog or a disposable
            # view keyset/content hash) across every segmented class pass and the whole-song baseline.
            from scripts.embedding_research.catalog_identity import (
                collapse_search_representations,
                resolve_evaluation_corpus,
            )

            identity = resolve_evaluation_corpus(handle.con, store, song_ids, backbone=backbone)
            if not identity.eligible:
                # A sub-2 eligible corpus cannot yield the MANDATORY leave-one-out observed baseline.
                # This is NOT a silent success: recording nothing and continuing would present a
                # successful baseline-less scope for the requested backbone, so the analyze scope
                # FAILS CLOSED (execution-reporting Plan A P2-S1) — never a fabricated baseline.
                raise AnalyzeRefusalError(
                    f"analyze: backbone {backbone!r} evaluation corpus has {identity.count} eligible "
                    f"song(s) (need >= 2); the mandatory observed global-pool medoid baseline cannot be "
                    f"computed — analyze scope refuses"
                )
            population = identity.song_ids
            # Apparatus Plan A P1-S2: bind every derived phase to the catalog observation
            # version.  Before ANY gathering/search, segmented class pass, or the mandatory
            # observed global-medoid baseline for this backbone, verify the CURRENT committed
            # observation group for every requested song matches the evidence the catalog
            # recorded at build time EXACTLY; a superseded/newer/older/mismatched group is a
            # typed refusal (never a silent rebind to another committed group).  The same
            # fail-closed seam guards head analysis in ``_run_head_analysis``.
            from scripts.embedding_research.catalog_binding import verify_catalog_observation_binding

            verify_catalog_observation_binding(handle.con, store, backbone=backbone, song_ids=population)
            # Head ruler (amended P3-S1): resolve the frozen committed semantic-head label for every
            # eligible song ONCE per backbone (the committed head suite is representation-independent
            # and identical across class passes and the medoid baseline).  EffNet-only and CPU-only;
            # a song missing its marker-aligned committed suite/mask/binary head simply gets NO head
            # label (excluded from the head ruler), while a present non-finite pooled value raises.
            head_labels = resolve_head_ruler_labels(store, out_root, tuple(population), backbone=backbone)
            # Per-class scheduling: each distinct current SearchRepresentationClass over this
            # backbone's participating configs is analyzed as its OWN leave-one-out pass over only
            # that class's canonical rows, persisted as its own analyze_scope strategy row.  Alias
            # configs add zero passes and are never appended to any candidate union.
            from scripts.embedding_research import catalog as _catalog

            backbone_cids = {c.config_id for c in _catalog.compact_configs_by_backbone(handle.con, backbone)}
            # Non-comparable representations for this backbone are RETAINED (execution-reporting Plan
            # B P2): a skipped class is never an ``analyze_metrics`` row and never a complete
            # ``analyze_scope_v2`` line — its only durable evidence is a versioned diagnostic, written
            # ONLY after this backbone's mandatory observed baseline below succeeds (never on the
            # refusal/failure path — fail closed, no orphan rows).
            _pending_incomplete: list = []
            for cls in collapse_search_representations(handle.con):
                members = tuple(sorted(c for c in cls.config_ids if c in backbone_cids))
                if not members:
                    continue
                analysis_cfg = CatalogAnalysisConfig(
                    run_id=run_id,
                    backbone=backbone,
                    song_ids=population,
                    artists=artists,
                    genres=genres,
                    head_labels=head_labels,
                    k=int(cfg.get("k", 10)),
                    config_ids=members,
                    evaluation_corpus=identity,
                )
                result = analyze_catalog_corpus(store, handle.con, analysis_cfg, research_con=con)
                if not result.comparable:
                    # Missing-medoid invalidation (execution-reporting P1-S3): an eligible whole-song
                    # song lost its searchable segment medoid in this representation (PTC absorption),
                    # so this partial configuration is NOT recorded as a complete outcome.  It is
                    # RETAINED and its diagnostic is persisted only after the mandatory baseline below
                    # succeeds (Plan B P2) — never as an ``analyze_metrics`` row or a complete scope.
                    _log.warning(
                        "analyze: backbone %r representation config_ids=%s is not comparable; "
                        "%d eligible song(s) lost a searchable medoid (%s) — not recorded as complete, "
                        "diagnostic queued until the mandatory baseline succeeds",
                        backbone,
                        members,
                        result.missing_count,
                        ",".join(result.missing_song_ids),
                    )
                    _pending_incomplete.append(result)
                    continue
                write_catalog_analyze_rows(con, run_id=run_id, result=result)

            # MANDATORY (execution-reporting Plan A P2): emit exactly ONE observed global-medoid
            # baseline metric identity per successfully analyzed backbone, after the per-class loop.
            # This is an ADDITIONAL scored retrieval pass — NOT a class: each searchable song is
            # represented by its observed whole-song global medoid, zero-searchable songs are
            # excluded, and the pass never unions with class candidates, adds no class execution, and
            # is never a winner candidate.  It is persisted run-scoped under strategy_type !=
            # 'catalog' so report's catalog-only query_analyze_metrics keeps excluding it from
            # section_analysis; the winners loader reads it through a distinct path.  The baseline is
            # MANDATORY and UNCONDITIONAL — there is no opt-in emit gate and no hidden config/fixture
            # switch — so a backbone whose mandatory observed baseline cannot be produced
            # (run_and_persist_medoid_baseline returns ``None``) FAILS CLOSED.
            # Resolve the compact catalog anchor (id + manifest fingerprint) once per backbone so the
            # mandatory baseline scope carries the same durable catalog identity as the class scopes.
            # This FAILS CLOSED exactly like the class-scope identity resolution above (the
            # catalog_class path refuses an incomplete anchor): a baseline scope is NEVER recorded
            # with a partial anchor — catalog_id beside an EMPTY fingerprint — on the failure path
            # the class scopes refuse.  A missing compact catalog_metadata singleton refuses, and a
            # fingerprint-derivation failure PROPAGATES (no broad suppression/silent '' fallback) so
            # the observed baseline cannot silently weaken its durable identity.
            from scripts.embedding_research.catalog_identity import catalog_fingerprint

            _meta = handle.con.execute(
                "SELECT catalog_id, schema_version FROM catalog_metadata ORDER BY catalog_id LIMIT 1"
            ).fetchone()
            if _meta is None:
                raise AnalyzeRefusalError(
                    "analyze: cannot resolve the mandatory observed-baseline catalog anchor: "
                    "compact catalog_metadata singleton is missing"
                )
            _cat_id = str(_meta[0])
            _cat_fp = catalog_fingerprint(handle.con, schema_version=int(_meta[1]))
            baseline_metrics = run_and_persist_medoid_baseline(
                con,
                store,
                run_id=run_id,
                backbone=backbone,
                song_ids=population,
                artists=artists,
                genres=genres,
                head_labels=head_labels,
                k=int(cfg.get("k", 10)),
                evaluation_corpus=identity,
                catalog_id=_cat_id,
                catalog_fingerprint=_cat_fp,
            )
            if baseline_metrics is None:
                raise AnalyzeRefusalError(
                    f"analyze: backbone {backbone!r} cannot produce the mandatory observed "
                    f"global_pool:{backbone}:medoid baseline (fewer than two searchable medoid songs) "
                    f"— analyze scope refuses"
                )
            # Plan B P2: this backbone's MANDATORY observed baseline succeeded, so every retained
            # non-comparable representation is now durably persisted as a versioned, report-readable
            # diagnostic (scoped replacement by ``(run_id, strategy_key, sim_metric, k)``).  If this
            # backbone (or a later one) later fails, the Phase-1 invocation veto already excludes the
            # whole run from clean completed-report selection, so these diagnostics are never rendered
            # as a clean completed report.
            for _inc in _pending_incomplete:
                write_incomplete_analyze_diagnostic(
                    con,
                    run_id=run_id,
                    result=_inc,
                    baseline_corpus=identity,
                    reason=(
                        f"segmented representation is non-comparable: {_inc.missing_count} "
                        f"eligible whole-song song(s) lost a searchable segment medoid in this "
                        f"representation ({','.join(_inc.missing_song_ids)}); NOT recorded as a "
                        "complete analyze_metrics/scope — its evidence is this diagnostic"
                    ),
                )
            total += len(song_ids)
    finally:
        handle.close()
    # Reaching here means every requested-and-attempted backbone completed its per-class passes
    # AND emitted its MANDATORY observed medoid baseline (any failure would have raised earlier).
    # Terminalize the invocation COMPLETED only now, after every obligation resolved; the
    # terminalizer re-validates each declared backbone's baseline evidence and refuses (raises ->
    # a ``failed`` analyze row) if any obligation is unresolved, so a partial scope is never
    # recorded as a clean completed invocation.
    if _attempted:
        terminalize_analyze_completed(con, run_id=run_id)
    # analyze records its own run_provenance row via materialize/record_*_scope.
    return {"song_count": total, "self_recorded": True}


def _run_head_analysis(con, cfg: dict, run_id: str) -> dict:
    """head-analysis: CPU head pooling over exact compact M_g memberships (CPU).

    Opens the latest COMPACT snapshot locally for catalog reads (the runner reconstructs
    each segment's exact searchable ``M_g`` from compact ``seg_meta`` rows over the same
    committed silence mask that built the catalog) and retains the research connection
    ``con`` for the ``HeadStreamStore`` and coverage/skip provenance writes.  When no
    compact snapshot exists it warns and skips (never routes the research connection into
    the compact-only reader).  P1-S11 aligns preflight detection with this same resolver.
    """
    from scripts.embedding_research.common.head_analysis import run_shared_catalog_head_analysis
    from scripts.embedding_research.db.head_phase import (
        build_head_phase_provenance_rows,
        write_head_phase_provenance,
    )
    from scripts.embedding_research.streams import HeadStreamStore, StreamStore, make_current_mask_resolver

    out_root = Path(cfg.get("output_root") or OUTPUT_ROOT)
    handle = _open_derived_catalog(out_root, "head-analysis")
    if handle is None:
        _warn_no_catalog("head-analysis")
        return {"song_count": 0}
    store = StreamStore(con, output_root=str(out_root))
    mask_store = make_current_mask_resolver(store)
    head_store = HeadStreamStore(con, output_root=str(out_root))
    # Apparatus Plan A P1-S2: bind shared head analysis to the catalog observation version
    # BEFORE the runner gathers any head stream.  Shared catalog head analysis is an EffNet
    # backbone phase, so bind every catalog-recorded EffNet song against its CURRENT committed
    # group — a superseded/newer/older/mismatched group is a typed refusal.
    from scripts.embedding_research.catalog_binding import verify_catalog_observation_binding

    head_song_ids = [
        str(r[0])
        for r in handle.con.execute(
            "SELECT DISTINCT song_id FROM observation_evidence WHERE backbone = 'effnet' ORDER BY song_id"
        ).fetchall()
    ]
    if head_song_ids:
        verify_catalog_observation_binding(handle.con, store, backbone="effnet", song_ids=head_song_ids)
    try:
        manifest = run_shared_catalog_head_analysis(
            handle,
            head_store,
            mask_store=mask_store,
            run_id=run_id,
        )
    finally:
        handle.close()
    rows = build_head_phase_provenance_rows(manifest)
    write_head_phase_provenance(con, rows)
    _log.info(
        "head-analysis: run_id=%s done=%d skipped=%d errors=%d finite=%s",
        run_id,
        manifest.done,
        manifest.skipped,
        manifest.errors,
        manifest.finite,
    )
    return {"song_count": len(manifest.song_ids)}


def _completed_analyze_run_ids(con) -> list[str]:
    """Completed ``analyze`` run ids present in ``run_provenance``, oldest first.

    Completion is decided PER ``run_id`` by grouping every ``phase == 'analyze'`` provenance row
    for that run (append-only ``run_provenance`` has no PK/UNIQUE on ``run_id``, so a run may hold
    several same-phase rows — the analyze producer's own scope rows and wrapper recordings).  The
    base predicate for a completed run is: it has at least one ``phase == 'analyze'`` row with
    status ``complete``/``completed``, and NONE of its analyze rows has status ``failed``.  A single
    failed analyze row vetoes the ENTIRE run, so a contradictory run carrying both completed analyze
    rows and a later failed analyze row never surfaces as a completed scope and can never render
    partial metrics as a completed report.  For an invocation-backed run (see below) this base
    predicate is necessary but NOT sufficient — it must also be a clean all-obligation terminal
    invocation.

    Obligation-gated completion: an invocation-backed run (its analyze rows carry an
    ``analyze_invocation_v1`` obligations record written by the Plan-B producer) is completed only when
    that record is paired with a ``completed`` ``analyze_terminal_v1`` terminal record — scope/evidence
    rows alone NEVER terminalize an invocation.  A pre-obligation run (no invocation record; e.g.
    historical/synthetic scope-only rows) falls back to the historical scope-evidence predicate (>=1
    ``complete``/``completed`` analyze row, no ``failed``), keeping such runs reportable exactly as
    before.  This is the deterministic completion signal the report phase resolves — there is no status
    column on ``analyze_metrics`` itself, so completion lives in ``run_provenance``.
    The returned ids are deduplicated (one entry per completed run) and deterministically ordered:
    ascending representative ``finished_at``/``started_at`` (integer ms; the existing fallback chain
    ``finished_at or started_at or 0``, with the EARLIEST stamp among the run's non-failed
    complete/completed analyze rows chosen as that run's representative) then ascending ``run_id``.
    """
    from scripts.embedding_research.db.analyze_scope import (
        INVOCATION_MARKER_PREFIX,
        TERMINAL_MARKER_PREFIX,
        TERMINAL_OUTCOME_COMPLETED,
    )
    from scripts.embedding_research.db.provenance import read_run_provenance

    analyze_rows = [r for r in read_run_provenance(con) if r["phase"] == "analyze"]

    # Group every analyze row by run_id; a failed row vetoes the whole run.  Obligation/terminal
    # marker lines may ride on any of the run's analyze rows (the Plan-B producer merges them into
    # the same append-only row that carries the scope lines), so obligations-presence and the
    # completed terminal are read from the rows' output lines, not from any status column.  The
    # representative stamp is the earliest ``finished_at``/``started_at`` among the run's non-failed
    # complete/completed analyze rows (unchanged for pre-obligation scope-only runs).
    _buckets: dict[str, dict] = {}
    for row in analyze_rows:
        rid = str(row["run_id"])
        bucket = _buckets.setdefault(
            rid,
            {"failed": False, "obligations_present": False, "terminal_completed": False},
        )
        if row["status"] == "failed":
            bucket["failed"] = True
            continue
        if row["status"] in {"complete", "completed"}:
            stamp = int(row.get("finished_at") or row.get("started_at") or 0)
            if bucket.get("stamp") is None or stamp < bucket["stamp"]:
                bucket["stamp"] = stamp
        for _ln in (row.get("output_artifact_hashes") or "").splitlines():
            _line = _ln.strip()
            if not _line:
                continue
            if _line.startswith(INVOCATION_MARKER_PREFIX + "|"):
                bucket["obligations_present"] = True
            elif _line.startswith(TERMINAL_MARKER_PREFIX + "|"):
                try:
                    _outcome = json.loads(_line.split("|", 1)[1]).get("outcome")
                except (ValueError, TypeError):
                    _outcome = None
                if _outcome == TERMINAL_OUTCOME_COMPLETED:
                    bucket["terminal_completed"] = True

    def _is_completed(bucket: dict) -> bool:
        if bucket["failed"]:
            return False
        if bucket["obligations_present"]:
            # Scopes/evidence never terminalize an invocation-backed run: it must carry the
            # completed terminal (written only after every obligation resolved).
            return bucket["terminal_completed"]
        # Pre-obligation (historical/synthetic) scope-only run: existing scope-evidence predicate.
        return bucket.get("stamp") is not None

    completed = [
        (rid, bucket["stamp"])
        for rid, bucket in _buckets.items()
        if _is_completed(bucket) and bucket.get("stamp") is not None
    ]
    completed.sort(key=lambda kv: (kv[1], kv[0]))
    return [rid for rid, _stamp in completed]


def _resolve_report_run_id(con, cfg: dict) -> str | None:
    """Resolve the completed analyze scope the report phase renders.

    Operates on the grouped per-run completion set from :func:`_completed_analyze_run_ids`: a run
    counts as a completed analyze scope only when at least one of its ``analyze`` rows is
    ``complete``/``completed`` AND none is ``failed`` — any failed analyze row vetoes the whole run
    whatever its other rows claim, so a contradictory complete-plus-failed run is never resolvable.
    Returns the run_id the report must be scoped to (never blends runs):

    * ``cfg["report_run_id"]`` is honoured only when it names a completed analyze run; a
      contradictory (or incomplete/bogus) run is not completed, so ``None`` is returned here and the
      caller rejects the request (explicit-but-incomplete, fail closed).
    * With no explicit request, the most recent CLEAN completed analyze run is returned — a newer
      contradictory run falls through to the newest clean completed run.
    * With no completed analyze run at all, ``None`` is returned (the caller renders an empty
      report or rejects when run-scoped analyze rows are orphaned).
    """
    requested = cfg.get("report_run_id")
    completed = _completed_analyze_run_ids(con)
    if requested is not None:
        return requested if requested in completed else None
    return completed[-1] if completed else None


def _run_report(con, cfg: dict, _run_id: str) -> dict:
    """report: render results + provenance, never infers (CPU).

    Renders a single completed scope: ``cfg["report_run_id"]`` when it names a completed analyze
    run, otherwise the most recent completed analyze run resolved deterministically from
    ``run_provenance`` via the grouped per-run predicate — a run with any failed ``analyze`` row is
    NOT completed (the failed row vetoes the whole run) and is therefore never selected and is
    refused when named explicitly.  Incomplete scopes are rejected rather than silently blended
    into a whole-set read — either run-scoped ``analyze_metrics`` rows with no completed analyze
    scope, or an explicitly requested scope that is not a completed analyze run (including a
    contradictory complete-plus-failed run).  An empty database (no run-scoped analyze rows)
    renders an empty report, preserving the preflight-warned path.
    """
    from scripts.embedding_research.config import REPORT_DIR as _REPORT_DIR
    from scripts.embedding_research.report import run as _report_run

    out_dir = Path(cfg.get("report_dir") or _REPORT_DIR)
    run_id = _resolve_report_run_id(con, cfg)
    if run_id is None and (cfg.get("report_run_id") is not None or _has_analyze_metrics(con)):
        if cfg.get("report_run_id") is not None:
            msg = (
                "phase 'report': requested report scope run_id="
                f"{cfg['report_run_id']!r} is not a completed analyze scope; "
                "run `analyze` to completion for that run"
            )
        else:
            msg = (
                "phase 'report': run-scoped analyze_metrics rows are present but no completed "
                "analyze scope is recorded; run `analyze` to completion (refusing to blend runs)"
            )
        raise _MissingArtifactError(msg)
    _report_run(con, out_dir, run_id=run_id)
    return {"song_count": 0, "output_artifact_hashes": "report.json,report.html"}


CLI_PHASE_RUNNERS: dict[str, Callable[..., dict]] = {
    "ingest": _run_ingest,
    "embed": _run_embed,
    "infer-heads": _run_infer_heads,
    "catalog": _run_catalog,
    "catalog-report": _run_catalog_report,
    "analyze": _run_analyze,
    "head-analysis": _run_head_analysis,
    "report": _run_report,
}


# ── single-phase executor (provenance wrapper) ─────────────────────────────────


_DERIVED_CONSUMER_PHASES = frozenset({"catalog-report", "analyze", "head-analysis", "report"})


def _has_canonical_catalog(con) -> bool:
    """True when the COMPACT snapshot has at least one ``seg_config`` row.

    *con* is the compact snapshot connection (``handle.con``); the snapshot stores only
    canonical configs (no alias graph), so a present catalog is exactly a non-empty
    ``seg_config``.
    """
    n = con.execute("SELECT count(*) FROM seg_config").fetchone()[0]
    return bool(n)


def _has_analyze_metrics(con) -> bool:
    """True when at least one run-scoped ``analyze_metrics`` row exists.

    Every ``analyze_metrics`` row is run-scoped (there is no pre-cut legacy partition), so the
    presence of any row is the presence of run-scoped rows.
    """
    n = con.execute("SELECT count(*) FROM analyze_metrics").fetchone()[0]
    return bool(n)


def _canonical_config_duplicates(con) -> int:
    """Count of COMPACT seg_config identities (by canonical_config_hash) that collide.

    *con* is the compact snapshot connection (``handle.con``); the snapshot holds only
    canonical configs, so every ``seg_config`` row participates in identity collapse and
    no ``alias_of_config_id`` filter applies.
    """
    return int(
        con.execute(
            "SELECT count(*) FROM ("
            "  SELECT canonical_config_hash FROM seg_config"
            "  GROUP BY canonical_config_hash HAVING count(*) > 1)"
        ).fetchone()[0]
    )


def _incomplete_catalog_committed_groups(con, cfg) -> list[str]:
    """Requested catalog input ``(song, backbone)`` pairs lacking a COMPLETE committed group.

    A song/backbone is catalogable only when it has a complete committed observation group
    (immutable stream + aligned committed silence mask + commit/identity marker) — the same
    group-level READY predicate FS reindex and the runtime resolvers use.  Returns
    ``"song:backbone"`` keys for every requested ``(song, backbone)`` whose committed group is
    not ready, so the catalog preflight can refuse them before any catalog construction treats
    an incomplete input as valid.  A registry row claiming ``ready`` never authorises a group.
    """
    from scripts.embedding_research.streams import StreamStore, observation_group_ready

    out_root = Path(cfg.get("output_root") or OUTPUT_ROOT)
    store = StreamStore(con, output_root=str(out_root))
    songs = _catalog_corpus_song_ids(con)
    if not songs:
        return []
    backbones = cfg.get("backbones") or ["effnet"]
    return [
        f"{song_id}:{backbone}"
        for backbone in backbones
        for song_id in songs
        if not observation_group_ready(store, song_id, backbone)
    ]


def _preflight_derived_phase(con, phase: str, cfg: dict, *, db_path=None) -> list[str]:
    """Post-crash canary + artifact-presence gate for the five derived phases.

    Thin by default: a clean run with no ``--verify`` and no detected post-crash
    state performs only the cheap post-crash detection and returns immediately.
    ``--verify`` (and therefore ``--strict``) additionally run the rollback-only
    canary over every surviving PK/UNIQUE table (DD ``Post-crash verification
    canary``) and check required derived inputs are present.  Under ``--strict``
    any recorded corruption, unresolved duplicate, or missing required artifact
    becomes a hard refusal (raised here, recorded as a ``failed`` provenance row,
    and propagated to the caller).  Plain ``--verify`` records the same conditions
    as warnings and continues — never blocks on a warning.

    Returns the list of verification/reuse notes to fold into the phase's
    run_provenance ``structural_change_summary`` / ``warning_count``.
    """
    if phase not in DERIVED_PHASES:
        return []
    verify = bool(cfg.get("verify"))
    strict = bool(cfg.get("strict"))
    from scripts.embedding_research.db.canary import detect_post_crash, run_rollback_canary

    post_crash = detect_post_crash(con, db_path=db_path)
    if not verify and not post_crash:
        return []  # thin gate: clean run without --verify pays no probe cost.

    notes: list[str] = []
    # 1) rollback-only canary over every surviving PK/UNIQUE table.
    canary_report = run_rollback_canary(con)
    notes.append(f"canary ok: {len(canary_report.ok)} probed, {len(canary_report.empty)} empty")
    # 1b) the catalog PRODUCER consumes complete committed observation groups.  Before any
    #     catalog construction, refuse (strict) / warn (verify) requested inputs that lack a
    #     complete committed group (stream + aligned committed mask + commit marker) so an
    #     incomplete input is never handed to build_segmentation_catalog as if it were valid.
    if phase == "catalog":
        gaps = _incomplete_catalog_committed_groups(con, cfg)
        if gaps:
            msg = (
                f"phase 'catalog': {len(gaps)} requested input(s) lack a complete committed "
                f"observation group (stream+aligned-mask+commit): {', '.join(gaps)}. Catalog "
                "refuses incomplete inputs — run `embed` to publish complete committed groups."
            )
            if strict:
                raise _MissingArtifactError(msg)
            notes.append(f"warning: {msg}")
        return notes
    # 2) required derived inputs (only consumers read catalog/analyze artifacts).  The
    #    catalog-presence / duplicate checks read the COMPACT snapshot (opened via the
    #    shared resolver and closed here); only report's analyze_metrics probe reads the
    #    research connection (disposable metrics live there).
    if phase in _DERIVED_CONSUMER_PHASES:
        try:
            handle = _open_derived_catalog(Path(cfg.get("output_root") or OUTPUT_ROOT), phase)
        except _CatalogRefusalError as exc:
            # An unclean EXISTING current catalog is a hard refusal under --strict; under
            # plain --verify it is recorded (the phase runner itself refuses unconditionally
            # per DD L272-273).
            if strict:
                raise
            notes.append(f"warning: {exc}")
            return notes
        try:
            if handle is None:
                msg = f"phase {phase!r}: no canonical catalog present (run `catalog` first)"
                if strict:
                    raise _MissingArtifactError(msg)
                notes.append(f"warning: {msg}")
            elif phase == "report" and not _has_analyze_metrics(con):
                msg = "phase 'report': no run-scoped analyze_metrics rows present to render"
                if strict:
                    raise _MissingArtifactError(msg)
                notes.append(f"warning: {msg}")
            elif _canonical_config_duplicates(handle.con):
                msg = f"phase {phase!r}: unresolved duplicate canonical config identity"
                if strict:
                    raise _DuplicateIdentityError(msg)
                notes.append(f"warning: {msg}")
            else:
                notes.append(f"{phase}: reuse existing verified catalog/analyze inputs")
        finally:
            if handle is not None:
                handle.close()
    return notes


class _MissingArtifactError(RuntimeError):
    """Raised under ``--verify --strict`` when a required derived input is absent."""


class _DuplicateIdentityError(RuntimeError):
    """Raised under ``--verify --strict`` on an unresolved duplicate application identity."""


class _CatalogRefusalError(RuntimeError):
    """Raised when an EXISTING-but-unclean current catalog refuses to open (WAL/incomplete/
    corrupt/mismatch).  Propagates as a phase refusal (exit 1) directing the operator to
    ``verify``, per DD L272-273 — never falls back to a stale/newest staging candidate."""


def _run_single_phase(con, phase: str, cfg: dict, *, db_path=None) -> None:
    """Execute exactly one CLI phase with run-scoped provenance."""
    started_at = int(time.time() * 1000)
    run_id = cfg.get("run_id") or f"{phase}-{started_at}"
    runner = CLI_PHASE_RUNNERS[phase]
    meta: dict = {}
    pre_notes: list[str] = []
    try:
        pre_notes = _preflight_derived_phase(con, phase, cfg, db_path=db_path)
        meta = runner(con, cfg, run_id) or {}
    except Exception:
        _record_phase_run(
            con,
            run_id=run_id,
            phase=phase,
            status="failed",
            started_at=started_at,
            finished_at=int(time.time() * 1000),
            config_hash=cfg.get("config_hash", ""),
            song_count=int(meta.get("song_count", 0)),
            warning_count=int(meta.get("warning_count", 0)),
            retained=bool(cfg.get("retained", False)),
        )
        _log.error("phase %r failed (run_id=%s)", phase, run_id)
        raise
    finished_at = int(time.time() * 1000)
    notes = list(pre_notes)
    if meta.get("notes"):
        notes.extend(str(n) for n in meta["notes"])
    summary = "; ".join(notes) if notes else ""
    warning_count = int(meta.get("warning_count", len(notes)))
    if meta.get("self_recorded"):
        # The canonical module owns its run_provenance row(s); only honor --retained.
        if cfg.get("retained"):
            _mark_run_retained(con, run_id, phase)
        _log.info("phase %s complete  run_id=%s  (module-recorded provenance)", phase, run_id)
        return
    _record_phase_run(
        con,
        run_id=run_id,
        phase=phase,
        status="completed",
        started_at=started_at,
        finished_at=finished_at,
        config_hash=cfg.get("config_hash", ""),
        song_count=int(meta.get("song_count", 0)),
        warning_count=warning_count,
        retained=bool(cfg.get("retained", False)),
        output_artifact_hashes=meta.get("output_artifact_hashes", ""),
        input_artifact_hashes=meta.get("input_artifact_hashes", ""),
        structural_change_summary=summary,
    )
    _log.info("phase %s complete  run_id=%s", phase, run_id)


class _MemoryWatcher:
    """Background daemon thread that logs process RSS memory every *interval* seconds."""

    def __init__(self, interval: float = 120.0) -> None:
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="mem-watcher", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=self._interval + 2)

    @staticmethod
    def _rss_mb() -> float | None:
        try:
            import psutil as _ps  # type: ignore[import]

            return float(_ps.Process().memory_info().rss) / 1_048_576
        except ImportError:
            pass
        try:
            # Linux fallback: /proc/self/status (no psutil required)
            _status = Path("/proc/self/status").read_text()
            for _line in _status.splitlines():
                if _line.startswith("VmRSS:"):
                    return int(_line.split()[1]) / 1024  # kB -> MB
        except OSError:
            pass
        return None

    def _run(self) -> None:
        _wlog = logging.getLogger(__name__ + ".mem")
        while not self._stop.wait(self._interval):
            _mb = self._rss_mb()
            if _mb is not None:
                _wlog.info("[mem]  RSS %.0f MB", _mb)


def _validate_verify_flags(verify: bool, strict: bool) -> None:
    """Reject ``--strict`` without ``--verify`` (strict refusal is meaningless otherwise).

    Chosen semantics (documented in --strict help text): ``--strict`` REQUIRES
    ``--verify``; it is rejected (not silently implied) so a user who believes they
    requested verification cannot be surprised.  ``--verify --strict`` escalates
    every recorded corruption / unresolved duplicate / missing-required-artifact /
    canary failure into a hard phase refusal.
    """
    if strict and not verify:
        _log.error(
            "--strict is only meaningful with --verify (strict refusal refuses on "
            "corruption/duplicates/missing artifacts found during verification); "
            "pass --verify --strict, or drop --strict."
        )
        raise SystemExit(2)


MAINTENANCE_COMMANDS: frozenset[str] = frozenset({"verify", "reindex", "cleanup", "reset"})


def _run_lock_path(root: Path, db_path: Path) -> Path:
    """Location of the single exclusive run lock for *root*/*db_path*.

    Local output roots lock at ``OUTPUT_ROOT/.run-lock``.  When the output root
    (or its device) is not local — e.g. a 9p share where an exclusive ``flock``
    may be unreliable — the lock is placed under the local system temp dir,
    keyed by a hash of the resolved research-DB path, so concurrent runs still
    collide on one well-known local file.
    """

    def _dev(p: Path):
        try:
            return os.stat(p).st_dev
        except OSError:
            return None

    root = Path(root).resolve()
    db = Path(db_path).resolve()
    local_tmp = Path(tempfile.gettempdir())
    root_dev = _dev(root)
    tmp_dev = _dev(local_tmp)
    if root_dev is not None and tmp_dev is not None and root_dev != tmp_dev:
        # Output root sits on a different (non-local) device — key the lock by
        # the resolved DB path so all run.py invocations for this DB collide.
        key = hashlib.sha256(str(db).encode("utf-8")).hexdigest()[:16]
        return local_tmp / f"nomarr-embed-research-{key}.lock"
    return root / ".run-lock"


class _RunLock:
    """Context manager: hold ONE exclusive advisory lock for the whole command.

    Acquired (non-blocking) before any CLI branch that opens the research DB or
    mutates artifacts — every phase and every maintenance command.  Contention
    raises ``SystemExit(2)`` with a diagnostic (never proceeds concurrently).
    Released on every exit path (success, error, exception) via ``__exit__``.
    """

    def __init__(self, root: Path, db_path: Path) -> None:
        self._path = _run_lock_path(root, db_path)
        self._fh = None

    @property
    def path(self) -> Path:
        return self._path

    def __enter__(self) -> _RunLock:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self._path, "w", encoding="utf-8")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            _log.error(
                "another embedding-research run holds the lock %s; refusing to proceed concurrently",
                self._path,
            )
            raise SystemExit(2) from None
        self._fh = fh
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._fh is not None:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None
        return False


def _resolve_command(cmd: str) -> str:
    """Validate a CLI command string against the explicit 12-command set.

    Returns the command unchanged when it is one of the eight phase names or one
    of the four maintenance keywords (``verify`` / ``reindex`` / ``cleanup`` /
    ``reset``).  Any unrecognized command — including the retired legacy names
    (``stratify``/``segment``/``classify``/``head``), which are now ordinary
    unknown commands with no named alias or compatibility rejection path —
    raises ``SystemExit(2)`` naming the valid commands.
    """
    if cmd not in CLI_PHASES and cmd not in MAINTENANCE_COMMANDS:
        _log.error(
            "unknown command %r. Valid phases: %s. Maintenance: %s.",
            cmd,
            ", ".join(CLI_PHASES),
            ", ".join(sorted(MAINTENANCE_COMMANDS)),
        )
        raise SystemExit(2)
    return cmd


def main() -> None:
    """Configure logging, parse CLI args, and execute one command under the run lock."""
    _fmt = logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s", datefmt="%H:%M:%S")
    _sh = logging.StreamHandler()
    _sh.setFormatter(_fmt)
    _log_dir = OUTPUT_ROOT
    _log_dir.mkdir(parents=True, exist_ok=True)
    _log_path = _log_dir / "post_pipeline_run.log"
    # Process-lifetime handle: the StreamHandler below owns `_fh` and flushes on each
    # record, so the file must stay open (and line-buffered) for main()'s whole run.
    _log_file_handle = open(_log_path, "w", encoding="utf-8", buffering=1)  # noqa: SIM115
    _fh = logging.StreamHandler(_log_file_handle)
    _fh.setFormatter(_fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(_sh)
    root.addHandler(_fh)
    # Route mem-watcher logs to file only (they split tqdm progress bars)
    _mem_logger = logging.getLogger(__name__ + ".mem")
    _mem_logger.propagate = False
    _mem_logger.addHandler(_fh)
    # Suppress verbose DEBUG spam from third-party libraries
    for _noisy in ("PIL", "onnxruntime", "numba", "h5py", "numexpr", "nomarr.components.ml.onnx.ml_session_comp"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)

    ap = argparse.ArgumentParser(
        description="Embedding research CLI — 8 phases + verify/reindex/cleanup/reset maintenance.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("command", nargs="?", default=None, help="phase or maintenance command (see below)")
    ap.add_argument("--force", action="store_true", help="Recompute/override existing rows for this phase")
    ap.add_argument(
        "--regenerate-masks",
        action="store_true",
        help="embed submode: CPU-only re-derive of audio masks (no ONNX/session; refuses if audio changed)",
    )
    ap.add_argument("--device", default=None, help="ONNX device (cpu|cuda) for audio phases")
    ap.add_argument("--retained", action="store_true", help="Mark this run retained (protected from GC)")
    ap.add_argument("--verify", action="store_true", help="Verify artifacts/catalog while running (relevant phases)")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="With --verify (phase runs): refuse the phase on corruption/duplicates/missing "
        "artifacts.  Standalone verify command: force fresh full-digest validation.",
    )
    ap.add_argument("--scope", default=None, help="cleanup: staging|stray|views ; reset: analysis")
    ap.add_argument("--dry-run", action="store_true", dest="dry_run", default=None, help="report without deleting")
    args = ap.parse_args()

    try:
        cmd = args.command
        if cmd is None:
            ap.print_help()
            raise SystemExit(2)
        cmd = _resolve_command(cmd)

        # Startup duckdb version gate (1.5 <= v < 2.0) before ANY DB work.
        from scripts.embedding_research.db._schema import require_supported_duckdb as _require_supported_duckdb

        _require_supported_duckdb()

        # One exclusive run lock guards EVERY branch that opens the DB or mutates
        # artifacts — all eight phases and the four maintenance commands.
        with _RunLock(OUTPUT_ROOT, DB_PATH):
            if cmd == "verify":
                _cmd_verify(args)
                return
            if cmd == "reindex":
                _cmd_reindex(args)
                return
            if cmd == "cleanup":
                _cmd_cleanup(args)
                return
            if cmd == "reset":
                _cmd_reset(args)
                return

            # ── pipeline phase ──────────────────────────────────────────────
            _validate_verify_flags(verify=bool(args.verify), strict=bool(args.strict))
            cfg = _build_run_config(args)
            _log.info(
                "Config: phase=%s force=%s device=%s backbones=%s heads=%s retained=%s",
                cmd,
                cfg.get("force"),
                cfg.get("device"),
                cfg.get("backbones"),
                cfg.get("heads"),
                cfg.get("retained"),
            )

            _watcher = _MemoryWatcher(interval=120.0)
            _watcher.start()
            try:
                with duckdb.connect(str(DB_PATH)) as con:
                    from scripts.embedding_research import db as _db_mod

                    _db_mod.ensure_schema(con)
                    _run_single_phase(con, cmd, cfg, db_path=str(DB_PATH))
            finally:
                _watcher.stop()
                _log.info("Memory watcher stopped")
    except SystemExit:
        raise
    except Exception as exc:
        _log.exception("command %r failed: %s", args.command, exc)
        raise SystemExit(1) from exc
    finally:
        _log_file_handle.close()


def _build_run_config(args) -> dict:
    """Build the per-phase config dict from the strict research config + CLI overrides.

    Reads the typed :class:`~helpers.toml.CurrentResearchConfig` (Plan A P1-S3)
    which exposes only the executable current ``[pipeline]`` / ``[analysis]``
    sections.  The legacy ``[binning]``/``[archival_ctp]``/``[optimization]`` grids
    were removed, so the legacy catalog sweep literals below are frozen constants
    (``helpers.binning``), not config reads.
    """
    _cfg = _load_research_config()
    _pipe = _cfg.pipeline
    _analysis = _cfg.analysis
    device = args.device or _pipe.device
    cfg: dict = {
        "limit": _pipe.limit or None,
        "force": bool(args.force or _pipe.force),
        "regenerate_masks": bool(getattr(args, "regenerate_masks", False)),
        "device": "gpu" if str(device).lower() in ("cuda", "gpu") else "cpu",
        "backbones": list(_pipe.backbones) if _pipe.backbones else None,  # None = all
        "heads": list(_pipe.heads) if _pipe.heads else None,  # None = all
        "k": _analysis.k,
        "workers": _analysis.workers,
        "blas_threads": _analysis.blas_threads or None,
        # Experiment One is the frozen temporal-global/L2 threshold sweep.  The
        # retained temporal-perdim/Chebyshev mode is secondary and must be selected
        # explicitly by a non-default caller; equal thresholds remain distinct by mode.
        "catalog_bin_modes": ["temporal_global"],
        "catalog_thresholds": [float(t) for t in STD_THRESHOLDS],
        # derived phases read/write frozen artifacts under the configured output root.
        "output_root": OUTPUT_ROOT,
        "report_dir": OUTPUT_ROOT / "report",
        "retained": bool(args.retained),
        "verify": bool(args.verify),
        "strict": bool(args.strict),
        "run_id": None,
        "config_hash": hashlib.sha256(_load_raw_cfg()).hexdigest()[:16],
    }
    return cfg


def _cmd_verify(args) -> None:
    """``python run.py verify [--strict]`` — current-format artifact audit.

    No DB mutation beyond verify-owned catalog WAL recovery/checkpoint.  Exits 1
    when the audit finds refusals/corruption (0 on a clean verified tree).
    """
    from scripts.embedding_research.verify import verify_current_artifacts

    report = verify_current_artifacts(OUTPUT_ROOT, strict=bool(args.strict))
    _log.info(
        "verify strict=%s verified=%d recovered=%d refusals=%d issues=%d",
        bool(args.strict),
        report.verified,
        len(report.recovered),
        len(report.refusals),
        len(report.issues),
    )
    for _refusal in report.refusals:
        _log.error("refusal: %s", _refusal)
    for _issue in report.issues:
        _log.warning("issue: %s", _issue)
    if report.refusals or report.issues:
        raise SystemExit(1)


def _cmd_reindex(_args) -> None:
    """``python run.py reindex`` — rebuild registry rows from current manifests.

    Thin public wrapper over ``streams.reindex.reindex`` (which invokes
    ``reconcile_current_manifests``).  CPU-only: never opens audio/models/sessions.
    """
    from scripts.embedding_research import db as _db_mod
    from scripts.embedding_research.streams.reindex import reindex as _reindex_run

    with duckdb.connect(str(DB_PATH)) as con:
        _db_mod.ensure_schema(con)
        report = _reindex_run(OUTPUT_ROOT, con)
    _log.info(
        "reindex scanned=%d rows_rebuilt=%d ready=%d orphan=%d issues=%d",
        report.scanned,
        report.rows_rebuilt,
        report.ready,
        report.orphan_payloads,
        len(report.issues),
    )
    for _issue in report.issues:
        _log.warning("reindex issue: %s", _issue)
    if report.issues:
        raise SystemExit(1)


def _open_cleanup_con():
    """Open a READ-ONLY ``research.duckdb`` connection for retention-aware view cleanup.

    Returns ``None`` when the DB file is absent or cannot be opened read-only — the caller
    then treats that as ``no retained refs`` (every existing view is GC-eligible).  The
    connection is read-only, so ``cleanup --scope views`` can never take the run lock or
    write to ``research.duckdb``.
    """
    try:
        return duckdb.connect(str(DB_PATH), read_only=True)
    except Exception:
        return None


def _cmd_cleanup(args) -> None:
    """``python run.py cleanup --scope {staging|stray|views} [--dry-run]``.

    Current-format-only report-then-remove.  staging/stray default to a report
    (dry-run) so the destructive pass requires an explicit ``--dry-run=false``
    at the module level; ``views`` removes by default unless ``--dry-run``.
    """
    from scripts.embedding_research import cleanup as _cleanup

    scope = args.scope
    if scope not in ("staging", "stray", "views"):
        _log.error("cleanup requires --scope {staging|stray|views}; got %r", scope)
        raise SystemExit(2)
    dry = args.dry_run if args.dry_run is not None else (scope in ("staging", "stray"))
    # ``views`` GC is retention-aware: it may delete only view keyset dirs NOT referenced by
    # a retained run.  Open a READ-ONLY research.duckdb connection to read the protected
    # ``run_provenance`` refs (a live DB is never required — absence == no retained refs ->
    # every existing view is GC-eligible).  Never take the run lock; never write here.
    con = None
    if scope == "views":
        con = _open_cleanup_con()
    report = _cleanup.cleanup_current(OUTPUT_ROOT, con, scope=scope, dry_run=dry)
    if con is not None:
        con.close()
    _log.info(
        "cleanup scope=%s dry_run=%s removed=%d skipped=%d refused=%d",
        scope,
        dry,
        len(report.removed),
        len(report.skipped),
        len(report.refused),
    )
    for _candidate in report.removed + report.skipped:
        _log.info("  %s", _candidate)
    for _refusal in report.refused:
        _log.warning("refused: %s", _refusal)
    if report.refused:
        raise SystemExit(1)


def _cmd_reset(args) -> None:
    """``python run.py reset --scope analysis`` — drop the disposable analysis DB + views.

    Removes ONLY the disposable ``research.duckdb`` (and WAL) plus the whole
    ``views/`` tree (retained-run protection never survives reset — view_refs live in the
    deleted research DB); Tier 1/2 payloads (corpus/, streams/, heads/,
    audio_masks/, observation_commits/, catalogs/) are preserved byte-for-byte.
    Any other scope is refused (nonzero).
    """
    from scripts.embedding_research.cleanup import reset_analysis

    scope = args.scope or "analysis"
    if scope != "analysis":
        _log.error("reset requires --scope analysis; got %r", scope)
        raise SystemExit(2)
    dry = bool(args.dry_run)
    report = reset_analysis(OUTPUT_ROOT, DB_PATH, dry_run=dry)
    _log.info(
        "reset scope=analysis dry_run=%s removed=%d",
        dry,
        len(report.removed),
    )
    for _candidate in report.removed:
        _log.info("  %s", _candidate)


if __name__ == "__main__":
    main()
