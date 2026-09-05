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
The retired legacy phase names (``stratify``, ``segment``, ``classify``, ``head``)
fail loudly (exit 2) — they are never silently aliased.

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
from scripts.embedding_research.helpers.binning import BIN_MODES
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
# EXPLICIT SEPARATE maintenance operations (wired to cleanup.py scopes / the
# legacy reset helpers, not to the phase sequence).
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
# view/reset GC protects it.  embed / infer-heads / analyze record their own
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

# Legacy phase names that previously mapped to opaque orchestration.  They are
# NOT valid new-CLI phase names: selecting one is a clear error (never a silent
# alias), per CONTRACTS.md CLI boundaries.
LEGACY_PHASE_ALIASES: frozenset[str] = frozenset({"stratify", "segment", "classify", "head"})

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
        "catalog_identity",
        "catalog_report",
        "config",
        "report",
        "streams",
        # db/* CPU persistence modules
        "db.analyze_scope",
        "db.songs",
        "db.head_phase",
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
    bin_modes = cfg.get("catalog_bin_modes") or ["temporal_global"]
    thresholds = [float(t) for t in (cfg.get("catalog_thresholds") or [0.7])]
    return [
        SegConfigInput(
            backbone=backbone,
            bin_mode=bin_mode,
            threshold_configured=threshold,
            threshold_effective=threshold,
            semantics="direct_l2",
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
    """The songs actually cataloged (compact ``seg_meta`` rows) for *backbone*.

    *con* is a COMPACT snapshot connection (``handle.con``); the compact snapshot
    stores only canonical ``seg_config`` rows (no alias graph), so every config is
    canonical and no ``alias_of_config_id`` filter is needed or possible.  The
    corpus is the distinct songs that produced segments (``seg_meta``) under a
    config of *backbone* — derived `analyze` reads its corpus from these frozen
    rows (the real cataloged corpus) rather than re-selecting.
    """
    rows = con.execute(
        """
        SELECT DISTINCT sm.song_id
        FROM seg_meta sm
        JOIN seg_config c ON c.config_id = sm.config_id
        WHERE c.backbone = ?
        ORDER BY 1
        """,
        (backbone,),
    ).fetchall()
    return [r[0] for r in rows]


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
        heads=cfg.get("heads"),
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
    from scripts.embedding_research.streams import StreamStore, make_current_stream_resolver

    out_root = cfg.get("output_root") or OUTPUT_ROOT
    configs = _catalog_seg_configs(cfg)
    song_ids = _catalog_corpus_song_ids(con)
    # Compact producer contract: stream_store is a current-stream loader
    # (``.load(song, backbone) -> float32[P,D] | None``); mask_store is the new duck
    # whole-song uint8 loader (``None`` == no silence at this research layer).
    stream_store = make_current_stream_resolver(StreamStore(con, output_root=str(out_root)))
    build_segmentation_catalog(
        stream_store,
        None,
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
    """
    from scripts.embedding_research.common.catalog_analysis import (
        CatalogAnalysisConfig,
        analyze_catalog_corpus,
    )
    from scripts.embedding_research.db.analyze_scope import write_catalog_analyze_rows
    from scripts.embedding_research.db.songs import load_all_songs
    from scripts.embedding_research.streams import StreamStore

    out_root = Path(cfg.get("output_root") or OUTPUT_ROOT)
    handle = _open_derived_catalog(out_root, "analyze")
    if handle is None:
        _warn_no_catalog("analyze")
        return {"song_count": 0, "self_recorded": True}
    try:
        store = StreamStore(con, output_root=str(out_root))
        artists = {r["song_id"]: (r["artist"] or "unknown") for r in load_all_songs(con)}
        total = 0
        for backbone in cfg.get("backbones") or ["effnet"]:
            song_ids = _analysis_corpus_song_ids(handle.con, backbone)
            if not song_ids:
                _log.warning("analyze: no cataloged corpus for backbone %r — run `catalog` first", backbone)
                continue
            analysis_cfg = CatalogAnalysisConfig(
                run_id=run_id,
                backbone=backbone,
                song_ids=tuple(song_ids),
                artists=artists,
                k=int(cfg.get("k", 10)),
            )
            result = analyze_catalog_corpus(store, handle.con, analysis_cfg, research_con=con)
            write_catalog_analyze_rows(con, run_id=run_id, result=result)
            total += len(song_ids)
    finally:
        handle.close()
    # analyze records its own run_provenance row via materialize/record_*_scope.
    return {"song_count": total, "self_recorded": True}


def _run_head_analysis(con, cfg: dict, run_id: str) -> dict:
    """head-analysis: CPU head pooling over exact compact M_g memberships (CPU).

    Opens the latest COMPACT snapshot locally for catalog reads (the runner reconstructs
    each segment's exact searchable ``M_g`` from compact ``seg_meta`` rows) and retains the
    research connection ``con`` for the ``HeadStreamStore`` and coverage/skip provenance
    writes.  When no compact snapshot exists it warns and skips (never routes the research
    connection into the compact-only reader).  P1-S11 aligns preflight detection with this
    same resolver.
    """
    from scripts.embedding_research.common.head_analysis import run_shared_catalog_head_analysis
    from scripts.embedding_research.db.head_phase import (
        build_head_phase_provenance_rows,
        write_head_phase_provenance,
    )
    from scripts.embedding_research.streams import HeadStreamStore

    out_root = Path(cfg.get("output_root") or OUTPUT_ROOT)
    handle = _open_derived_catalog(out_root, "head-analysis")
    if handle is None:
        _warn_no_catalog("head-analysis")
        return {"song_count": 0}
    head_store = HeadStreamStore(con, output_root=str(out_root))
    try:
        manifest = run_shared_catalog_head_analysis(
            handle,
            head_store,
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


def _run_report(con, cfg: dict, _run_id: str) -> dict:
    """report: render results + provenance, never infers (CPU)."""
    from scripts.embedding_research.config import REPORT_DIR as _REPORT_DIR
    from scripts.embedding_research.report import run as _report_run

    out_dir = Path(cfg.get("report_dir") or _REPORT_DIR)
    _report_run(con, out_dir)
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
    """True when at least one non-legacy (run-scoped) analyze_metrics row exists."""
    n = con.execute("SELECT count(*) FROM analyze_metrics WHERE run_id <> 'legacy'").fetchone()[0]
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
    ``reset``).  Retired legacy aliases (``stratify``/``segment``/``classify``/
    ``head``) and unknown commands raise ``SystemExit(2)`` naming the valid
    commands — they are never silently aliased.
    """
    if cmd in LEGACY_PHASE_ALIASES:
        _log.error(
            "%r is a retired/legacy phase name and is not a valid new-CLI command. Valid phases: %s (maintenance: %s)",
            cmd,
            ", ".join(CLI_PHASES),
            ", ".join(sorted(MAINTENANCE_COMMANDS)),
        )
        raise SystemExit(2)
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
        # catalog input generation: the removed [binning] grid is replaced by these
        # frozen literals from helpers.binning (the strict schema has no binning sweep).
        "catalog_bin_modes": list(BIN_MODES),
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
    from scripts.embedding_research.streams import reindex as _reindex

    with duckdb.connect(str(DB_PATH)) as con:
        _db_mod.ensure_schema(con)
        report = _reindex.reindex(OUTPUT_ROOT, con)
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
    report = _cleanup.cleanup_current(OUTPUT_ROOT, None, scope=scope, dry_run=dry)
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

    Removes ONLY the disposable ``research.duckdb`` (and WAL) plus the
    ``disposable_views/`` tree; Tier 1/2 payloads (corpus/, streams/, heads/,
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
