"""Persistence wrappers for calibration state management.

Absorbs all calibration-related ``db.*`` calls from calibration workflows
so they never touch persistence directly.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from arango.cursor import Cursor

    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Calibration state CRUD
# ---------------------------------------------------------------------------


def save_calibration_state(
    db: Database,
    *,
    model_key: str,
    head_name: str,
    label: str,
    calibration_def_hash: str,
    version: int,
    histogram_spec: dict[str, Any],
    p5: float,
    p95: float,
    sample_count: int,
    underflow_count: int,
    overflow_count: int,
    histogram_bins: list[dict[str, Any]] | None = None,
) -> None:
    """Persist a single label's calibration state (upsert)."""
    db.calibration_state.upsert_calibration_state(
        model_key=model_key,
        head_name=head_name,
        label=label,
        calibration_def_hash=calibration_def_hash,
        version=version,
        histogram_spec=histogram_spec,
        p5=p5,
        p95=p95,
        sample_count=sample_count,
        underflow_count=underflow_count,
        overflow_count=overflow_count,
        histogram_bins=histogram_bins,
    )


def load_all_calibration_states(
    db: Database,
) -> list[dict[str, Any]]:
    """Return every document in the ``calibration_state`` collection."""
    return db.calibration_state.get_all_calibration_states()


# ---------------------------------------------------------------------------
# Meta: calibration version / last-run
# ---------------------------------------------------------------------------


def get_calibration_version(db: Database) -> str | None:
    """Return the current global calibration version hash, or ``None``."""
    return db.meta.get("calibration_version")


def set_calibration_version(db: Database, version_hash: str) -> None:
    """Set the global calibration version hash."""
    db.meta.set("calibration_version", version_hash)


def set_calibration_last_run(db: Database, timestamp: str) -> None:
    """Record the timestamp of the last calibration run."""
    db.meta.set("calibration_last_run", timestamp)


# ---------------------------------------------------------------------------
# Library-file queries related to calibration
# ---------------------------------------------------------------------------


def update_file_calibration_hash(
    db: Database,
    file_id: str,
    calibration_hash: str,
) -> None:
    """Set the ``calibration_hash`` field on a single library file."""
    db.library_files.update_calibration_hash(file_id, calibration_hash)


# ---------------------------------------------------------------------------
# Bulk backfill helpers (absorb raw AQL from workflow)
# ---------------------------------------------------------------------------


def count_null_calibration_hashes(db: Database) -> int:
    """Count library files where ``calibration_hash`` is ``null``."""
    cursor = cast(
        "Cursor",
        db.db.aql.execute(
            """
            FOR f IN library_files
                FILTER f.calibration_hash == null
                COLLECT WITH COUNT INTO count
                RETURN count
            """,
        ),
    )
    return next(cursor, 0)


def backfill_null_calibration_hashes(
    db: Database,
    calibration_hash: str,
) -> int:
    """Set ``calibration_hash`` on all files where it is currently ``null``.

    Returns:
        Number of files updated.
    """
    cursor = cast(
        "Cursor",
        db.db.aql.execute(
            """
            FOR f IN library_files
                FILTER f.calibration_hash == null
                UPDATE f WITH { calibration_hash: @hash } IN library_files
                COLLECT WITH COUNT INTO updated
                RETURN updated
            """,
            bind_vars={"hash": calibration_hash},
        ),
    )
    return next(cursor, 0)


# ---------------------------------------------------------------------------
# Calibration analysis (convergence, reconciliation, history grouping)
# ---------------------------------------------------------------------------


def compute_convergence_status(db: Database) -> dict[str, Any]:
    """Compute latest convergence metrics for all calibration heads.

    Iterates every calibration state, fetches its most recent snapshot,
    and evaluates whether the head has converged
    (``|p5_delta| < 0.01`` **and** ``|p95_delta| < 0.01``).

    Returns:
        ``{head_key: {"latest_snapshot": ..., "p5_delta": ..., "converged": bool}}``
    """
    all_states = db.calibration_state.get_all_calibration_states()
    convergence_status: dict[str, Any] = {}

    for state in all_states:
        calibration_key = f"{state['model_key']}:{state['head_name']}"
        latest = db.calibration_history.get_latest_snapshot(calibration_key)

        if latest:
            p5_delta = latest.get("p5_delta")
            p95_delta = latest.get("p95_delta")
            converged = False
            if p5_delta is not None and p95_delta is not None:
                converged = abs(p5_delta) < 0.01 and abs(p95_delta) < 0.01

            convergence_status[calibration_key] = {
                "latest_snapshot": latest,
                "p5_delta": p5_delta,
                "p95_delta": p95_delta,
                "n": latest.get("n", 0),
                "converged": converged,
            }

    return convergence_status


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
    all_libraries = db.libraries.list_libraries()
    writable_libraries = {
        lib["_id"]: lib
        for lib in all_libraries
        if lib.get("file_write_mode") in ("minimal", "full")
    }

    if not writable_libraries:
        return {"requires_reconciliation": False, "affected_libraries": []}

    # Get calibration status by library
    calibration_status = db.library_files.get_calibration_status_by_library(global_version)

    affected_libraries = []
    for status in calibration_status:
        library_id = status["library_id"]
        if library_id in writable_libraries and status["outdated_count"] > 0:
            lib = writable_libraries[library_id]
            affected_libraries.append(
                {
                    "library_id": library_id,
                    "name": lib.get("name", "Unknown"),
                    "outdated_files": status["outdated_count"],
                    "file_write_mode": lib.get("file_write_mode"),
                }
            )

    return {
        "requires_reconciliation": len(affected_libraries) > 0,
        "affected_libraries": affected_libraries,
    }


