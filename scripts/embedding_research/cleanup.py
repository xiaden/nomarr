"""Current-format stream/observation cleanup and analysis reset."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import duckdb

from scripts.embedding_research.db._schema import schema_fingerprint
from scripts.embedding_research.streams.publication import parse_artifact_name

CleanupScope = Literal["staging", "stray"]


class GeometryResetUnavailableError(RuntimeError):
    """Geometry evidence is immutable and cannot be reset by maintenance."""

    code = "GEOMETRY_RESET_UNAVAILABLE"


_PAYLOAD_FAMILIES = (("streams", ".npy"), ("heads", ".npz"), ("audio_masks", ".npy"))
_STAGING_WRITE_SUBDIRS = ("streams", "heads", "audio_masks", "observation_commits")

#: Tables that hold run-scoped disposable analysis metrics/provenance/report state.
#: ``song_patch_geometry``, the stream/head registries, ``songs`` and ``corpus_state``
#: are deliberately absent: analysis reset must never delete or rewrite authoritative
#: geometry or upstream committed evidence (geometry DD reset topology / R12).  The
#: reset performs no filesystem mutation, so stream/mask/head payloads and
#: observation-commit markers are preserved byte-for-byte as well.
_DISPOSABLE_ANALYSIS_TABLES: tuple[str, ...] = (
    "geometry_analysis_records",
    "geometry_head_evidence",
    "head_phase_provenance",
    "analyze_incomplete_diagnostics",
    "analyze_metrics",
    "song_retrieval_metrics",
    "phase_timings",
    "run_provenance",
)


@dataclass
class CleanupReport:
    """Result of a maintenance cleanup/reset request, including refusals and removals."""

    scope: str
    dry_run: bool = False
    removed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.removed)


def _leftover_staging_tmp(root: Path) -> list[Path]:
    result: list[Path] = []
    for subdir in _STAGING_WRITE_SUBDIRS:
        staging = root / subdir / ".staging"
        if staging.is_dir():
            result.extend(item for item in sorted(staging.iterdir()) if item.is_file() and item.name.endswith(".tmp"))
    return result


def _digest_payloads_without_manifest(root: Path) -> list[Path]:
    result: list[Path] = []
    for subdir, suffix in _PAYLOAD_FAMILIES:
        directory = root / subdir
        if not directory.is_dir():
            continue
        for payload in sorted(directory.glob(f"*{suffix}")):
            if parse_artifact_name(payload.name, suffix) is not None and not payload.with_suffix(".json").is_file():
                result.extend((payload,))
    return result


def _remove(target: Path, report: CleanupReport) -> None:
    if not report.dry_run:
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    report.removed.append(str(target))


def _geometry_refusals(root: Path, con) -> list[str]:
    """Refuse maintenance when any committed observation's geometry is stale/corrupt."""
    import json

    from scripts.embedding_research.db.geometry import GeometryRefusal, verify_geometry_current
    from scripts.embedding_research.streams.store import StreamStore

    marker_dir = root / "observation_commits"
    if not marker_dir.is_dir():
        return []
    store = StreamStore(con, output_root=root)
    refusals: list[str] = []
    for marker in sorted(marker_dir.glob("*.json")):
        try:
            doc = json.loads(marker.read_text(encoding="utf-8"))
            observation = store.load_committed_observation(str(doc["song_id"]), str(doc["backbone"]))
            record = verify_geometry_current(con, observation, profile=None)
        except GeometryRefusal as exc:
            refusals.append(f"geometry {marker.name}: {exc.code}: {exc}")
            continue
        except Exception as exc:  # store/schema refusal is a fail-closed refusal
            refusals.append(f"geometry {marker.name}: INTEGRITY_REFUSED: {exc}")
            continue
        if record is None:
            refusals.append(
                f"geometry {marker.name}: INTEGRITY_REFUSED: no committed geometry for the current observation"
            )
    return refusals


def cleanup_current(root: Path, con, *, scope: CleanupScope, dry_run: bool = True) -> CleanupReport:
    """Remove leftover staging/stray filesystem payloads for one cleanup scope.

    Only ``staging`` (leftover ``.tmp`` payloads) and ``stray`` (digest payloads
    with no manifest) are valid scopes; any other scope is refused.  When a live
    connection is supplied, stale/corrupt current-geometry evidence refuses the
    whole cleanup rather than deleting files behind it.
    """
    report = CleanupReport(scope=scope, dry_run=dry_run)
    root = Path(root)
    if scope not in ("staging", "stray"):
        report.refused.append(f"unknown cleanup scope {scope!r}")
        return report
    if con is not None:
        # Refuse to remove anything while current geometry evidence is stale/corrupt; there
        # is no filesystem substitute and no repair path.
        report.refused.extend(_geometry_refusals(root, con))
        if report.refused:
            return report
    candidates = _leftover_staging_tmp(root) if scope == "staging" else _digest_payloads_without_manifest(root)
    for candidate in candidates:
        _remove(candidate, report)
    return report


def reset_analysis(_root: Path, db_path: Path, *, dry_run: bool = False) -> CleanupReport:
    """Remove disposable analysis state, preserving geometry and upstream evidence.

    Deletes only :data:`_DISPOSABLE_ANALYSIS_TABLES` rows from the primary research
    DuckDB.  Every ``song_patch_geometry`` row/BLOB, stream/mask/head registry row,
    ``songs``/``corpus_state`` row, and filesystem payload/marker/observation commit
    is left byte-for-byte unchanged: this function performs no filesystem mutation
    and never names the geometry table.  The schema fingerprint is checked first, so
    a pre-cut/mixed database is refused rather than partially reset.
    """
    report = CleanupReport(scope="analysis", dry_run=dry_run)
    db_path = Path(db_path)
    if not db_path.exists():
        return report
    if dry_run:
        report.skipped.append(f"analysis metadata in {db_path}")
        return report
    con = duckdb.connect(str(db_path))
    try:
        schema_fingerprint(con)
        for table in _DISPOSABLE_ANALYSIS_TABLES:
            con.execute(f"DELETE FROM {table}")
        con.commit()
        report.removed.append(f"analysis metadata in {db_path}")
    finally:
        con.close()
    return report


def reset_geometry(*_args, **_kwargs) -> None:
    """Refuse geometry reset; immutable evidence has no destructive maintenance path."""
    raise GeometryResetUnavailableError("GEOMETRY_RESET_UNAVAILABLE: geometry reset is unavailable")
