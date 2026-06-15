"""Pipeline and scan state management for library scans.

Extracted from ``scan_lifecycle_comp`` — owns scan-document read/write and
pipeline-axis transition logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from nomarr.components.library.library_id_comp import library_key_from_ref
from nomarr.helpers.constants.pipeline_states import (
    CAL_COMPLETE,
    CAL_IN_PROGRESS,
    CAL_NOT_CALIBRATED,
    CAL_STATE_FIELD,
    ML_COMPLETE,
    ML_IN_PROGRESS,
    ML_NOT_PROCESSED,
    ML_STATE_FIELD,
    PIPELINE_DEFAULTS,
    SCAN_COMPLETE,
    SCAN_IN_PROGRESS,
    SCAN_NOT_SCANNED,
    SCAN_STATE_FIELD,
    VALID_PIPELINE_TRANSITIONS,
    WRITE_COMPLETE,
    WRITE_IN_PROGRESS,
    WRITE_NOT_WRITTEN,
    WRITE_STATE_FIELD,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

_DEFAULT_SCAN_FIELDS: dict[str, Any] = {
    "files_processed": 0,
    "files_total": 0,
    "completed_at": None,
    "started_at": None,
    "error": None,
    "scan_type": None,
    "scan_heartbeat": None,
}


def _pipeline_state_to_scan_status(
    pipeline_state: dict[str, str] | None,
    scan_doc: dict[str, Any] | None,
) -> str:
    """Derive legacy scan_status string from pipeline state and scan doc.

    Rules:
        - scan_state == "scanning" -> "scanning"
        - scan_doc.error present   -> "error"
        - scan_doc.completed_at set -> "complete"
        - otherwise                -> "idle"
    """
    if pipeline_state and pipeline_state.get("scan_state") == "scanning":
        return "scanning"
    if scan_doc and scan_doc.get("error"):
        return "error"
    if scan_doc and scan_doc.get("completed_at"):
        return "complete"
    return "idle"


def _scan_doc_id(library_id: str) -> str:
    """Return the canonical scan document id for a library."""
    return f"library_scans/{library_key_from_ref(library_id)}"


def _default_scan_doc(library_id: str) -> dict[str, Any]:
    """Build the canonical default scan document payload."""
    library_key = library_key_from_ref(library_id)
    return {
        "_key": library_key,
        "library_key": library_key,
        **_DEFAULT_SCAN_FIELDS,
    }


def ensure_scan_state(db: Database, library_id: str) -> dict[str, Any]:
    """Return the scan document for a library, creating or repairing it when needed."""
    library_key = library_key_from_ref(library_id)
    scan_doc = cast("dict[str, Any] | None", db.app.get_scan(library_id))

    if scan_doc is None:
        default_doc = _default_scan_doc(library_id)
        db.app.add_scan(library_id, default_doc)
        scan_doc = cast("dict[str, Any] | None", db.app.get_scan(library_id)) or default_doc
    elif scan_doc.get("library_key") != library_key:
        repaired_doc = {
            **_DEFAULT_SCAN_FIELDS,
            **scan_doc,
            "_key": library_key,
            "library_key": library_key,
        }
        db.app.remove_scan(library_id)
        db.app.add_scan(library_id, repaired_doc)
        scan_doc = cast("dict[str, Any] | None", db.app.get_scan(library_id)) or repaired_doc

    return scan_doc


def get_scan_state(db: Database, library_id: str) -> dict[str, Any] | None:
    """Return the scan document for a library, repairing legacy rows when found."""
    scan_doc = cast("dict[str, Any] | None", db.app.get_scan(library_id))
    if scan_doc is None:
        return None
    if scan_doc.get("library_key") != library_key_from_ref(library_id):
        return ensure_scan_state(db, library_id)
    return scan_doc


def update_scan_state(db: Database, library_id: str, **fields: Any) -> dict[str, Any]:
    """Persist scan-state changes through the constructor-backed namespace."""
    scan_doc = ensure_scan_state(db, library_id)
    if not fields:
        return scan_doc

    db.app.update_scan(library_id, fields)
    refreshed = cast("dict[str, Any] | None", db.app.get_scan(library_id))
    if refreshed is not None:
        return refreshed
    return {**scan_doc, **fields}


def transition_pipeline_axis(
    db: Database,
    library_id: str,
    axis_field: str,
    next_state: str,
) -> None:
    """Update a single pipeline axis on a library document.

    Validates that the transition is allowed from the current axis state.

    Raises:
        ValueError: If the transition is not valid from the current axis state.
    """
    current = db.app.get_pipeline_state(library_id)
    if current is not None:
        current_value = current.get(axis_field)
        if current_value is not None:
            allowed = VALID_PIPELINE_TRANSITIONS.get(axis_field, {}).get(current_value, set())
            if next_state not in allowed:
                msg = (
                    f"Invalid pipeline transition for library {library_id} "
                    f"axis {axis_field!r}: {current_value!r} -> {next_state!r}. "
                    f"Allowed targets: {sorted(allowed)}"
                )
                raise ValueError(msg)
    db.app.update_pipeline_axis(library_id, axis_field, next_state)


def get_pipeline_state(db: Database, library_id: str) -> dict[str, str]:
    """Return the four pipeline axis values for a library.

    Returns default values if the library has no pipeline state fields set.
    """
    state = db.app.get_pipeline_state(library_id)
    if state is None:
        return dict(PIPELINE_DEFAULTS)
    return state


def get_libraries_in_axis_state(
    db: Database,
    axis_field: str,
    axis_value: str,
) -> list[str]:
    """Return library document IDs where the given axis field matches the value."""
    return db.app.get_libraries_in_axis_state(axis_field, axis_value)


def bulk_transition_pipeline_axis(
    db: Database,
    axis_field: str,
    from_state: str,
    to_state: str,
) -> int:
    """Transition every library currently in `from_state` on the given axis to `to_state`.

    Validates that the transition is allowed from the source state.

    Raises:
        ValueError: If the transition is not valid from the source state.
    """
    allowed = VALID_PIPELINE_TRANSITIONS.get(axis_field, {}).get(from_state, set())
    if to_state not in allowed:
        msg = (
            f"Invalid bulk pipeline transition for axis {axis_field!r}: "
            f"{from_state!r} -> {to_state!r}. "
            f"Allowed targets: {sorted(allowed)}"
        )
        raise ValueError(msg)
    library_ids = get_libraries_in_axis_state(db, axis_field, from_state)
    for library_id in library_ids:
        db.app.update_pipeline_axis(library_id, axis_field, to_state)
    return len(library_ids)


# Legacy shims — these map old single-value API to new per-axis API.
# They will be removed once all callers are updated.


def transition_pipeline_state(db: Database, library_id: str, next_state: str) -> None:
    """Legacy shim: map a single-value state to the appropriate axis transition."""
    axis_map = {
        SCAN_IN_PROGRESS: (SCAN_STATE_FIELD, SCAN_IN_PROGRESS),
        SCAN_COMPLETE: (SCAN_STATE_FIELD, SCAN_COMPLETE),
        SCAN_NOT_SCANNED: (SCAN_STATE_FIELD, SCAN_NOT_SCANNED),
        ML_IN_PROGRESS: (ML_STATE_FIELD, ML_IN_PROGRESS),
        ML_NOT_PROCESSED: (ML_STATE_FIELD, ML_NOT_PROCESSED),
        ML_COMPLETE: (ML_STATE_FIELD, ML_COMPLETE),
        CAL_IN_PROGRESS: (CAL_STATE_FIELD, CAL_IN_PROGRESS),
        CAL_NOT_CALIBRATED: (CAL_STATE_FIELD, CAL_NOT_CALIBRATED),
        CAL_COMPLETE: (CAL_STATE_FIELD, CAL_COMPLETE),
        WRITE_IN_PROGRESS: (WRITE_STATE_FIELD, WRITE_IN_PROGRESS),
        WRITE_NOT_WRITTEN: (WRITE_STATE_FIELD, WRITE_NOT_WRITTEN),
        WRITE_COMPLETE: (WRITE_STATE_FIELD, WRITE_COMPLETE),
    }
    if next_state not in axis_map:
        msg = f"Unknown pipeline state: {next_state!r}"
        raise ValueError(msg)
    axis_field, axis_value = axis_map[next_state]
    transition_pipeline_axis(db, library_id, axis_field, axis_value)


def bulk_transition_pipeline_state(db: Database, from_state: str, to_state: str) -> int:
    """Legacy shim: map single-value states to per-axis bulk transition."""
    axis_map = {
        SCAN_IN_PROGRESS: SCAN_STATE_FIELD,
        SCAN_COMPLETE: SCAN_STATE_FIELD,
        SCAN_NOT_SCANNED: SCAN_STATE_FIELD,
        ML_IN_PROGRESS: ML_STATE_FIELD,
        ML_NOT_PROCESSED: ML_STATE_FIELD,
        ML_COMPLETE: ML_STATE_FIELD,
        CAL_IN_PROGRESS: CAL_STATE_FIELD,
        CAL_NOT_CALIBRATED: CAL_STATE_FIELD,
        CAL_COMPLETE: CAL_STATE_FIELD,
        WRITE_IN_PROGRESS: WRITE_STATE_FIELD,
        WRITE_NOT_WRITTEN: WRITE_STATE_FIELD,
        WRITE_COMPLETE: WRITE_STATE_FIELD,
    }
    axis_field = axis_map.get(from_state)
    if axis_field is None:
        msg = f"Unknown pipeline state: {from_state!r}"
        raise ValueError(msg)
    return bulk_transition_pipeline_axis(db, axis_field, from_state, to_state)
