"""Persistence wrappers for calibration state management.

Absorbs all calibration-related ``db.*`` calls from calibration workflows
so they never touch persistence directly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_records_comp import list_library_records
from nomarr.components.library.library_song_state_comp import (
    bulk_set_not_calibrated,
    bulk_set_not_vectors_extracted,
    get_calibration_status_by_library,
    transition_song_state,
)
from nomarr.helpers.constants.file_states import STATE_CALIBRATED, STATE_NOT_CALIBRATED
from nomarr.helpers.dataclasses.calibration_history_dataclass import CalibrationHistorySnapshot
from nomarr.helpers.dataclasses.calibration_state_dataclass import CalibrationState
from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def count_recent_calibration_states(db: Database, threshold: int) -> int:
    """Count calibration state records updated at or after ``threshold``."""
    states = db.ml.list_calibration_states()
    return sum(1 for state in states if state.updated_at is not None and state.updated_at >= threshold)


def get_latest_calibration_state_updated_at(db: Database) -> int | None:
    """Return the most recent non-null ``updated_at`` timestamp."""
    states = db.ml.list_calibration_states()
    timestamps = [state.updated_at for state in states if state.updated_at is not None]
    return max(timestamps) if timestamps else None


def load_calibration_state(
    db: Database,
    model_id: str,
    head_name: str,
    label: str,
) -> CalibrationState | None:
    """Load one calibration state by its logical (model, head, label) identity."""
    return db.ml.get_calibration_state_view(model_id, head_name, label)


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
        model_id: Stable model identity
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
    state = CalibrationState(
        model_id=model_id,
        head_name=head_name,
        label=label,
        calibration_def_hash=calibration_def_hash,
        histogram=histogram_spec,
        histogram_bins=histogram_bins,
        p5=p5,
        p95=p95,
        sample_count=sample_count,
        underflow_count=underflow_count,
        overflow_count=overflow_count,
        updated_at=now_ms().value,
    )
    db.ml.replace_calibration_state(state)


def load_all_calibration_states(
    db: Database,
) -> list[CalibrationState]:
    """Return every calibration state as a domain value."""
    return [state for state, _model in db.ml.list_calibration_states_with_models()]


def load_calibration_lookup(db: Database) -> dict[str, dict[str, Any]]:
    """Return calibration parameters keyed by label for reconstruction and aggregation."""
    calibration_states = load_all_calibration_states(db)
    if not calibration_states:
        logger.debug("[calibration_state] No calibrations in database (initial state)")
        return {}

    calibrations: dict[str, dict[str, Any]] = {}
    for state in calibration_states:
        label = state.label
        p5 = state.p5
        p95 = state.p95
        calibration_def_hash = state.calibration_def_hash
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
    model_id: str,
    head_name: str,
    label: str,
) -> None:
    """Delete one calibration state record."""
    calibration_doc = load_calibration_state(db, model_id, head_name, label)
    if calibration_doc is None:
        return

    db.ml.remove_calibration_state(calibration_doc)


def create_calibration_history_snapshot(
    db: Database,
    model_id: str,
    head_name: str,
    label: str,
    p5: float,
    p95: float,
    sample_count: int,
    underflow_count: int,
    overflow_count: int,
    p5_delta: float | None = None,
    p95_delta: float | None = None,
    n_delta: int | None = None,
) -> None:
    """Record one calibration history snapshot for a model/head/label identity."""
    snapshot = CalibrationHistorySnapshot(
        model_id=model_id,
        head_name=head_name,
        label=label,
        snapshot_at=now_ms().value,
        p5=p5,
        p95=p95,
        sample_count=sample_count,
        underflow_count=underflow_count,
        overflow_count=overflow_count,
        p5_delta=p5_delta,
        p95_delta=p95_delta,
        n_delta=n_delta,
    )
    db.ml.add_calibration_history(snapshot)


def get_latest_calibration_history_snapshot(
    db: Database,
    model_id: str,
    head_name: str,
    label: str,
) -> CalibrationHistorySnapshot | None:
    """Return the newest history snapshot for one model/head/label identity."""
    return db.ml.get_latest_calibration_history_snapshot(model_id, head_name, label)


def delete_old_calibration_history_snapshots(
    db: Database,
    model_id: str,
    head_name: str,
    label: str,
    keep_count: int = 100,
) -> int:
    """Delete old history snapshots, retaining the newest ``keep_count`` rows.

    Delegates to the repository's natural-identity retention intent, which
    removes everything beyond the newest ``keep_count`` snapshots for the
    identity and returns the number of rows removed.
    """
    return db.ml.remove_calibration_history(model_id, head_name, label, keep_count)


# ---------------------------------------------------------------------------
# Calibration bookkeeping
# ---------------------------------------------------------------------------


def get_calibration_version(db: Database) -> str | None:
    """Return the current global calibration version hash, or ``None``."""
    return db.app.get_calibration_version()


def set_calibration_version(db: Database, version_hash: str) -> None:
    """Set the global calibration version hash."""
    db.app.set_calibration_version(version_hash)


def get_calibration_last_run(db: Database) -> int | None:
    """Return the timestamp (ms) of the last calibration run, or ``None``."""
    return db.app.get_calibration_last_run()


def set_calibration_last_run(db: Database, timestamp: str) -> None:
    """Record the timestamp of the last calibration run."""
    db.app.set_calibration_last_run(timestamp)


# ---------------------------------------------------------------------------
# Library-file queries related to calibration
# ---------------------------------------------------------------------------


def update_file_calibration_hash(
    db: Database,
    file_id: int,
) -> None:
    """Mark a single library file as calibrated."""
    transition_song_state(db, [file_id], STATE_NOT_CALIBRATED, STATE_CALIBRATED)


def update_file_calibration_hashes_batch(
    db: Database,
    file_ids: list[int],
) -> None:
    """Mark multiple library files as calibrated.

    Args:
        db: Database instance
        file_ids: List of file id values (e.g. ``123``).

    """
    for file_id in file_ids:
        transition_song_state(db, [file_id], STATE_NOT_CALIBRATED, STATE_CALIBRATED)


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
    writable_libraries = {lib.id: lib for lib in all_libraries if lib.file_write_mode in ("minimal", "full")}

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
                    "name": lib.name or "Unknown",
                    "outdated_files": status["not_calibrated_count"],
                    "file_write_mode": lib.file_write_mode,
                }
            )

    return {
        "requires_reconciliation": len(affected_libraries) > 0,
        "affected_libraries": affected_libraries,
    }


def clear_all_calibration_data(db: Database) -> dict[str, int]:
    """Remove all calibration data from the database.

    Truncates the calibration_state and calibration_history tables,
    clears the calibration bookkeeping values, and transitions all library
    files to the not calibrated and not vectors extracted states.

    Args:
        db: Database instance

    Returns:
        Summary containing ``files_updated`` and ``bookkeeping_values_cleared``.

    """
    # Multi-domain thin sanctioned sequence (ADR-046): the destructive ML table
    # resets live under maintenance, app bookkeeping on the app facade, and the
    # library state transitions via components. Each call is one atomic intent;
    # no single ML operation replaces this because it spans three sub-facades.
    db.ml.maintenance.truncate_calibration_states()
    db.ml.maintenance.truncate_calibration_history()

    # Clear calibration bookkeeping atomically (returns the number removed)
    bookkeeping_values_cleared = db.app.clear_calibration_metadata()

    # Mark all files as not calibrated and not vectors extracted
    files_updated = bulk_set_not_calibrated(db)
    bulk_set_not_vectors_extracted(db)

    return {"files_updated": files_updated, "bookkeeping_values_cleared": bookkeeping_values_cleared}
