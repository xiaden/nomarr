"""Pipeline and scan state management for library scans.

Extracted from ``scan_lifecycle_comp`` — owns scan-document read/write and
pipeline-axis transition logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from nomarr.components.library.library_id_comp import library_key_from_ref
from nomarr.helpers.constants.pipeline_states import (
    PIPELINE_DEFAULTS,
    VALID_PIPELINE_TRANSITIONS,
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


def _scan_doc_id(library_id: int) -> str:
    """Return the canonical scan document id for a library."""
    return f"library_scans/{library_key_from_ref(str(library_id))}"


def _default_scan_doc(library_id: int) -> dict[str, Any]:
    """Build the canonical default scan document payload."""
    library_key = library_key_from_ref(str(library_id))
    return {
        "_key": library_key,
        "library_key": library_key,
        **_DEFAULT_SCAN_FIELDS,
    }


async def ensure_scan_state(db: Database, library_id: int) -> dict[str, Any]:
    """Return the scan document for a library, creating or repairing it when needed."""
    library_key = library_key_from_ref(str(library_id))
    scan_doc = cast("dict[str, Any] | None", await db.library.get_scan(library_id))

    if scan_doc is None:
        default_doc = _default_scan_doc(library_id)
        await db.library.add_scan(library_id, default_doc)
        scan_doc = cast("dict[str, Any] | None", await db.library.get_scan(library_id)) or default_doc
    elif scan_doc.get("library_key") != library_key:
        repaired_doc = {
            **_DEFAULT_SCAN_FIELDS,
            **scan_doc,
            "_key": library_key,
            "library_key": library_key,
        }
        await db.library.remove_scan(library_id)
        await db.library.add_scan(library_id, repaired_doc)
        scan_doc = cast("dict[str, Any] | None", await db.library.get_scan(library_id)) or repaired_doc

    return scan_doc


async def get_scan_state(db: Database, library_id: int) -> dict[str, Any] | None:
    """Return the scan document for a library, repairing legacy rows when found."""
    scan_doc = cast("dict[str, Any] | None", await db.library.get_scan(library_id))
    if scan_doc is None:
        return None
    if scan_doc.get("library_key") != library_key_from_ref(str(library_id)):
        return await ensure_scan_state(db, library_id)
    return scan_doc


async def update_scan_state(db: Database, library_id: int, **fields: Any) -> dict[str, Any]:
    """Persist scan-state changes through the constructor-backed namespace."""
    scan_doc = await ensure_scan_state(db, library_id)
    if not fields:
        return scan_doc

    await db.library.update_scan(library_id, fields)
    refreshed = cast("dict[str, Any] | None", await db.library.get_scan(library_id))
    if refreshed is not None:
        return refreshed
    return {**scan_doc, **fields}


async def transition_pipeline_axis(
    db: Database,
    library_id: int,
    axis_field: str,
    next_state: str,
) -> None:
    """Update a single pipeline axis on a library document.

    Validates that the transition is allowed from the current axis state.

    Raises:
        ValueError: If the transition is not valid from the current axis state.

    """
    current = await db.app.get_pipeline_state(library_id)
    if current is not None:
        current_value = current.get(axis_field)
        if current_value is not None:
            # No-op: current state is already the target — skip validation and update
            if next_state == current_value:
                return
            allowed = VALID_PIPELINE_TRANSITIONS.get(axis_field, {}).get(current_value, set())
            if next_state not in allowed:
                msg = (
                    f"Invalid pipeline transition for library {library_id} "
                    f"axis {axis_field!r}: {current_value!r} -> {next_state!r}. "
                    f"Allowed targets: {sorted(allowed)}"
                )
                raise ValueError(msg)
    await db.app.update_pipeline_axis(library_id, axis_field, next_state)


async def get_pipeline_state(db: Database, library_id: int) -> dict[str, str]:
    """Return the four pipeline axis values for a library.

    Returns default values if the library has no pipeline state fields set.
    """
    state = await db.app.get_pipeline_state(library_id)
    if state is None:
        return dict(PIPELINE_DEFAULTS)
    return state


async def get_libraries_in_axis_state(
    db: Database,
    axis_field: str,
    axis_value: str,
) -> list[int]:
    """Return library document IDs where the given axis field matches the value."""
    return await db.app.get_libraries_in_axis_state(axis_field, axis_value)


async def bulk_transition_pipeline_axis(
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
    # No-op: source and target are the same — nothing to do
    if from_state == to_state:
        return 0
    allowed = VALID_PIPELINE_TRANSITIONS.get(axis_field, {}).get(from_state, set())
    if to_state not in allowed:
        msg = (
            f"Invalid bulk pipeline transition for axis {axis_field!r}: "
            f"{from_state!r} -> {to_state!r}. "
            f"Allowed targets: {sorted(allowed)}"
        )
        raise ValueError(msg)
    library_ids = await get_libraries_in_axis_state(db, axis_field, from_state)
    for library_id in library_ids:
        await db.app.update_pipeline_axis(library_id, axis_field, to_state)
    return len(library_ids)
