"""Explicit cleanup / reset scopes (Plan E P3-S2).

This module exposes the DD's cleanup/reset scopes as an importable, CLI-ready surface
(the ``cleanup`` subcommand wiring that binds flags is Phase 4 P4-S1 — nothing here parses
CLI args).  Each scope is an explicit, confirmable operation; there is **no default/global
reset of Tier 1/2 baseline or corpus results** and no unclassified deletion:

* ``staging``        — remove aged ``.staging/*.tmp`` leftover staging files.
* ``views``          — remove disposable search views NOT referenced by a retained run.
* ``dead``           — remove only statically-classified Dead artifacts (from the P3-S1 audit).
* ``archival``       — remove archival artifacts ONLY with loud confirmation.
* ``analysis-run``   — belongs to P3-S3's run-scoped ``reset_analysis_run`` (see below); this
                       module never performs a global ``DELETE FROM analyze_metrics``.

Rules enforced here:
* **Retained-run protection** — any operation that would touch rows/artifacts referenced by a
  ``run_provenance.retained=true`` row is refused unless the explicit scope names them.
* **No unclassified deletion** — a table/cache/artifact not present in the static inventory
  (``DEAD_DB_TABLES`` / ``ARCHIVAL_CACHE_DIRNAMES``) raises :class:`UnclassifiedArtifactError`
  instead of being deleted.
* **Sidecar preservation** — on any reset, immutable sidecars (stream/head payloads and their
  ``.staging`` neighbours) and disposable search-view *payloads* are preserved unless the
  explicit scope targets them.

Scope functions are pure of the DB and take a ``duckdb`` connection only where retained-run
protection or table drops require it.  Each returns a :class:`CleanupReport` and honours
``dry_run`` (report intent without mutating anything).  Timestamps elsewhere remain integer
milliseconds.
"""

from __future__ import annotations

import logging
import shutil
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

LOG = logging.getLogger(__name__)

#: Sibling directory name used for staged ``*.tmp`` writes (streams/publication.py).
STAGING_DIRNAME = ".staging"

#: Default age (seconds) past which a leftover ``.staging/*.tmp`` is considered a stale
#: interrupted-write remnant eligible for removal.  Callers may pass ``min_age_seconds=0``
#: to remove every leftover staging file (used by tests).
DEFAULT_STAGING_MIN_AGE = 3600

# ── Static inventory (P3-S1 audit; see README.md "Maintenance" section) ──────────

#: Dead DuckDB tables — DDL'd with zero live writers (P3-S1 audit).  These survive only as
#: DDL/layout and are the ``cleanup --scope dead`` targets.  Listed table names are the ONLY
#: tables the dead scope may drop; anything else is unclassified and refused.
DEAD_DB_TABLES: frozenset[str] = frozenset(
    {
        "pooled_vecs",
        "head_results",
        "head_agreement_rows",
        "binned_pair_sims",
        "patch_features",
        "binned_classify_ctp",
        "binned_ctp_vecs",
        "binned_ptc_ctp_metrics",
        "head_sim_corr_rows",
        "truncation_robustness_rows",
        "binned_calibration",
        "binned_song_stats",
    }
)

#: Active tables a reset scope must NEVER drop (defensive; kept as the inverse of the dead
#: inventory so an accidental request to drop a live table is refused as unclassified).
ACTIVE_DB_TABLES: frozenset[str] = frozenset(
    {
        "songs",
        "analyze_metrics",
        "song_retrieval_metrics",
        "stratified_corpus",
        "head_phase_provenance",
        "phase_timings",
        "stream_registry",
        "head_stream_registry",
        "run_provenance",
        "corpus_state",
        "catalog_metadata",
        "seg_config",
        "seg_meta",
        "seg_membership",
    }
)

#: Archival legacy cache directory names under ``<root>/cache/`` — legacy flat/PTC/CTP
#: threshold-specific copied vectors.  Removed by ``cleanup --scope archival`` ONLY with
#: explicit confirmation.  (``cache/flat_heads.py`` and the frozen ``streams/`` payloads are
#: Active and are never in this set.)
ARCHIVAL_CACHE_DIRNAMES: frozenset[str] = frozenset(
    {"flat_vecs", "binned_ptc", "binned_ptc_heads", "binned_ctp", "binned_ctp_heads"}
)


