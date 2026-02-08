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
    calibration_def_hash: str,
    version: int,
    histogram_spec: dict[str, Any],
    p5: float,
    p95: float,
    sample_count: int,
    underflow_count: int,
    overflow_count: int,
) -> None:
    """Persist a single head's calibration state (upsert)."""
    db.calibration_state.upsert_calibration_state(
        model_key=model_key,
        head_name=head_name,
        calibration_def_hash=calibration_def_hash,
        version=version,
        histogram_spec=histogram_spec,
        p5=p5,
        p95=p95,
        sample_count=sample_count,
        underflow_count=underflow_count,
        overflow_count=overflow_count,
    )


def load_all_calibration_states(
    db: Database,
) -> list[dict[str, Any]]:
    """Return every document in the ``calibration_state`` collection."""
    return db.calibration_state.get_all_calibration_states()


# ---------------------------------------------------------------------------
# Calibration history
# ---------------------------------------------------------------------------


def create_calibration_snapshot(
    db: Database,
    *,
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
    """Create a point-in-time snapshot for progressive calibration tracking.

    Returns:
        The ``_key`` of the created snapshot document.
    """
    return db.calibration_history.create_snapshot(
        calibration_key=calibration_key,
        p5=p5,
        p95=p95,
        sample_count=sample_count,
        underflow_count=underflow_count,
        overflow_count=overflow_count,
        p5_delta=p5_delta,
        p95_delta=p95_delta,
        n_delta=n_delta,
    )


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


def count_tagged_files(db: Database, namespace: str = "nom") -> int:
    """Count library files that have tags in *namespace*."""
    return db.library_files.count_files_with_tags(namespace)


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
