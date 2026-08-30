"""Library song state helpers extracted from legacy persistence mixins."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any

from nomarr.helpers.constants.file_states import (
    AXIS_PAIRS,
    STATE_CALIBRATED,
    STATE_ERRORED,
    STATE_HYDRATED,
    STATE_NOT_CALIBRATED,
    STATE_NOT_ERRORED,
    STATE_NOT_HYDRATED,
    STATE_NOT_PROCESSED,
    STATE_NOT_VECTORS_EXTRACTED,
    STATE_NOT_WRITTEN,
    STATE_PROCESSED,
    STATE_TAGS_CURRENT,
    STATE_TAGS_NOT_FRESH,
    STATE_VECTORS_EXTRACTED,
    STATE_WRITTEN,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


# Build reverse lookup: given (from_vertex, to_vertex), verify the pair belongs to the same axis.
_VALID_TRANSITIONS: set[tuple[str, str]] = set()
for _positive, _negative in AXIS_PAIRS.values():
    _VALID_TRANSITIONS.add((_positive, _negative))
    _VALID_TRANSITIONS.add((_negative, _positive))

# The 8 negative poles are the second element of each axis pair. Deriving them
# from AXIS_PAIRS (rather than a ``not_`` name prefix) is required because one
# negative pole (``tags_not_fresh``) is not ``not_``-prefixed and would be
# missed by a prefix check (AR-SDR-6 stripped the legacy doc-collection
# prefix from these bare constants).
_NEGATIVE_STATE_VERTICES: frozenset[str] = frozenset(neg for _, neg in AXIS_PAIRS.values())


def transition_song_state(db: Database, song_ids: list[int], from_state: str, to_state: str) -> None:
    """Transition songs between boolean state vertices with axis-pair validation.

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
    if not song_ids:
        return

    unique_song_ids = list(dict.fromkeys(song_ids))
    # The facade owns the assignment transaction and changes only this axis;
    # callers must not coordinate primitive remove/insert operations.
    db.app.transition_song_states(unique_song_ids, from_state, to_state)


def _state_song_docs(db: Database, state: str) -> list[Any]:
    return [song.to_dict() for song in db.app.songs_with_state(state)]


def _state_song_ids(db: Database, state: str) -> set[int]:
    docs = _state_song_docs(db, state)
    return {doc["id"] for doc in docs if isinstance(doc, dict) and "id" in doc}


def _library_song_docs(db: Database, library: Library) -> list[Any]:
    return [song.to_dict() for song in db.library.list_songs(library)]


def _library_song_ids(db: Database, library: Library) -> set[int]:
    docs = _library_song_docs(db, library)
    return {doc["id"] for doc in docs if isinstance(doc, dict) and "id" in doc}


def _state_membership_for_songs(db: Database, song_ids: list[int]) -> dict[int, set[str]]:
    """Return the current state memberships for the given song IDs.

    Uses a single targeted edge-traversal query — no full state scan,
    no document fetch.
    """
    if not song_ids:
        return {}
    return db.app.song_state_memberships(song_ids)


def _extract_matching_head_keys(
    tags: Sequence[Any],
    expected_heads: list[dict[str, Any]],
    namespace_prefix: str,
) -> list[str]:
    """Return expected `head_key` values matched by namespace-prefixed tags on label and model key."""
    matched_heads: list[str] = []
    seen_heads: set[str] = set()
    for tag in tags:
        name = tag.name
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


def initialize_song_states(db: Database, song_id: int) -> None:
    """Initialize all canonical negative state poles for one song."""
    # This overlaps concurrent state-component cleanup: keep the public helper,
    # but delegate initialization as one persistence intent operation.
    db.app.initialize_song_states([song_id])


def initialize_song_states_batch(db: Database, song_ids: list[int]) -> None:
    """Initialize all canonical negative state poles for multiple songs."""
    if song_ids:
        # Keep this helper's existing component contract while avoiding state
        # edge payloads that expose the underlying assignment table.
        db.app.initialize_song_states(song_ids)


def clear_all_states(db: Database, song_id: int) -> int:
    """Remove all processing-state membership for one song."""
    return db.app.clear_song_states([song_id])