class UnclassifiedArtifactError(RuntimeError):
    """A cleanup scope was asked to delete an artifact not in the static inventory."""


@dataclass
class CleanupReport:
    """Outcome of one cleanup scope invocation.

    ``removed`` and ``skipped`` hold resolved absolute ``Path``s (or strings for DB tables
    when the scope is table-based); ``refused`` holds items rejected by a guard (retained-run
    protection, missing confirmation, or an unclassified target).  ``dry_run`` records whether
    the report describes intent without mutation.
    """

    scope: str
    dry_run: bool = False
    removed: list[object] = field(default_factory=list)
    skipped: list[object] = field(default_factory=list)
    refused: list[object] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return not self.dry_run and bool(self.removed)


# ── staging ─────────────────────────────────────────────────────────────────────


def discover_staging_tmp(root: Path, *, min_age_seconds: int = DEFAULT_STAGING_MIN_AGE) -> list[Path]:
    """Return leftover ``.tmp`` files under every ``.staging`` directory below *root*.

    A ``.tmp`` file present under ``.staging`` is an interrupted staged-write remnant
    (publication is fsync + atomic rename, so a surviving ``.tmp`` is never a valid registry
    state).  Files newer than ``min_age_seconds`` are excluded to avoid racing an in-flight
    write; an empty tree yields an empty list (never an error).
    """
    root = Path(root)
    if not root.is_dir():
        return []
    now = _now_ms() / 1000.0
    found: list[Path] = []
    for staging_dir in root.rglob(STAGING_DIRNAME):
        if not staging_dir.is_dir():
            continue
        for candidate in sorted(staging_dir.iterdir()):
            if not candidate.is_file() or not candidate.name.endswith(".tmp"):
                continue
            if min_age_seconds > 0 and (now - candidate.stat().st_mtime) < min_age_seconds:
                continue
            found.append(candidate)
    return found


def cleanup_staging(
    root: Path, *, min_age_seconds: int = DEFAULT_STAGING_MIN_AGE, dry_run: bool = False
) -> CleanupReport:
    """Remove aged ``.staging/*.tmp`` leftover staging files beneath *root* (reports each)."""
    report = CleanupReport(scope="staging", dry_run=dry_run)
    for path in discover_staging_tmp(root, min_age_seconds=min_age_seconds):
        if not dry_run:
            LOG.info("staging: removing %s", path)
            with suppress(FileNotFoundError):
                path.unlink()
        report.removed.append(path)
    return report


# ── views ───────────────────────────────────────────────────────────────────────


def _retained_view_hashes(con) -> frozenset[str]:
    """Keyset hashes referenced by ``run_provenance.retained=true`` rows' ``view_refs``.

    ``view_refs`` lines are ``keyset_hash|content_hash|view_ref`` (search_views._viewref_line);
    the leading key is the view directory name under ``<root>/views/<keyset_hash>/``.  Rows of
    every other (non-retained) run are NOT protected — their views are disposable and GC-able.
    """
    protected: set[str] = set()
    rows = con.execute(
        "SELECT view_refs FROM run_provenance WHERE retained = TRUE AND view_refs IS NOT NULL"
    ).fetchall()
    for (blob,) in rows:
        for line in (blob or "").splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            protected.add(line.split("|", 1)[0])
    return frozenset(protected)


def _view_dirs(root: Path) -> list[Path]:
    views_root = Path(root) / "views"
    if not views_root.is_dir():
        return []
    return sorted(p for p in views_root.iterdir() if p.is_dir())


