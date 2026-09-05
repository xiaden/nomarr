"""Current-format-only cleanup and analysis-reset maintenance (DD "cleanup/reset").

These are EXPLICIT SEPARATE maintenance operations wired to the run.py
``cleanup`` / ``reset`` commands — not pipeline phases.

Scope (DD frozen-observation corrective pass, ``cleanup_current``):

* ``staging`` — remove only current-format staging directories: unfinished
  ``catalogs/.staging-<run-id>/`` catalog builds and leftover ``.staging/*.tmp``
  staged-write files under ``streams/`` / ``heads/`` / ``audio_masks/`` /
  ``observation_commits/``.
* ``stray`` — remove only current-format digest-named payloads that no current
  manifest references (no sibling ``.json`` manifest) plus valid current-format
  catalogs in ``catalogs/<id>/`` that ``current.json`` does not select.
* ``views`` — remove disposable search-view materializations under
  ``<root>/disposable_views/``.

Candidates are derived from the current-format grammar (``parse_artifact_name``)
and manifest relationships ALONE — never a legacy classifier / rehasher /
adoption / supersession path.  The obsolete scopes (``dead``/``archival``/
``analysis-run``) and their module-level table/cache deletions were removed with
the deleted tables/directories they referenced (Plan E P1-S5 hard cut).

``reset_analysis`` removes ONLY the disposable ``research.duckdb`` (+ WAL) and
the ``disposable_views/`` tree.  Tier 1/2 payloads — corpus/, streams/, heads/,
audio_masks/, observation_commits/, catalogs/ — are preserved byte-for-byte.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from scripts.embedding_research.streams.publication import parse_artifact_name

_log = logging.getLogger(__name__)

CleanupScope = Literal["staging", "stray", "views"]

# Current-format digest payload families: <subdir> -> payload suffix.  A payload is
# stray when it matches the current grammar but has no sibling ``.json`` manifest.
_PAYLOAD_FAMILIES: tuple[tuple[str, str], ...] = (
    ("streams", ".npy"),
    ("heads", ".npz"),
    ("audio_masks", ".npy"),
)
# Subdirs that stage `.tmp` writes under a sibling ``.staging`` dir.
_STAGING_WRITE_SUBDIRS: tuple[str, ...] = ("streams", "heads", "audio_masks", "observation_commits")

_CATALOGS_DIR = "catalogs"
_CATALOGS_CURRENT = "current.json"
_CATALOG_MANIFEST = "catalog.manifest.json"
_VIEWS_DIR = "disposable_views"


@dataclass
class CleanupReport:
    """Outcome of one cleanup/reset operation (also the module CONTRACTS type)."""

    scope: str
    dry_run: bool = False
    removed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.removed)


# ── candidate discovery (current-format grammar + manifest relationships only) ──


def _staging_catalog_dirs(root: Path) -> list[Path]:
    catalogs = root / _CATALOGS_DIR
    if not catalogs.is_dir():
        return []
    return sorted(p for p in catalogs.glob(".staging-*") if p.is_dir())


def _leftover_staging_tmp(root: Path) -> list[Path]:
    out: list[Path] = []
    for sub in _STAGING_WRITE_SUBDIRS:
        staging = root / sub / ".staging"
        if not staging.is_dir():
            continue
        out.extend(f for f in sorted(staging.iterdir()) if f.is_file() and f.name.endswith(".tmp"))
    return out


def _digest_payloads_without_manifest(root: Path) -> list[Path]:
    """Digest-named payloads in the current subdirs with no sibling manifest."""
    out: list[Path] = []
    for sub, suffix in _PAYLOAD_FAMILIES:
        base = root / sub
        if not base.is_dir():
            continue
        for payload in sorted(base.glob(f"*{suffix}")):
            identity = parse_artifact_name(payload.name, suffix)
            if identity is None:
                # Not a current-format digest name (bare/.vN/legacy) — NOT a
                # current-format stray.  We never classify/remove these.
                continue
            sibling = payload.with_suffix(".json")
            if not sibling.is_file():
                out.append(payload)
    return out


def _stray_catalog_dirs(root: Path) -> list[Path]:
    """Valid current-format catalogs in ``catalogs/<id>/`` that current.json does not select."""
    catalogs = root / _CATALOGS_DIR
    if not catalogs.is_dir():
        return []
    selected: str | None = None
    current_file = catalogs / _CATALOGS_CURRENT
    if current_file.is_file():
        try:
            import json

            selected = json.loads(current_file.read_text(encoding="utf-8")).get("catalog_id")
        except (OSError, ValueError):
            selected = None  # cannot resolve the current selection; treat nothing as selectable
    out: list[Path] = []
    for d in sorted(catalogs.iterdir()):
        if not d.is_dir() or d.name.startswith(".staging-"):
            continue
        if selected is not None and d.name == selected:
            continue
        if (d / _CATALOG_MANIFEST).is_file() and (d / "catalog.duckdb").is_file():
            out.append(d)
    return out


def _view_entries(root: Path) -> list[Path]:
    views = root / _VIEWS_DIR
    if not views.is_dir():
        return []
    return sorted(views.iterdir())


# ── scoped cleanup ────────────────────────────────────────────────────────────


def _remove_tree(target: Path, report: CleanupReport) -> None:
    label = str(target)
    if not report.dry_run:
        if target.is_dir():
            shutil.rmtree(target)
        elif target.is_file():
            target.unlink()
    report.removed.append(label)


def _remove_file(target: Path, report: CleanupReport) -> None:
    if not report.dry_run:
        target.unlink()
    report.removed.append(str(target))


def cleanup_current(
    root: Path,
    _con,
    *,
    scope: CleanupScope,
    dry_run: bool = True,
) -> CleanupReport:
    """Report-then-remove current-format candidates for *scope* (see module docstring).

    *con* is accepted for signature parity with the module CONTRACTS but is not
    required: every candidate here is derived from the filesystem grammar and
    manifest relationships, so DB access is unnecessary.
    """
    root = Path(root)
    report = CleanupReport(scope=scope, dry_run=dry_run)

    if scope == "staging":
        for d in _staging_catalog_dirs(root):
            _remove_tree(d, report)
        for f in _leftover_staging_tmp(root):
            if f.is_file():
                _remove_file(f, report)
        return report

    if scope == "stray":
        for p in _digest_payloads_without_manifest(root):
            _remove_file(p, report)
        for d in _stray_catalog_dirs(root):
            _remove_tree(d, report)
        return report

    if scope == "views":
        for v in _view_entries(root):
            _remove_tree(v, report)
        # Remove the (now possibly empty) disposable views dir itself.
        views = root / _VIEWS_DIR
        if views.is_dir() and (report.dry_run or not any(views.iterdir())):
            _remove_tree(views, report)
        return report

    report.refused.append(f"unknown cleanup scope {scope!r}")
    return report


# ── reset (disposable analysis DB + views only) ──────────────────────────────


def reset_analysis(root: Path, db_path: Path, *, dry_run: bool = False) -> CleanupReport:
    """Remove ONLY the disposable analysis DB (+ WAL) and the disposable views tree.

    Never touches corpus/, streams/, heads/, audio_masks/, observation_commits/,
    catalogs/ (Tier 1/2 payloads) — they are preserved byte-for-byte.
    """
    root = Path(root)
    db = Path(db_path)
    report = CleanupReport(scope="analysis", dry_run=dry_run)
    targets: list[Path] = [c for c in (db, Path(f"{db}.wal")) if c.exists()]
    views = root / _VIEWS_DIR
    if views.is_dir():
        targets.append(views)
    for t in targets:
        _remove_tree(t, report)
    return report
