"""Persistence wrappers for calibration state management.

Absorbs all calibration-related ``db.*`` calls from calibration workflows
so they never touch persistence directly.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, cast

from nomarr.components.library.library_file_state_comp import (
    bulk_set_not_calibrated,
    bulk_set_not_vectors_extracted,
    get_calibration_status_by_library,
    transition_file_state,
)
from nomarr.components.library.library_records_comp import list_library_records
from nomarr.helpers.constants.file_states import STATE_CALIBRATED, STATE_NOT_CALIBRATED
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def _make_calibration_state_key(head_name: str, label: str) -> str:
    """Build the deterministic calibration_state document key."""
    raw = f"{head_name}:{label}"
    return re.sub(r"[^a-zA-Z0-9_:.@()+,=;$!*'%-]", "_", raw)


def count_recent_calibration_states(db: Database, threshold: int) -> int:
    """Count calibration_state documents updated at or after ``threshold``."""
    docs = db.ml.list_calibration_states()
    return sum(1 for doc in docs if isinstance(doc.get("updated_at"), int) and int(doc["updated_at"]) >= threshold)


def get_latest_calibration_state_updated_at(db: Database) -> int | None:
    """Return the most recent non-null ``updated_at`` timestamp."""
    docs = db.ml.list_calibration_states()
    timestamps = [value for doc in docs if isinstance((value := doc.get("updated_at")), int)]
    return max(timestamps) if timestamps else None


def load_calibration_state(
    db: Database,
    head_name: str,
    label: str,
) -> dict[str, Any] | None:
    """Load one calibration_state document by its logical identity."""
    return cast("dict[str, Any] | None", db.ml.get_calibration_state_doc(head_name, label))


# ---------------------------------------------------------------------------
# Calibration state CRUD
# ---------------------------------------------------------------------------


def save_calibration_state(
    db: Database,
    *,
    model_id: str,
    head_name: str,
    label: str,
    calibration_def_hash: str,
    histogram_spec: dict[str, Any],
    p5: float,
    p95: float,
    sample_count: int,
    underflow_count: int,
    overflow_count: int,
    histogram_bins: list[dict[str, Any]] | None = None,
) -> None:
    """Persist a single label's calibration state (upsert).

    Args:
        db: Database instance
        model_id: ArangoDB ``_id`` of the parent model vertex
        head_name: Head name (e.g., "mood_happy")
        label: Label to calibrate (e.g., "happy")
        calibration_def_hash: MD5 hash of calibration definition
        histogram_spec: Histogram parameters {lo, hi, bins, bin_width}
        p5: 5th percentile value
        p95: 95th percentile value
        sample_count: Total samples in histogram
        underflow_count: Samples below lo
        overflow_count: Samples above hi
        histogram_bins: Sparse histogram bins

    """
    _key = _make_calibration_state_key(head_name, label)
    doc = {
        "_key": _key,
        "head_name": head_name,
        "label": label,
        "calibration_def_hash": calibration_def_hash,
        "histogram": histogram_spec,
        "histogram_bins": histogram_bins,
        "p5": p5,
        "p95": p95,
        "n": sample_count,
        "underflow_count": underflow_count,
        "overflow_count": overflow_count,
        "updated_at": now_ms().value,
    }
    db.ml.upsert_calibration_state_doc(
        key=_key,
        payload={key: value for key, value in doc.items() if key != "_key"},
    )

    cs_id = f"calibration_state/{_key}"
    db.ml.upsert_model_has_calibration_edge(
        key=_key,
        model_id=model_id,
        calibration_state_id=cs_id,
    )


def load_all_calibration_states(
    db: Database,
) -> list[dict[str, Any]]:
    """Return every calibration_state document enriched with model metadata."""
    calibration_docs = db.ml.list_calibration_states()
    if not calibration_docs:
        return []

    # Batch-fetch all edges and models instead of one query per calibration doc.
    mhc_ids = [f"model_has_calibration/{doc['_key']}" for doc in calibration_docs if doc.get("_key")]
    edge_docs = db.ml.get_model_has_calibration_edges_by_ids(mhc_ids) if mhc_ids else []
    edge_by_key: dict[str, dict[str, Any]] = {str(e["_key"]): e for e in edge_docs if "_key" in e}

    unique_model_ids = list({str(e["_from"]) for e in edge_docs if e.get("_from")})
    model_docs = db.ml.get_models_by_ids(unique_model_ids) if unique_model_ids else []
    model_by_id: dict[str, dict[str, Any]] = {str(m["_id"]): m for m in model_docs if "_id" in m}

    enriched: list[dict[str, Any]] = []
    for calibration_doc in calibration_docs:
        model_info: dict[str, Any] | None = None
        calibration_key = calibration_doc.get("_key")
        if isinstance(calibration_key, str):
            edge = edge_by_key.get(calibration_key)
            model_id = str(edge["_from"]) if edge and edge.get("_from") else None
            if model_id is not None:
                model_doc = model_by_id.get(model_id)
                if model_doc is not None:
                    model_info = {
                        "backbone": model_doc.get("backbone"),
                        "embedder_release_date": model_doc.get("embedder_release_date"),
                    }

        enriched.append({**calibration_doc, "model": model_info})

    return sorted(
        enriched,
        key=lambda row: (str(row.get("head_name", "")), str(row.get("label", ""))),
    )


def load_calibration_lookup(db: Database) -> dict[str, dict[str, Any]]:
    """Return calibration parameters keyed by label for reconstruction and aggregation."""
    calibration_states = load_all_calibration_states(db)
    if not calibration_states:
        logger.debug("[calibration_state] No calibrations in database (initial state)")
        return {}

    calibrations: dict[str, dict[str, Any]] = {}
    for state in calibration_states:
        label = state.get("label")
        p5 = state.get("p5")
        p95 = state.get("p95")
        calibration_def_hash = state.get("calibration_def_hash")
        if label and p5 is not None and p95 is not None:
            calibrations[str(label)] = {
                "p5": p5,
                "p95": p95,
                "calibration_def_hash": calibration_def_hash,
            }

    logger.debug("[calibration_state] Loaded %d calibrations from database", len(calibrations))
    return calibrations


def delete_calibration_state(
    db: Database,
    head_name: str,
    label: str,
) -> None:
    """Delete one calibration_state document and its edge."""
    calibration_doc = load_calibration_state(db, head_name, label)
    if calibration_doc is None:
        return

    _key = _make_calibration_state_key(head_name, label)
    db.ml.delete_model_has_calibration_edge(edge_id=f"model_has_calibration/{_key}")
    calibration_id = cast("str", calibration_doc.get("_id", f"calibration_state/{_key}"))
    db.ml.delete_calibration_state_doc(calibration_id=calibration_id)


def create_calibration_history_snapshot(
    db: Database,
    calibration_key: str,
    p5: float,
    p95: float,
    sample_count: int,
    underflow_count: int,
    overflow_count: int,
    p5_delta: float | None = None,
    p95_delta: float | None = None,
    n_delta: int | None = None,
) -> str:
    """Insert a calibration_history snapshot document."""
    doc = {
        "calibration_key": calibration_key,
        "snapshot_at": now_ms().value,
        "p5": p5,
        "p95": p95,
        "n": sample_count,
        "underflow_count": underflow_count,
        "overflow_count": overflow_count,
        "p5_delta": p5_delta,
        "p95_delta": p95_delta,
        "n_delta": n_delta,
    }
    return cast("str", db.ml.add_calibration_history(payload=doc))


def get_latest_calibration_history_snapshot(
    db: Database,
    calibration_key: str,
) -> dict[str, Any] | None:
    """Return the newest history snapshot for one calibration key."""
    snapshots = cast(
        "list[dict[str, Any]]",
        db.ml.get_calibration_history_snapshots(calibration_key=calibration_key),
    )
    if not snapshots:
        return None

    return max(
        snapshots,
        key=lambda snapshot: cast("int", snapshot.get("snapshot_at", 0)),
    )


def delete_old_calibration_history_snapshots(
    db: Database,
    calibration_key: str,
    keep_count: int = 100,
) -> int:
    """Delete old history snapshots, keeping the newest ``keep_count`` rows."""
    snapshots = cast(
        "list[dict[str, Any]]",
        db.ml.get_calibration_history_snapshots(calibration_key=calibration_key),
    )
    if len(snapshots) <= keep_count:
        return 0

    ordered_snapshots = sorted(
        snapshots,
        key=lambda snapshot: cast("int", snapshot.get("snapshot_at", 0)),
        reverse=True,
    )
    stale_ids = [cast("str", snapshot["_id"]) for snapshot in ordered_snapshots[keep_count:] if "_id" in snapshot]
    if not stale_ids:
        return 0

    db.ml.delete_calibration_history_entries(entry_ids=stale_ids)
    return len(stale_ids)


# ---------------------------------------------------------------------------
# Meta: calibration version / last-run
# ---------------------------------------------------------------------------


def get_calibration_version(db: Database) -> str | None:
    """Return the current global calibration version hash, or ``None``."""
    calibration_doc = cast("dict[str, Any] | None", db.app.get_meta(key="calibration_version"))
    return None if calibration_doc is None else calibration_doc.get("value")


def set_calibration_version(db: Database, version_hash: str) -> None:
    """Set the global calibration version hash."""
    db.app.upsert_meta(key="calibration_version", payload={"value": version_hash})


def get_calibration_last_run(db: Database) -> int | None:
    """Return the timestamp (ms) of the last calibration run, or ``None``."""
    last_run_doc = cast("dict[str, Any] | None", db.app.get_meta(key="calibration_last_run"))
    last_run_str = None if last_run_doc is None else last_run_doc.get("value")
    return int(last_run_str) if last_run_str else None


def set_calibration_last_run(db: Database, timestamp: str) -> None:
    """Record the timestamp of the last calibration run."""
    db.app.upsert_meta(key="calibration_last_run", payload={"value": timestamp})


# ---------------------------------------------------------------------------
# Library-file queries related to calibration
# ---------------------------------------------------------------------------


def update_file_calibration_hash(
    db: Database,
    file_id: str,
) -> None:
    """Mark a single library file as calibrated."""
    transition_file_state(db, [file_id], STATE_NOT_CALIBRATED, STATE_CALIBRATED)


def update_file_calibration_hashes_batch(
    db: Database,
    file_ids: list[str],
) -> None:
    """Mark multiple library files as calibrated.

    Args:
        db: Database instance
        file_ids: List of file _id values (e.g. "library_files/abc123").

    """
    for file_id in file_ids:
        transition_file_state(db, [file_id], STATE_NOT_CALIBRATED, STATE_CALIBRATED)


def compute_reconciliation_info(
    db: Database,
    global_version: str | None,
) -> dict[str, Any]:
    """Compute which libraries need reconciliation after calibration.

    Checks all libraries with ``file_write_mode`` in ``('minimal', 'full')``
    and counts files with outdated ``calibration_hash``.

    Returns:
        ``{"requires_reconciliation": bool,
          "affected_libraries": [{library_id, name, outdated_files, file_write_mode}]}``
    """
    if not global_version:
        return {"requires_reconciliation": False, "affected_libraries": []}

    # Get libraries with write modes that use mood tags
    all_libraries = list_library_records(db, include_scan=False)
    writable_libraries = {lib["_id"]: lib for lib in all_libraries if lib.get("file_write_mode") in ("minimal", "full")}

    if not writable_libraries:
        return {"requires_reconciliation": False, "affected_libraries": []}

    # Get calibration status by library
    calibration_status = get_calibration_status_by_library(db)

    affected_libraries = []
    for status in calibration_status:
        library_id = status["library_id"]
        if library_id in writable_libraries and status["not_calibrated_count"] > 0:
            lib = writable_libraries[library_id]
            affected_libraries.append(
                {
                    "library_id": library_id,
                    "name": lib.get("name", "Unknown"),
                    "outdated_files": status["not_calibrated_count"],
                    "file_write_mode": lib.get("file_write_mode"),
                }
            )

    return {
        "requires_reconciliation": len(affected_libraries) > 0,
        "affected_libraries": affected_libraries,
    }


def clear_all_calibration_data(db: Database) -> dict[str, int]:
    """Remove all calibration data from the database.

    Truncates calibration_state and calibration_history collections,
    removes calibration meta keys, and transitions all library files to the
    not calibrated and not vectors extracted states.

    Args:
        db: Database instance

    Returns:
        Summary containing ``files_updated`` and ``meta_keys_cleared``.

    """
    # Truncate calibration collections
    db.ml.truncate_calibration_states()
    db.ml.truncate_calibration_history()

    # Clear calibration meta keys
    meta_keys_cleared = 0
    for key in ("calibration_version", "calibration_last_run"):
        if db.app.get_meta(key=key) is not None:
            db.app.delete_meta(key=key)
            meta_keys_cleared += 1

    # Mark all files as not calibrated and not vectors extracted
    files_updated = bulk_set_not_calibrated(db)
    bulk_set_not_vectors_extracted(db)

    return {"files_updated": files_updated, "meta_keys_cleared": meta_keys_cleared}