def cleanup_views(con, root: Path, *, dry_run: bool = False) -> CleanupReport:
    """Remove disposable search views NOT referenced by a retained run.

    Views are always regenerable (``bounded_scoring``/``search_views`` contract) but a view
    referenced by a ``retained=true`` run is protected and never GC'd.  A missing database
    (``con is None``) means retained references cannot be known, so the scope refuses rather
    than risk deleting a retained view.
    """
    report = CleanupReport(scope="views", dry_run=dry_run)
    if con is None:
        report.refused.append("<db>")
        LOG.warning("views: refusing GC without a database connection (retained-run protection)")
        return report
    protected = _retained_view_hashes(con)
    for view_dir in _view_dirs(root):
        if view_dir.name in protected:
            report.skipped.append(view_dir)
            continue
        if not dry_run:
            LOG.info("views: removing disposable view %s", view_dir)
            shutil.rmtree(view_dir, ignore_errors=True)
        report.removed.append(view_dir)
    return report


# ── dead (tables) ───────────────────────────────────────────────────────────────


def cleanup_dead_tables(con, *, tables: Iterable[str] = DEAD_DB_TABLES, dry_run: bool = False) -> CleanupReport:
    """Drop statically-classified Dead DB tables (transactional).

    Every requested table must be a member of :data:`DEAD_DB_TABLES`; an unclassified name
    (including any Active table) raises :class:`UnclassifiedArtifactError` and nothing is
    dropped.  All drops happen in ONE transaction so a refusal aborts the whole scope.
    """
    report = CleanupReport(scope="dead", dry_run=dry_run)
    requested = list(tables)
    for name in requested:
        if name not in DEAD_DB_TABLES:
            raise UnclassifiedArtifactError(
                f"cleanup --scope dead refuses unclassified table {name!r}: only "
                f"{sorted(DEAD_DB_TABLES)} are statically-classified Dead"
            )
    existing = {
        r[0]
        for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()
    }
    if not dry_run:
        con.execute("BEGIN TRANSACTION")
    try:
        for name in requested:
            if name not in existing:
                report.skipped.append(name)
                continue
            if not dry_run:
                LOG.info("dead: dropping %s", name)
                con.execute(f"DROP TABLE IF EXISTS {name}")
            report.removed.append(name)
        if not dry_run:
            con.execute("COMMIT")
    except Exception:
        if not dry_run:
            with suppress(Exception):
                con.execute("ROLLBACK")
        raise
    return report


# ── archival ────────────────────────────────────────────────────────────────────


def cleanup_archival_caches(
    root: Path, *, dirnames: Iterable[str] = ARCHIVAL_CACHE_DIRNAMES, confirm: bool = False, dry_run: bool = False
) -> CleanupReport:
    """Remove archival legacy cache directories under ``<root>/cache/`` — WITH confirmation.

    Archival deletion is loud: without ``confirm=True`` (an interactive yes/no or an explicit
    ``--yes`` flag bound by Phase 4) every archival cache is refused and nothing is removed.
    Each *dirname* must be a member of :data:`ARCHIVAL_CACHE_DIRNAMES`; anything else is
    unclassified and refused.
    """
    report = CleanupReport(scope="archival", dry_run=dry_run)
    if not confirm:
        for d in dirnames:
            report.refused.append(d)
        LOG.warning("archival: deletion requires explicit confirmation; refusing (dry_run=%s)", dry_run)
        return report
    cache_root = Path(root) / "cache"
    for dirname in dirnames:
        if dirname not in ARCHIVAL_CACHE_DIRNAMES:
            raise UnclassifiedArtifactError(
                f"cleanup --scope archival refuses unclassified cache dir {dirname!r}: only "
                f"{sorted(ARCHIVAL_CACHE_DIRNAMES)} are archival"
            )
        target = cache_root / dirname
        if not target.exists():
            report.skipped.append(target)
            continue
        if not dry_run:
            LOG.info("archival: removing %s", target)
            shutil.rmtree(target, ignore_errors=True)
        report.removed.append(target)
    return report


# ── reset helpers (consistent with run.py _reset_db / _reset_cache_dirs) ─────────


