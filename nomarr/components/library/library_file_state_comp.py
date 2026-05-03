"""Library-file state helpers extracted from legacy persistence mixins."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from arango.exceptions import DocumentInsertError

from nomarr.helpers.constants.file_states import (
    ALL_STATE_VERTICES,
    AXIS_PAIRS,
    STATE_CALIBRATED,
    STATE_ERRORED,
    STATE_NOT_CALIBRATED,
    STATE_NOT_TAGGED,
    STATE_NOT_VECTORS_EXTRACTED,
    STATE_TAGGED,
    STATE_TAGS_CURRENT,
    STATE_TAGS_NOT_WRITTEN,
    STATE_TAGS_STALE,
    STATE_TOO_SHORT,
    STATE_VECTORS_EXTRACTED,
)

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


DUPLICATE_KEY_ERROR_CODE = 1210

# Build reverse lookup: given (from_vertex, to_vertex), verify the pair belongs to the same axis.
_VALID_TRANSITIONS: set[tuple[str, str]] = set()
for _positive, _negative in AXIS_PAIRS.values():
    _VALID_TRANSITIONS.add((_positive, _negative))
    _VALID_TRANSITIONS.add((_negative, _positive))


def transition_file_state(db: Database, file_ids: list[str], from_state: str, to_state: str) -> None:
    """Transition files between boolean state vertices with axis-pair validation.

    Validates that ``from_state`` and ``to_state`` belong to the same axis pair
    as defined in ``AXIS_PAIRS`` before delegating to persistence.

    Raises:
        ValueError: If the from/to pair is not a valid axis transition.
    """
    if (from_state, to_state) not in _VALID_TRANSITIONS:
        msg = (
            f"Invalid state transition: {from_state!r} -> {to_state!r}. "
            f"Transitions must swap between poles of the same axis (see AXIS_PAIRS)."
        )
        raise ValueError(msg)
    db.file_states.transition(file_ids, from_state, to_state)


def _insert_file_state_edges_ignoring_duplicates(db: Database, edge_docs: list[dict[str, str]]) -> None:
    for edge_doc in edge_docs:
        try:
            db.file_has_state.insert([edge_doc])
        except DocumentInsertError as exc:
            if exc.error_code != DUPLICATE_KEY_ERROR_CODE:
                raise


def _normalize_library_id(library_id: str) -> str:
    return library_id if "/" in library_id else f"libraries/{library_id}"


def _state_file_docs(db: Database, state_id: str) -> list[dict[str, Any]]:
    return db.file_states.traversal(state_id, "file_has_state", limit=None)


def _state_file_ids(db: Database, state_id: str) -> set[str]:
    return {doc["_id"] for doc in _state_file_docs(db, state_id)}


def _library_file_edges(db: Database, library_id: str) -> list[dict[str, Any]]:
    return db.library_contains_file._from.get.many(_normalize_library_id(library_id), limit=None)


def _library_file_ids(db: Database, library_id: str) -> set[str]:
    return {edge["_to"] for edge in _library_file_edges(db, library_id)}


def _extract_matching_head_keys(
    tags: list[dict[str, Any]],
    expected_heads: list[dict[str, Any]],
    namespace_prefix: str,
) -> list[str]:
    """Return expected `head_key` values matched by namespace-prefixed tags on label and model key."""
    matched_heads: list[str] = []
    seen_heads: set[str] = set()
    for tag in tags:
        name = tag.get("name")
        if not isinstance(name, str) or not name.startswith(namespace_prefix):
            continue
        name_without_prefix = name[4:]
        first_underscore = name_without_prefix.find("_")
        label = name_without_prefix[:first_underscore] if first_underscore >= 0 else name_without_prefix
        for expected in expected_heads:
            head_key = expected.get("head_key")
            labels = expected.get("labels", [])
            model_key_for_tag = expected.get("model_key_for_tag")
            if not isinstance(head_key, str) or not isinstance(model_key_for_tag, str):
                continue
            if label not in labels or model_key_for_tag not in name_without_prefix or head_key in seen_heads:
                continue
            matched_heads.append(head_key)
            seen_heads.add(head_key)
    return matched_heads


def initialize_file_states(db: Database, file_id: str) -> None:
    """Create all-negative state edges for one file."""
    negative_states = [
        state for state in ALL_STATE_VERTICES if state.startswith("file_states/not_") or state == STATE_TAGS_STALE
    ]
    edge_docs = [{"_from": file_id, "_to": state} for state in negative_states]
    _insert_file_state_edges_ignoring_duplicates(db, edge_docs)


def initialize_file_states_batch(db: Database, file_ids: list[str]) -> None:
    """Create all-negative state edges for multiple files."""
    if not file_ids:
        return
    negative_states = [
        state for state in ALL_STATE_VERTICES if state.startswith("file_states/not_") or state == STATE_TAGS_STALE
    ]
    edge_docs = [{"_from": file_id, "_to": state} for file_id in file_ids for state in negative_states]
    _insert_file_state_edges_ignoring_duplicates(db, edge_docs)


def clear_all_states(db: Database, file_id: str) -> int:
    """Remove all state edges for one file."""
    return db.file_has_state._from.delete(file_id)


def clear_all_states_batch(db: Database, file_ids: list[str]) -> int:
    """Remove all state edges for a batch of files."""
    if not file_ids:
        return 0
    return sum(db.file_has_state._from.delete(file_id) for file_id in file_ids)


def discover_next_untagged_file(
    db: Database,
    library_id: str | None = None,
    exclude_claimed: bool = True,
) -> dict[str, Any] | None:
    """Find the next file eligible for ML discovery work.

    Args:
        db: Database handle used to query file state and ownership edges.
        library_id: Optional library ``_id``; when provided, the scan is scoped to that library's files.
        exclude_claimed: When ``True``, skips files that already have a ``worker_claims`` entry; defaults to ``True``.

    Returns:
        A single library-file document dict, or ``None`` if no eligible file exists;
            files in ``too_short`` or ``errored`` states are always excluded.
    """
    untagged_files = _state_file_docs(db, STATE_NOT_TAGGED)
    candidate_ids = {doc["_id"] for doc in untagged_files}
    candidate_ids -= _state_file_ids(db, STATE_TOO_SHORT)
    candidate_ids -= _state_file_ids(db, STATE_ERRORED)
    if library_id is not None:
        candidate_ids &= _library_file_ids(db, library_id)
    if exclude_claimed:
        claimed_ids = {
            claim["file_id"]
            for claim in db.worker_claims.get.many.by_filter({}, limit=None)
            if isinstance(claim.get("file_id"), str)
        }
        candidate_ids -= claimed_ids
    candidate_docs = [doc for doc in untagged_files if doc["_id"] in candidate_ids]
    if not candidate_docs:
        return None
    return min(candidate_docs, key=lambda doc: str(doc.get("_key") or doc.get("_id") or ""))


def count_untagged_files(db: Database, library_id: str | None = None) -> int:
    """Count files in the ``not_tagged`` state."""
    untagged_ids = _state_file_ids(db, STATE_NOT_TAGGED)
    if library_id is not None:
        untagged_ids &= _library_file_ids(db, library_id)
    return len(untagged_ids)


def count_pending_tag_writes(db: Database) -> int:
    """Count files still waiting for file-tag writeback."""
    return len(db.file_has_state._to.get.many(STATE_TAGS_NOT_WRITTEN, limit=None))


def get_errored_file_ids(db: Database, library_id: str, limit: int | None = 500) -> list[str]:
    """Return errored file ids for one library."""
    library_file_ids = _library_file_ids(db, library_id)
    errored_file_ids = [
        edge["_from"]
        for edge in db.file_has_state._to.get.many(STATE_ERRORED, limit=None)
        if edge["_from"] in library_file_ids
    ]
    return errored_file_ids if limit is None else errored_file_ids[:limit]


def count_errored_files(db: Database, library_id: str) -> int:
    """Count errored files for one library."""
    return len(get_errored_file_ids(db, library_id, limit=None))


def get_uncalibrated_tagged_file_ids(db: Database, library_id: str) -> list[str]:
    """Return ids that are tagged and not calibrated within one library."""
    tagged_ids = _state_file_ids(db, STATE_TAGGED)
    not_calibrated_ids = _state_file_ids(db, STATE_NOT_CALIBRATED)
    library_file_ids = [edge["_to"] for edge in _library_file_edges(db, library_id)]
    eligible_ids = tagged_ids & not_calibrated_ids
    return [file_id for file_id in library_file_ids if file_id in eligible_ids]


def get_stale_file_ids(db: Database, library_id: str | None = None) -> list[str]:
    """Return file ids in the ``tags_stale`` state."""
    stale_files = _state_file_docs(db, STATE_TAGS_STALE)
    if library_id is None:
        return [doc["_id"] for doc in stale_files]
    library_file_ids = _library_file_ids(db, library_id)
    return [doc["_id"] for doc in stale_files if doc["_id"] in library_file_ids]


def get_calibration_status_by_library(db: Database) -> list[dict[str, Any]]:
    """Return per-library calibrated and not-calibrated counts."""
    calibrated_ids = _state_file_ids(db, STATE_CALIBRATED)
    not_calibrated_ids = _state_file_ids(db, STATE_NOT_CALIBRATED)
    results: list[dict[str, Any]] = []
    for library in db.libraries.get.many.by_filter({}, limit=None):
        library_id = library["_id"]
        library_file_ids = _library_file_ids(db, library_id)
        results.append(
            {
                "library_id": library_id,
                "calibrated_count": len(calibrated_ids & library_file_ids),
                "not_calibrated_count": len(not_calibrated_ids & library_file_ids),
            }
        )
    return results


def library_has_tagged_files(db: Database, library_id: str) -> bool:
    """Return whether a library contains at least one tagged file."""
    tagged_ids = _state_file_ids(db, STATE_TAGGED)
    return bool(tagged_ids & _library_file_ids(db, library_id))


def file_has_tagged_state(db: Database, file_id: str) -> bool:
    """Return whether one file currently has the tagged-state edge."""
    return db.file_has_state.count_by_filter({"_from": file_id, "_to": STATE_TAGGED}) > 0


def find_short_files_missing_too_short(db: Database, library_id: str, min_duration_s: int) -> list[str]:
    """Return short files that are missing the ``too_short`` state."""
    library_files = db.libraries.traversal(_normalize_library_id(library_id), "library_contains_file", limit=None)
    too_short_ids = {edge["_from"] for edge in db.file_has_state._to.get.many(STATE_TOO_SHORT, limit=None)}
    return [
        file_doc["_id"]
        for file_doc in library_files
        if file_doc.get("duration_seconds") is not None
        and file_doc["duration_seconds"] < min_duration_s
        and file_doc["_id"] not in too_short_ids
    ]


def get_files_with_incomplete_tags(
    db: Database,
    expected_heads: list[dict[str, Any]],
    namespace_prefix: str,
    library_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return tagged files missing one or more expected model heads.

    Args:
        db: Database handle used to inspect tagged files and their tag names.
        expected_heads: List of dicts where each item defines ``head_key``,
            ``labels``, and ``model_key_for_tag`` for one expected model head.
        namespace_prefix: Tag name prefix used to identify model-generated tags, such as ``"nom:"``.
        library_id: Optional library ``_id`` used to restrict the scan to one library.

    Returns:
        List of dicts with ``file_id``, ``file_key``, ``library_id``,
            ``matched_count``, ``missing_count``, and ``missing_heads`` for each
            tagged file missing one or more expected heads.
    """
    tagged_files = _state_file_docs(db, STATE_TAGGED)
    normalized_library_id = _normalize_library_id(library_id) if library_id is not None else None
    if normalized_library_id is not None:
        library_file_ids = _library_file_ids(db, normalized_library_id)
        tagged_files = [file_doc for file_doc in tagged_files if file_doc["_id"] in library_file_ids]
    file_ids = [file_doc["_id"] for file_doc in tagged_files]
    all_rows = (
        db.library_files.traversal.by_ids(
            file_ids,
            "song_has_tags",
            target_like_starts_with=("name", namespace_prefix),
        )
        if file_ids
        else []
    )
    tags_by_file: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in all_rows:
        start_id = row.get("start_id")
        tag = row.get("v")
        if not isinstance(start_id, str) or not isinstance(tag, dict):
            continue
        tags_by_file[start_id].append(tag)

    results: list[dict[str, Any]] = []
    for file_doc in tagged_files:
        matched_heads = _extract_matching_head_keys(
            tags_by_file.get(file_doc["_id"], []),
            expected_heads,
            namespace_prefix,
        )
        missing_heads = [
            expected["head_key"] for expected in expected_heads if expected["head_key"] not in matched_heads
        ]
        results.append(
            {
                "file_id": file_doc["_id"],
                "file_key": file_doc.get("_key"),
                "library_id": normalized_library_id,
                "matched_count": len(matched_heads),
                "missing_count": len(missing_heads),
                "missing_heads": missing_heads,
            }
        )
    return results


