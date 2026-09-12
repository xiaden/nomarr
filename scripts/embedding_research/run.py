"""Geometry research pipeline CLI — the exact seven-phase topology.

Phases, in order: ``ingest``, ``embed``, ``infer-heads``, ``geometry``, ``analyze``,
``head-analysis``, ``report``.  The first three are audio phases (the only phases permitted
to discover audio, load models, create ONNX sessions, or touch CUDA).  The four derived
phases (``geometry``, ``analyze``, ``head-analysis``, ``report``) are CPU-only and consume
only committed stream/geometry/head artifacts through the geometry, observation,
persistence, and report owners.

Maintenance commands are separate verbs: ``verify``, ``reindex``, ``cleanup``, ``reset``.
Any other command — including retired names — is an ordinary unknown command with no
special rejection path.
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

_pkg_root = Path(__file__).resolve().parent.parent.parent
if str(_pkg_root) not in sys.path:
    sys.path.insert(0, str(_pkg_root))

from scripts.embedding_research.common.threshold_analysis import (
    PRIMARY_EXPERIMENT,
    PRIMARY_EXPERIMENT_VERSION,
    PrimaryThresholdRequest,
    dense_primary_threshold_request,
    primary_experiment_manifest,
)
from scripts.embedding_research.config import DB_PATH, OUTPUT_ROOT
from scripts.embedding_research.helpers.toml import load_research_config as _load_research_config
from scripts.embedding_research.helpers.toml import load_research_config_bytes as _load_raw_cfg

_log = logging.getLogger(__name__)

CLI_PHASES: tuple[str, ...] = ("ingest", "embed", "infer-heads", "geometry", "analyze", "head-analysis", "report")
AUDIO_PHASES: frozenset[str] = frozenset({"ingest", "embed", "infer-heads"})
DERIVED_PHASES: frozenset[str] = frozenset(CLI_PHASES) - AUDIO_PHASES
DERIVED_ALLOWED_IMPORT_ROOTS: frozenset[str] = frozenset({"common", "config", "report", "streams", "db"})
DERIVED_FORBIDDEN_TOKENS: frozenset[str] = frozenset({"discover_audio", "onnxruntime", "torch", "cuda"})

# ── provenance / run helpers ───────────────────────────────────────────────────


def _software_versions() -> str:
    """Software-version line recorded in run_provenance."""
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


def _run_geometry(con, cfg: dict, run_id: str) -> dict:
    """Derive and persist geometry from committed stream observations (CPU-only).

    Narrow adapter over the geometry-owned corpus writer: it uses the configured
    backbone set, loads exactly one committed observation per item through the
    StreamStore seam, and requires the already-held exclusive run lock.
    """
    from scripts.embedding_research.common.geometry_analysis import write_geometries_for_current_songs
    from scripts.embedding_research.db.geometry_profile import GeometryProfile
    from scripts.embedding_research.streams.store import StreamStore

    lock = cfg.get("run_lock")
    if lock is None:
        raise RuntimeError("geometry phase requires the exclusive run lock")
    store = StreamStore(con, output_root=cfg.get("output_root") or OUTPUT_ROOT)
    records = write_geometries_for_current_songs(
        con,
        stream_store=store,
        profile=GeometryProfile.current(),
        run_id=run_id,
        lock=lock,
        song_ids=cfg.get("song_ids"),
        backbones=cfg.get("backbones"),
    )
    return {"song_count": len(records), "notes": [f"geometry rows written: {len(records)}"]}


def _run_analyze(con, cfg: dict, run_id: str) -> dict:
    """Analyze committed geometry evidence through the sole CPU corpus owner."""
    from scripts.embedding_research.common.geometry_analysis import (
        analyze_geometry_corpus,
        build_geometry_corpus_request,
        write_geometry_corpus_analysis,
    )
    from scripts.embedding_research.db.geometry_profile import GeometryProfile
    from scripts.embedding_research.streams.store import StreamStore

    profile = GeometryProfile.current()
    store = StreamStore(con, output_root=cfg.get("output_root") or OUTPUT_ROOT)
    request = build_geometry_corpus_request(
        con,
        stream_store=store,
        profile=profile,
        threshold_request=cfg["threshold_request"],
        experiment=cfg["experiment"],
        evaluation_id=f"evaluation:{run_id}",
        run_id=run_id,
        execution_id=f"execution:{run_id}",
        scoring_semantics_version=1,
        song_ids=cfg.get("song_ids"),
        backbones=cfg.get("backbones"),
    )
    result = analyze_geometry_corpus(request, con=con, stream_store=store, profile=profile)
    write_geometry_corpus_analysis(con, run_id=run_id, result=result, stream_store=store, profile=profile)
    return {
        "song_count": len(request.items),
        "identity_hash": hashlib.sha256(request.execution_id.encode()).hexdigest(),
    }


def _run_head_analysis(con, cfg: dict, run_id: str) -> dict:
    """Analyze aligned head evidence over completed geometry projections."""
    from scripts.embedding_research.common.geometry_analysis import build_geometry_corpus_request
    from scripts.embedding_research.common.head_analysis import run_shared_geometry_head_analysis
    from scripts.embedding_research.db.geometry_profile import GeometryProfile
    from scripts.embedding_research.db.identity_persistence import write_head_evidence
    from scripts.embedding_research.streams.store import HeadStreamStore, StreamStore

    profile = GeometryProfile.current()
    streams = StreamStore(con, output_root=cfg.get("output_root") or OUTPUT_ROOT)
    heads = HeadStreamStore(con, output_root=cfg.get("output_root") or OUTPUT_ROOT)
    request = build_geometry_corpus_request(
        con,
        stream_store=streams,
        profile=profile,
        threshold_request=cfg["threshold_request"],
        experiment=cfg["experiment"],
        evaluation_id=f"evaluation:{run_id}",
        run_id=run_id,
        execution_id=f"execution:{run_id}",
        scoring_semantics_version=1,
        song_ids=cfg.get("song_ids"),
        backbones=cfg.get("backbones"),
    )
    manifests = []
    if not isinstance(request.threshold_request, PrimaryThresholdRequest):
        raise RuntimeError("secondary geometry head analysis is unavailable")
    for item in request.items:
        observation = streams.load_committed_observation(item.song_id, item.backbone)
        from scripts.embedding_research.db.geometry import read_geometry, verify_geometry_binding

        record = read_geometry(item.geometry_identity, con)
        verify_geometry_binding(record, observation, profile)
        from scripts.embedding_research.common.threshold_analysis import analyze_all_thresholds

        analysis = analyze_all_thresholds(
            record, observation.mask, request.threshold_request, experiment=request.experiment
        )
        manifests.append(
            run_shared_geometry_head_analysis(
                record,
                heads,
                analysis=analysis,
                run_id=run_id,
                current_observation=observation,
                profile=profile,
                stream_store=streams,
            )
        )
    outputs = [output for manifest in manifests for output in manifest.outputs]
    if outputs:
        write_head_evidence(con, run_id=run_id, outputs=outputs)
    return {"song_count": len(manifests), "head_output_count": len(outputs)}


def _completed_analyze_run_ids(con) -> list[str]:
    """Completed ``analyze`` run ids present in ``run_provenance``, oldest first.

    Completion is decided PER ``run_id`` by grouping every ``phase == 'analyze'`` provenance row
    for that run (append-only ``run_provenance`` has no PK/UNIQUE on ``run_id``, so a run may hold
    several same-phase rows — the analyze producer's own scope rows and wrapper recordings).  The
    base predicate for a completed run is: it has at least one ``phase == 'analyze'`` row with
    status ``complete``/``completed``, and NONE of its analyze rows has status ``failed``.  A single
    failed analyze row vetoes the ENTIRE run, so a contradictory run carrying both completed analyze
    rows and a later failed analyze row never surfaces as a completed scope and can never render
    partial geometry analysis as a completed report.  For an invocation-backed run (see below) this base
    predicate is necessary but NOT sufficient — it must also be a clean all-obligation terminal
    invocation.

    Obligation-gated completion: an invocation-backed run (its analyze rows carry an
    ``analyze_invocation_v1`` obligations record written by the Plan-B producer) is completed only when
    that record is paired with a ``completed`` ``analyze_terminal_v1`` terminal record — scope/evidence
    rows alone NEVER terminalize an invocation.  A pre-obligation run (no invocation record; e.g.
    historical/synthetic scope-only rows) falls back to the historical scope-evidence predicate (>=1
    ``complete``/``completed`` analyze row, no ``failed``), keeping such runs reportable exactly as
    before.  This is the deterministic completion signal the report phase resolves — there is no status
    column on the geometry analysis records themselves, so completion lives in ``run_provenance``.
    The returned ids are deduplicated (one entry per completed run) and deterministically ordered:
    ascending representative ``finished_at``/``started_at`` (integer ms; the existing chain
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
    into a whole-set read — either run-scoped ``geometry_analysis_records`` rows with no completed
    analyze scope, or an explicitly requested scope that is not a completed analyze run (including a
    contradictory complete-plus-failed run).  An empty database (no run-scoped analysis rows)
    renders an empty report, preserving the preflight-warned path.
    """
    from scripts.embedding_research.config import REPORT_DIR as _REPORT_DIR
    from scripts.embedding_research.db.geometry_profile import GeometryProfile
    from scripts.embedding_research.report import run as _report_run
    from scripts.embedding_research.streams.store import StreamStore

    out_dir = Path(cfg.get("report_dir") or _REPORT_DIR)
    run_id = _resolve_report_run_id(con, cfg)
    if run_id is None and (cfg.get("report_run_id") is not None or _has_geometry_analysis(con)):
        if cfg.get("report_run_id") is not None:
            msg = (
                "phase 'report': requested report scope run_id="
                f"{cfg['report_run_id']!r} is not a completed analyze scope; "
                "run `analyze` to completion for that run"
            )
        else:
            msg = (
                "phase 'report': run-scoped geometry analysis rows are present but no completed "
                "analyze scope is recorded; run `analyze` to completion (refusing to blend runs)"
            )
        raise _MissingArtifactError(msg)
    _report_run(
        con,
        out_dir,
        run_id=run_id,
        stream_store=StreamStore(con, output_root=cfg.get("output_root") or OUTPUT_ROOT),
        profile=GeometryProfile.current(),
    )
    return {"song_count": 0, "output_artifact_hashes": "report.json,report.html"}


CLI_PHASE_RUNNERS: dict[str, Callable[..., dict]] = {
    "ingest": _run_ingest,
    "embed": _run_embed,
    "infer-heads": _run_infer_heads,
    "geometry": _run_geometry,
    "analyze": _run_analyze,
    "head-analysis": _run_head_analysis,
    "report": _run_report,
}

_DERIVED_CONSUMER_PHASES = frozenset({"geometry", "analyze", "head-analysis", "report"})


def _has_geometry_analysis(con) -> bool:
    return bool(con.execute("SELECT count(*) FROM geometry_analysis_records").fetchone()[0])


def _preflight_derived_phase(con, phase: str, cfg: dict, *, db_path=None) -> list[str]:
    if phase not in DERIVED_PHASES:
        return []
    from scripts.embedding_research.db.canary import detect_post_crash, run_rollback_canary

    post_crash = detect_post_crash(con, db_path=db_path)
    if not (cfg.get("verify") or cfg.get("strict") or post_crash):
        return []

    notes = []
    if post_crash:
        notes.append("post-crash state detected")
    result = run_rollback_canary(con)
    notes.append(f"canary ok: {len(result.ok)} probed, {len(result.empty)} empty")
    if phase in _DERIVED_CONSUMER_PHASES and not _has_geometry_analysis(con):
        notes.append(f"{phase}: no geometry analysis metrics present")
    return notes


class _MissingArtifactError(RuntimeError):
    """Raised when a required geometry artifact is absent."""


class _DuplicateIdentityError(RuntimeError):
    """Raised when an exact geometry identity is duplicated."""


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
            # Linux alternative: /proc/self/status (no psutil required)
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
    """Validate a CLI command string against the explicit eleven-command set.

    Returns the command unchanged when it is one of the seven phase names or one of
    the four maintenance keywords (``verify`` / ``reindex`` / ``cleanup`` / ``reset``).
    Any unrecognized command — including retired historical phase names such as
    ``stratify``/``segment``/``classify``/``head`` — follows the ordinary
    unknown-command path with no named rejection or compatibility branch, and raises
    ``SystemExit(2)`` naming the valid commands.
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
        description="Embedding research CLI — 7 phases + verify/reindex/cleanup/reset maintenance.",
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
    ap.add_argument("--verify", action="store_true", help="Verify current artifacts while running (relevant phases)")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="With --verify (phase runs): refuse the phase on corruption/duplicates/missing "
        "artifacts.  Standalone verify command: force fresh full-digest validation.",
    )
    ap.add_argument("--scope", default=None, help="cleanup: staging|stray ; reset: analysis")
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
        # artifacts — all seven phases and the four maintenance commands.
        with _RunLock(OUTPUT_ROOT, DB_PATH) as _run_lock:
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
            # Hand the already-held exclusive run lock to phases whose persistence
            # contract requires an existing lock token (geometry writes).
            cfg["run_lock"] = _run_lock
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
    sections.  The earlier ``[binning]``/``[archival_ctp]``/``[optimization]`` grids
    were removed, so the sweep literals below are frozen constants
    (the canonical Gram/coordinate engines), not config reads.
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
        # Experiment One is the sole default: exactly the indexed 0.30..2.00
        # float32 grid.  Do not source these values from a persisted config default.
        "experiment": PRIMARY_EXPERIMENT,
        "experiment_version": PRIMARY_EXPERIMENT_VERSION,
        "threshold_request": dense_primary_threshold_request(),
        "threshold_manifest": primary_experiment_manifest(),
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

    No DB mutation beyond verify-owned WAL recovery/checkpoint.  Exits 1
    when the audit finds refusals/corruption (0 on a clean verified tree).
    """
    from scripts.embedding_research.verify import verify_current_artifacts

    con = None
    if DB_PATH.exists():
        from scripts.embedding_research.db.geometry_profile import GeometryProfile

        con = duckdb.connect(str(DB_PATH))
        try:
            report = verify_current_artifacts(
                OUTPUT_ROOT, strict=bool(args.strict), con=con, profile=GeometryProfile.current()
            )
        finally:
            con.close()
    else:
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


def _cmd_cleanup(args) -> None:
    """``python run.py cleanup --scope {staging|stray} [--dry-run]``.

    Current-format-only report-then-remove.  staging/stray default to a report
    (dry-run) so the destructive pass requires an explicit destructive opt-in.
    """
    from scripts.embedding_research import cleanup as _cleanup

    scope = args.scope
    if scope not in ("staging", "stray"):
        _log.error("cleanup requires --scope {staging|stray}; got %r", scope)
        raise SystemExit(2)
    dry = args.dry_run if args.dry_run is not None else True
    con = None
    if DB_PATH.exists():
        con = duckdb.connect(str(DB_PATH))
        try:
            report = _cleanup.cleanup_current(OUTPUT_ROOT, con, scope=scope, dry_run=dry)
        finally:
            con.close()
    else:
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
    """Reset disposable analysis metadata while preserving committed evidence.

    Geometry reset is deliberately unavailable; analysis reset never deletes streams,
    masks, heads, observation commits, or geometry rows.
    """
    from scripts.embedding_research.cleanup import GeometryResetUnavailableError, reset_analysis, reset_geometry

    scope = args.scope or "analysis"
    if scope == "geometry":
        try:
            reset_geometry()
        except GeometryResetUnavailableError as exc:
            _log.error(str(exc))
            raise SystemExit(str(exc)) from exc
    if scope != "analysis":
        _log.error("reset requires --scope analysis; got %r", scope)
        raise SystemExit(2)
    dry = bool(args.dry_run)
    if not dry and DB_PATH.exists():
        from scripts.embedding_research import db as _db_mod
        from scripts.embedding_research.db.geometry_profile import GeometryProfile
        from scripts.embedding_research.verify import verify_current_artifacts

        with duckdb.connect(str(DB_PATH)) as audit_con:
            _db_mod.ensure_schema(audit_con)
            audit = verify_current_artifacts(OUTPUT_ROOT, con=audit_con, profile=GeometryProfile.current())
        if audit.refusals:
            _log.error("reset refused: stale/invalid geometry evidence present")
            for _refusal in audit.refusals:
                _log.error("  %s", _refusal)
            raise SystemExit(1)
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
