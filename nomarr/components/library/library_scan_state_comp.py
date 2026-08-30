"""Pipeline and scan state management for library scans.

Extracted from ``scan_lifecycle_comp`` — owns scan read and pipeline-axis
transition logic. Migrated to the library-domain boundary (P4-S3): functions
operate on domain ``Library`` values and typed ``LibraryPipelineState`` /
``LibraryScan`` value objects; no pipeline/scan dictionary or generated id
crosses this component's surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.helpers.constants.pipeline_states import VALID_PIPELINE_TRANSITIONS

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dataclasses.library_domain_dataclasses import (
        LibraryPipelineState,
        LibraryScan,
    )
    from nomarr.persistence.db import Database


def _pipeline_state_to_scan_status(
    pipeline_state: LibraryPipelineState | None,
    scan_doc: LibraryScan | None,
) -> str:
    """Derive legacy scan_status string from pipeline state and scan doc.

    Rules:
        - scan_state == "scanning" -> "scanning"
        - scan_doc.error present   -> "error"
        - scan_doc.finished_at set -> "complete"
        - otherwise                -> "idle"
    """
    if pipeline_state is not None and pipeline_state.scan_state == "scanning":
        return "scanning"
    if scan_doc is not None and scan_doc.error:
        return "error"
    if scan_doc is not None and scan_doc.finished_at is not None:
        return "complete"
    return "idle"


def get_scan_state(db: Database, library: Library) -> LibraryScan | None:
    """Return the scan for a library, or None when no scan exists."""
    return db.library.get_scan(library)


def transition_pipeline_axis(
    db: Database,
    library: Library,
    axis_field: str,
    next_state: str,
) -> None:
    """Update a single pipeline axis on a library's pipeline-state row.

    Validates that the transition is allowed from the current axis state.

    Raises:
        ValueError: If the transition is not valid from the current axis state.

    """
    current = db.library.get_pipeline_state(library)
    current_value = getattr(current, axis_field)
    if current_value is not None:
        # No-op: current state is already the target — skip validation and update
        if next_state == current_value:
            return
        allowed = VALID_PIPELINE_TRANSITIONS.get(axis_field, {}).get(current_value, set())
        if next_state not in allowed:
            msg = (
                f"Invalid pipeline transition for library {library.name} "
                f"axis {axis_field!r}: {current_value!r} -> {next_state!r}. "
                f"Allowed targets: {sorted(allowed)}"
            )
            raise ValueError(msg)
    db.library.set_pipeline_axis(library, axis_field, next_state)


def get_pipeline_state(db: Database, library: Library) -> LibraryPipelineState:
    """Return the four pipeline axis values for a library.

    Returns default values if the library has no pipeline state fields set.
    """
    return db.library.get_pipeline_state(library)


def get_libraries_in_axis_state(
    db: Database,
    axis_field: str,
    axis_value: str,
) -> list[Library]:
    """Return domain ``Library`` values whose pipeline axis equals ``axis_value``."""
    return db.library.get_libraries_in_axis_state(axis_field, axis_value)


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
    libraries = get_libraries_in_axis_state(db, axis_field, from_state)
    for library in libraries:
        db.library.set_pipeline_axis(library, axis_field, to_state)
    return len(libraries)