def reset_db(db_path: Path) -> None:
    """Delete the DuckDB file (and its WAL) so the next run starts with a clean schema.

    Mirrors ``run.py._reset_db`` semantics: immutable ``.npy`` sidecar patches are preserved
    (they are the raw backbone outputs and expensive to regenerate); only the recomputable DB
    file is removed.  This is an explicit whole-file temp-DB reset, NOT a scoped row deletion
    and NOT the ``--scope analysis-run`` path (P3-S3 owns run-scoped analysis resets).
    """
    db_path = Path(db_path)
    if db_path.exists():
        LOG.info("reset: removing DB %s", db_path)
        db_path.unlink()
    wal = Path(str(db_path) + ".wal")
    if wal.exists():
        LOG.info("reset: removing WAL %s", wal)
        wal.unlink()


def reset_cache_dirs(root: Path, *, optimizer: bool = False, binned: bool = False) -> None:
    """Delete reset-eligible cache directories (mirrors ``run.py._reset_cache_dirs``).

    ``binned`` clears ``cache/binned_ptc`` and ``cache/binned_ctp``; ``optimizer`` clears the
    ``optimizer`` curves dir.  The similarity-matrix caches (``cache/sim.py`` / ``sim_pairs``)
    were removed in Plan C, so there is no sim cache to reset.  Only these explicit reset-
    eligible cache dirs are touched; sidecar/stream payloads are preserved.
    """
    root = Path(root)
    dirs: list[Path] = []
    if optimizer:
        dirs.append(root / "optimizer")
    if binned:
        dirs.extend([root / "cache" / "binned_ptc", root / "cache" / "binned_ctp"])
    for d in dirs:
        if d.exists():
            LOG.info("reset: removing cache dir %s", d)
            shutil.rmtree(d, ignore_errors=True)
        else:
            LOG.info("reset: cache dir not present (skip): %s", d)


# ── analysis-run reset (run-scoped) ────────────────────────────────────────────


def reset_analysis_run(
    con,
    run_id: str,
    *,
    override: bool = False,
    dry_run: bool = False,
) -> CleanupReport:
    """Transactionally delete exactly *run_id*'s ``analyze_metrics`` rows (run-scoped reset).

    This is the row-level reset backing the future ``cleanup --scope analysis-run RUN_ID``
    (Phase 4 wires the flag).  It deletes ONLY ``analyze_metrics`` rows whose physical ``run_id``
    column equals *run_id* — it never performs a global ``DELETE FROM analyze_metrics`` and never
    touches any other run's rows.

    Tier 1/2 protection: the legacy baseline/corpus scope (``run_id == db._schema.LEGACY_RUN_ID``)
    and any run whose ``run_provenance`` row is ``retained=true`` are REFUSED unless *override* is
    True.  Returns a :class:`CleanupReport` with ``scope='analysis-run'`` and honours ``dry_run``.
    """
    report = CleanupReport(scope="analysis-run", dry_run=dry_run)
    if _analysis_run_is_protected(con, run_id) and not override:
        LOG.warning("analysis-run: refusing reset of protected run %r (use override=True)", run_id)
        report.refused.append(run_id)
        return report
    n = int(con.execute("SELECT COUNT(*) FROM analyze_metrics WHERE run_id = ?", [run_id]).fetchone()[0])
    if n == 0:
        report.skipped.append(run_id)
        return report
    if not dry_run:
        con.execute("BEGIN TRANSACTION")
        try:
            con.execute("DELETE FROM analyze_metrics WHERE run_id = ?", [run_id])
            con.execute("COMMIT")
        except Exception:
            with suppress(Exception):
                con.execute("ROLLBACK")
            raise
        report.removed.append(f"analyze_metrics:run_id={run_id}:{n} rows")
    else:
        report.removed.append(f"analyze_metrics:run_id={run_id}")
    return report


def _analysis_run_is_protected(con, run_id: str) -> bool:
    """True when *run_id* is the legacy baseline scope or a retained run's scope."""
    from scripts.embedding_research.db._schema import LEGACY_RUN_ID

    if run_id == LEGACY_RUN_ID:
        return True
    try:
        row = con.execute(
            "SELECT 1 FROM run_provenance WHERE run_id = ? AND retained = TRUE LIMIT 1", [run_id]
        ).fetchone()
    except Exception:
        return False
    return row is not None


def _now_ms() -> int:
    return int(time.time() * 1000)