def clear_all_states_batch(db: Database, song_ids: list[int]) -> int:
    """Remove all processing-state membership for multiple songs."""
    return db.app.clear_song_states(song_ids)


def discover_next_untagged_file(
    db: Database,
    library: Library | None = None,
    exclude_claimed: bool = True,
) -> dict[str, Any] | None:
    """Find the next song eligible for ML discovery, excluding errored songs."""
    untagged_files = _state_song_docs(db, STATE_NOT_PROCESSED)
    candidate_ids = {doc["id"] for doc in untagged_files if isinstance(doc, dict) and "id" in doc}
    errored_ids = _state_song_ids(db, STATE_ERRORED)
    candidate_ids -= errored_ids
    if library is not None:
        library_song_ids = _library_song_ids(db, library)
        candidate_ids &= library_song_ids
    if exclude_claimed:
        claims = db.app.list_claims()
        claimed_ids: set[int] = set()
        for claim in claims:
            file_id = claim.get("file_id")
            if isinstance(file_id, (int, str)):
                with contextlib.suppress(ValueError):
                    claimed_ids.add(int(file_id))
        candidate_ids -= claimed_ids
    candidate_docs = [doc for doc in untagged_files if doc.get("id") in candidate_ids]
    if not candidate_docs:
        return None
    return min(candidate_docs, key=lambda doc: str(doc.get("id") or ""))  # type: ignore[no-any-return]


def count_untagged_files(db: Database, library: Library | None = None) -> int:
    """Count songs in the ``not_processed`` state that are still taggable."""
    untagged_ids = _state_song_ids(db, STATE_NOT_PROCESSED)
    if library is not None:
        library_song_ids = _library_song_ids(db, library)
        untagged_ids &= library_song_ids
    return len(untagged_ids)


def discover_next_file_needing_tags(
    db: Database,
    library: Library | None = None,
    exclude_claimed: bool = True,
) -> dict[str, Any] | None:
    """Find the next song needing audio tag extraction, excluding errored songs."""
    pending_files = _state_song_docs(db, STATE_NOT_HYDRATED)
    candidate_ids = {doc["id"] for doc in pending_files if isinstance(doc, dict) and "id" in doc}
    errored_ids = _state_song_ids(db, STATE_ERRORED)
    candidate_ids -= errored_ids
    if library is not None:
        library_song_ids = _library_song_ids(db, library)
        candidate_ids &= library_song_ids
    if exclude_claimed:
        claims = db.app.list_claims()
        claimed_ids: set[int] = set()
        for claim in claims:
            file_id = claim.get("file_id")
            if isinstance(file_id, (int, str)):
                with contextlib.suppress(ValueError):
                    claimed_ids.add(int(file_id))
        candidate_ids -= claimed_ids
    candidate_docs = [doc for doc in pending_files if doc.get("id") in candidate_ids]
    if not candidate_docs:
        return None
    return min(candidate_docs, key=lambda doc: str(doc.get("id") or ""))  # type: ignore[no-any-return]


def count_pending_tag_writes(db: Database) -> int:
    """Count songs still waiting for tag writeback."""
    return db.app.count_songs_with_state(STATE_NOT_WRITTEN)


def get_errored_song_ids(db: Database, library: Library, limit: int | None = 500) -> list[int]:
    """Return errored song ids for one library."""
    library_song_ids = _library_song_ids(db, library)
    errored_files = [song.to_dict() for song in db.app.songs_with_state(STATE_ERRORED)]
    errored_song_ids = [
        doc["id"] for doc in errored_files if isinstance(doc, dict) and "id" in doc and doc["id"] in library_song_ids
    ]
    return errored_song_ids if limit is None else errored_song_ids[:limit]


def count_errored_songs(db: Database, library: Library) -> int:
    """Count errored songs for one library."""
    errored = get_errored_song_ids(db, library, limit=None)
    return len(errored)


def mark_song_errored(db: Database, song_id: int) -> None:
    """Mark a song errored while preserving every unrelated state axis."""
    transition_song_state(db, [song_id], STATE_NOT_ERRORED, STATE_ERRORED)
    logger.info("Song %s transitioned to errored", song_id)