def bulk_set_not_calibrated(db: Database) -> int:
    """Transition all calibrated files back to not-calibrated."""
    file_ids = [edge["_from"] for edge in db.file_has_state._to.get.many(STATE_CALIBRATED, limit=None)]
    if not file_ids:
        return 0
    transition_file_state(db, file_ids, STATE_CALIBRATED, STATE_NOT_CALIBRATED)
    return len(file_ids)


def bulk_set_tags_stale(db: Database, library_id: str | None = None) -> int:
    """Transition ``tags_current`` files to ``tags_stale``."""
    file_ids = [edge["_from"] for edge in db.file_has_state._to.get.many(STATE_TAGS_CURRENT, limit=None)]
    if library_id is not None:
        library_file_ids = _library_file_ids(db, library_id)
        file_ids = [file_id for file_id in file_ids if file_id in library_file_ids]
    if not file_ids:
        return 0
    transition_file_state(db, file_ids, STATE_TAGS_CURRENT, STATE_TAGS_STALE)
    return len(file_ids)


def bulk_set_not_vectors_extracted(db: Database) -> int:
    """Transition all vector-extracted files back to not-extracted."""
    file_ids = [edge["_from"] for edge in db.file_has_state._to.get.many(STATE_VECTORS_EXTRACTED, limit=None)]
    if not file_ids:
        return 0
    transition_file_state(db, file_ids, STATE_VECTORS_EXTRACTED, STATE_NOT_VECTORS_EXTRACTED)
    return len(file_ids)