def get_uncalibrated_tagged_song_ids(db: Database, library: Library) -> list[int]:
    """Return ids that are tagged and not calibrated within one library."""
    tagged_ids = _state_song_ids(db, STATE_PROCESSED)
    not_calibrated_ids = _state_song_ids(db, STATE_NOT_CALIBRATED)
    library_docs = _library_song_docs(db, library)
    library_song_ids = [doc["id"] for doc in library_docs if isinstance(doc, dict) and "id" in doc]
    eligible_ids = tagged_ids & not_calibrated_ids
    return [song_id for song_id in library_song_ids if song_id in eligible_ids]


def get_stale_song_ids(db: Database, library: Library | None = None) -> list[int]:
    """Return song ids in the ``tags_not_fresh`` state."""
    stale_files = _state_song_docs(db, STATE_TAGS_NOT_FRESH)
    if library is None:
        return [doc["id"] for doc in stale_files if isinstance(doc, dict) and "id" in doc]
    library_song_ids = _library_song_ids(db, library)
    return [doc["id"] for doc in stale_files if isinstance(doc, dict) and "id" in doc and doc["id"] in library_song_ids]


def get_calibration_status_by_library(db: Database) -> list[dict[str, Any]]:
    """Return per-library calibrated and not-calibrated counts."""
    calibrated_ids = _state_song_ids(db, STATE_CALIBRATED)
    not_calibrated_ids = _state_song_ids(db, STATE_NOT_CALIBRATED)
    results: list[dict[str, Any]] = []
    libraries = db.library.list_libraries()
    for library in libraries:
        library_song_ids = _library_song_ids(db, library)
        results.append(
            {
                "library_id": library.name,
                "calibrated_count": len(calibrated_ids & library_song_ids),
                "not_calibrated_count": len(not_calibrated_ids & library_song_ids),
            }
        )
    return results


def library_has_tagged_files(db: Database, library: Library) -> bool:
    """Return whether a library contains at least one tagged song."""
    tagged_ids = _state_song_ids(db, STATE_PROCESSED)
    lib_ids = _library_song_ids(db, library)
    return bool(tagged_ids & lib_ids)


def song_has_tagged_state(db: Database, song_id: int) -> bool:
    """Return whether one song is currently marked as processed."""
    return STATE_PROCESSED in db.app.song_state_membership(song_id)


def get_songs_with_incomplete_tags(
    db: Database,
    expected_heads: list[dict[str, Any]],
    namespace_prefix: str,
    library: Library | None = None,
) -> list[dict[str, Any]]:
    """Return written songs missing one or more expected model heads.

    Args:
        db: Database handle used to inspect written songs and their tag names.
        expected_heads: List of dicts where each item defines ``head_key``,
            ``labels``, and ``model_key_for_tag`` for one expected model head.
        namespace_prefix: Tag name prefix used to identify model-generated tags, such as ``"nom:"``.
        library: Optional domain ``Library`` used to restrict the scan to one
            library.

    Returns:
        List of dicts with ``file_id``, ``file_key``, ``library_id``,
            ``matched_count``, ``missing_count``, and ``missing_heads`` for each
            written song missing one or more expected heads.

    """
    written_files = _state_song_docs(db, STATE_WRITTEN)
    if library is not None:
        library_song_ids = _library_song_ids(db, library)
        written_files = [doc for doc in written_files if isinstance(doc, dict) and doc.get("id") in library_song_ids]
    song_ids = [doc["id"] for doc in written_files if isinstance(doc, dict) and "id" in doc]
    # Resolve the numeric state-document handles to domain identities before the
    # sealed tag facade (never pass integer song ids to the tag facade). Empty
    # song_ids yields an empty mapping without any facade call.
    identity_map = db.library.resolve_song_identities(song_ids) if song_ids else {}
    if identity_map:
        tags_by_identity = db.library.list_song_tags_for_songs(
            list(identity_map.values()), name_starts_with=namespace_prefix
        )
        # Re-key the identity-keyed assignments back to the integer file ids so
        # the per-file lookup below keeps working unchanged against int keys.
        tags_by_file = {
            song_id: tags_by_identity[identity]
            for song_id, identity in identity_map.items()
            if identity in tags_by_identity
        }
    else:
        tags_by_file = {}

    results: list[dict[str, Any]] = []
    for file_doc in written_files:
        if not isinstance(file_doc, dict):
            continue
        matched_heads = _extract_matching_head_keys(
            tags_by_file.get(file_doc["id"], []),
            expected_heads,
            namespace_prefix,
        )
        missing_heads = [
            expected["head_key"] for expected in expected_heads if expected["head_key"] not in matched_heads
        ]
        results.append(
            {
                "file_id": file_doc["id"],
                "file_key": file_doc.get("id"),
                "library_id": library,
                "matched_count": len(matched_heads),
                "missing_count": len(missing_heads),
                "missing_heads": missing_heads,
            }
        )
    return results


def bulk_set_not_calibrated(db: Database) -> int:
    """Transition all calibrated songs back to not-calibrated."""
    docs = _state_song_docs(db, STATE_CALIBRATED)
    song_ids = [doc["id"] for doc in docs if isinstance(doc, dict) and "id" in doc]
    if not song_ids:
        return 0
    transition_song_state(db, song_ids, STATE_CALIBRATED, STATE_NOT_CALIBRATED)
    return len(song_ids)


def bulk_set_tags_not_fresh(db: Database, library: Library | None = None) -> int:
    """Transition ``tags_current`` songs to ``tags_not_fresh``."""
    docs = _state_song_docs(db, STATE_TAGS_CURRENT)
    song_ids = [doc["id"] for doc in docs if isinstance(doc, dict) and "id" in doc]
    if library is not None:
        library_song_ids = _library_song_ids(db, library)
        song_ids = [song_id for song_id in song_ids if song_id in library_song_ids]
    if not song_ids:
        return 0
    transition_song_state(db, song_ids, STATE_TAGS_CURRENT, STATE_TAGS_NOT_FRESH)
    return len(song_ids)


def bulk_set_not_vectors_extracted(db: Database) -> int:
    """Transition all vector-extracted songs back to not-extracted."""
    docs = _state_song_docs(db, STATE_VECTORS_EXTRACTED)
    song_ids = [doc["id"] for doc in docs if isinstance(doc, dict) and "id" in doc]
    if not song_ids:
        return 0
    transition_song_state(db, song_ids, STATE_VECTORS_EXTRACTED, STATE_NOT_VECTORS_EXTRACTED)
    return len(song_ids)


def bulk_set_not_hydrated(db: Database, library: Library | None = None) -> int:
    """Transition all library songs needing it to not_hydrated, forcing re-hydration.

    Songs can exist without any hydration-state edge at all (hydration axis
    was introduced after initial scan).  This function handles three cases:
      - already hydrated  → transition to not_hydrated
      - no hydration edge → add        not_hydrated edge
      - already not_hydrated → no-op

    Returns the number of songs that were changed.
    """
    if library is not None:
        docs = _library_song_docs(db, library)
        song_ids = [doc["id"] for doc in docs if isinstance(doc, dict) and "id" in doc]
    else:
        # All songs globally (no library scope) — assemble by iterating libraries,
        # since the intent-level facade requires a Library scope for song listing.
        song_ids = [
            doc["id"]
            for lib in db.library.list_libraries()
            for doc in (song.to_dict() for song in db.library.list_songs(lib, limit=None))
            if isinstance(doc, dict) and "id" in doc
        ]

    if not song_ids:
        return 0

    hydrated_ids = _state_song_ids(db, STATE_HYDRATED)
    not_hydrated_ids = _state_song_ids(db, STATE_NOT_HYDRATED)
    errored_ids = _state_song_ids(db, STATE_ERRORED)

    to_transition = [fid for fid in song_ids if fid in hydrated_ids]
    to_add = [fid for fid in song_ids if fid not in hydrated_ids and fid not in not_hydrated_ids]
    to_recover = [fid for fid in song_ids if fid in errored_ids]

    if to_transition:
        transition_song_state(db, to_transition, STATE_HYDRATED, STATE_NOT_HYDRATED)
    if to_add:
        db.app.set_song_state(to_add, STATE_NOT_HYDRATED)
    if to_recover:
        transition_song_state(db, to_recover, STATE_ERRORED, STATE_NOT_ERRORED)

    return len(set(to_transition) | set(to_add) | set(to_recover))
