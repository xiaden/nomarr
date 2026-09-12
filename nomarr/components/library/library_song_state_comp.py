"""Library song state helpers extracted from legacy persistence mixins."""

from __future__ import annotations

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
    from collections.abc import Mapping, Sequence

    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.helpers.dataclasses.song_dataclass import Song
    from nomarr.helpers.dataclasses.song_state_candidate_dataclass import SongStateCandidate
    from nomarr.persistence.db import Database

from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_state_candidate_dataclass import IncompleteTagCandidate

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


def transition_song_state(db: Database, songs: Sequence[SongIdentity], from_state: str, to_state: str) -> None:
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
    if not songs:
        return

    unique_songs = list(dict.fromkeys(songs))
    # The facade owns locator resolution, assignment transaction, and axis-safe mutation.
    db.app.transition_song_states(unique_songs, from_state, to_state)


def _library_identity(library: Library) -> LibraryIdentity | None:
    """Return the UUID-bearing identity for a persisted library.

    Unsaved/configuration-only ``Library`` values cannot scope a song read.  A
    missing UUID is therefore a semantic scoped miss, never an invitation to
    reconstruct an identity from a generated integer key or mutable name/path.
    """
    if library.library_uuid is None:
        return None
    return LibraryIdentity(library_uuid=library.library_uuid, name=library.name, root_path=library.root_path)


def _state_candidates(db: Database, state: str, library: Library | None = None) -> list[SongStateCandidate]:
    """Read semantic state candidates through the typed library facade."""
    library_identity = _library_identity(library) if library is not None else None
    if library is not None and library_identity is None:
        return []
    return db.library.list_songs_with_state(state, library=library_identity)


def _state_song_docs(db: Database, state: str) -> list[Song]:
    return db.app.songs_with_state(state)


def _library_song_docs(db: Database, library: Library) -> list[Song]:
    identity = _library_identity(library)
    if identity is None:
        return []
    return db.library.list_songs(identity)


def _library_song_identities(db: Database, library: Library) -> list[SongIdentity]:
    """Derive locators from semantic library-scoped songs."""
    library_identity = _library_identity(library)
    if library_identity is None:
        return []
    return [
        SongIdentity(library=library_identity, normalized_path=song.normalized_path)
        for song in db.library.list_songs(library_identity, limit=None)
    ]


def _exclude_claimed(db: Database, candidates: list[SongStateCandidate]) -> list[SongStateCandidate]:
    """Remove claimed candidates using their semantic locators directly."""
    claimed_identities = {claim.song for claim in db.app.list_claims()}
    if not claimed_identities:
        return candidates
    return [candidate for candidate in candidates if candidate.identity not in claimed_identities]


def _state_membership_for_songs(db: Database, songs: Sequence[SongIdentity]) -> Mapping[SongIdentity, set[str]]:
    """Return the current state memberships for the given song IDs.

    Uses a single targeted edge-traversal query — no full state scan,
    no document fetch.
    """
    if not songs:
        return {}
    return db.app.song_state_memberships(songs)


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


def initialize_song_states(db: Database, song: SongIdentity) -> None:
    """Initialize all canonical negative state poles for one located song."""
    db.app.initialize_song_states([song])


def initialize_song_states_batch(db: Database, songs: Sequence[SongIdentity]) -> None:
    """Initialize canonical negative state poles for located songs."""
    if songs:
        db.app.initialize_song_states(list(dict.fromkeys(songs)))


def clear_all_states(db: Database, song: SongIdentity) -> int:
    """Remove all processing-state membership for one located song."""
    return db.app.clear_song_states([song])


def clear_all_states_batch(db: Database, songs: Sequence[SongIdentity]) -> int:
    """Remove all processing-state membership for located songs."""
    return db.app.clear_song_states(list(dict.fromkeys(songs)))


def discover_next_untagged_file(
    db: Database,
    library: Library | None = None,
    exclude_claimed: bool = True,
) -> SongStateCandidate | None:
    """Find the next semantic candidate eligible for ML discovery."""
    candidates = _state_candidates(db, STATE_NOT_PROCESSED, library)
    errored = {candidate.identity for candidate in _state_candidates(db, STATE_ERRORED, library)}
    candidates = [candidate for candidate in candidates if candidate.identity not in errored]
    if exclude_claimed:
        candidates = _exclude_claimed(db, candidates)
    return candidates[0] if candidates else None


def count_untagged_files(db: Database, library: Library | None = None) -> int:
    """Count semantic candidates in the ``not_processed`` state."""
    candidates = _state_candidates(db, STATE_NOT_PROCESSED, library)
    return len({candidate.identity for candidate in candidates})


def discover_next_file_needing_tags(
    db: Database,
    library: Library | None = None,
    exclude_claimed: bool = True,
) -> SongStateCandidate | None:
    """Find the next semantic candidate needing audio tag extraction."""
    candidates = _state_candidates(db, STATE_NOT_HYDRATED, library)
    errored = {candidate.identity for candidate in _state_candidates(db, STATE_ERRORED, library)}
    candidates = [candidate for candidate in candidates if candidate.identity not in errored]
    if exclude_claimed:
        candidates = _exclude_claimed(db, candidates)
    return candidates[0] if candidates else None


def count_pending_tag_writes(db: Database) -> int:
    """Count songs still waiting for tag writeback."""
    return db.app.count_songs_with_state(STATE_NOT_WRITTEN)


def get_errored_song_ids(db: Database, library: Library, limit: int | None = 500) -> list[SongIdentity]:
    """Return errored SongLocators for one library."""
    candidates = _state_candidates(db, STATE_ERRORED, library)
    identities = [candidate.identity for candidate in candidates]
    return identities if limit is None else identities[:limit]


def count_errored_songs(db: Database, library: Library) -> int:
    """Count errored songs for one library."""
    errored = get_errored_song_ids(db, library, limit=None)
    return len(errored)


def mark_song_errored(db: Database, song: SongIdentity) -> None:
    """Mark a located song errored while preserving unrelated state axes."""
    transition_song_state(db, [song], STATE_NOT_ERRORED, STATE_ERRORED)
    logger.info("Song at %s transitioned to errored", song.normalized_path)


def get_uncalibrated_tagged_song_ids(db: Database, library: Library) -> list[SongIdentity]:
    """Return tagged, not-calibrated SongLocators for one library."""
    candidates = _state_candidates(db, STATE_PROCESSED, library)
    not_calibrated = {candidate.identity for candidate in _state_candidates(db, STATE_NOT_CALIBRATED, library)}
    return [candidate.identity for candidate in candidates if candidate.identity in not_calibrated]


def get_stale_song_ids(db: Database, library: Library | None = None) -> list[SongIdentity]:
    """Return SongLocators in the ``tags_not_fresh`` state."""
    candidates = _state_candidates(db, STATE_TAGS_NOT_FRESH, library)
    return [candidate.identity for candidate in candidates]


def get_calibration_status_by_library(db: Database) -> list[dict[str, Any]]:
    """Return per-library calibrated and not-calibrated counts."""
    calibrated = {candidate.identity for candidate in _state_candidates(db, STATE_CALIBRATED)}
    not_calibrated = {candidate.identity for candidate in _state_candidates(db, STATE_NOT_CALIBRATED)}
    results: list[dict[str, Any]] = []
    for library in db.library.list_libraries():
        library_identity = _library_identity(library)
        library_songs = set(_library_song_identities(db, library)) if library_identity else set()
        results.append(
            {
                "library_id": library.name,
                "calibrated_count": len(calibrated & library_songs),
                "not_calibrated_count": len(not_calibrated & library_songs),
            }
        )
    return results


def library_has_tagged_files(db: Database, library: Library) -> bool:
    """Return whether a library contains at least one tagged song."""
    return bool(_state_candidates(db, STATE_PROCESSED, library))


def song_has_tagged_state(db: Database, song: SongIdentity) -> bool:
    """Return whether one located song is currently marked as processed."""
    return STATE_PROCESSED in db.app.song_state_membership(song)


def get_songs_with_incomplete_tags(
    db: Database,
    expected_heads: list[dict[str, Any]],
    namespace_prefix: str,
    library: Library | None = None,
) -> list[IncompleteTagCandidate]:
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
    candidates = _state_candidates(db, STATE_WRITTEN, library)
    tags_by_identity = (
        db.library.list_song_tags_for_songs(
            [candidate.identity for candidate in candidates], name_starts_with=namespace_prefix
        )
        if candidates
        else {}
    )
    results: list[IncompleteTagCandidate] = []
    for candidate in candidates:
        matched_heads = _extract_matching_head_keys(
            tags_by_identity.get(candidate.identity, []), expected_heads, namespace_prefix
        )
        missing_heads = [
            expected["head_key"] for expected in expected_heads if expected["head_key"] not in matched_heads
        ]
        if missing_heads:
            results.append(
                IncompleteTagCandidate(
                    identity=candidate.identity,
                    song=candidate.song,
                    matched_count=len(matched_heads),
                    missing_count=len(missing_heads),
                    missing_heads=tuple(missing_heads),
                )
            )
    return results


def bulk_set_not_calibrated(db: Database) -> int:
    """Transition all calibrated candidates back to not-calibrated."""
    candidates = _state_candidates(db, STATE_CALIBRATED)
    identities = [candidate.identity for candidate in candidates]
    if not identities:
        return 0
    transition_song_state(db, identities, STATE_CALIBRATED, STATE_NOT_CALIBRATED)
    return len(identities)


def bulk_set_tags_not_fresh(db: Database, library: Library | None = None) -> int:
    """Transition ``tags_current`` candidates to ``tags_not_fresh``."""
    candidates = _state_candidates(db, STATE_TAGS_CURRENT, library)
    identities = [candidate.identity for candidate in candidates]
    if not identities:
        return 0
    transition_song_state(db, identities, STATE_TAGS_CURRENT, STATE_TAGS_NOT_FRESH)
    return len(identities)


def bulk_set_not_vectors_extracted(db: Database) -> int:
    """Transition all vector-extracted candidates back to not-extracted."""
    candidates = _state_candidates(db, STATE_VECTORS_EXTRACTED)
    identities = [candidate.identity for candidate in candidates]
    if not identities:
        return 0
    transition_song_state(db, identities, STATE_VECTORS_EXTRACTED, STATE_NOT_VECTORS_EXTRACTED)
    return len(identities)


def bulk_set_not_hydrated(db: Database, library: Library | None = None) -> int:
    """Transition semantic library songs to ``not_hydrated`` for re-hydration."""
    if library is not None:
        identities = _library_song_identities(db, library)
    else:
        identities = [identity for lib in db.library.list_libraries() for identity in _library_song_identities(db, lib)]
    if not identities:
        return 0

    memberships = db.app.song_state_memberships(identities)
    to_transition = [song for song in identities if STATE_HYDRATED in memberships.get(song, set())]
    to_add = [
        song
        for song in identities
        if STATE_HYDRATED not in memberships.get(song, set()) and STATE_NOT_HYDRATED not in memberships.get(song, set())
    ]
    to_recover = [song for song in identities if STATE_ERRORED in memberships.get(song, set())]

    if to_transition:
        transition_song_state(db, to_transition, STATE_HYDRATED, STATE_NOT_HYDRATED)
    if to_add:
        db.app.set_song_state(to_add, STATE_NOT_HYDRATED)
    if to_recover:
        transition_song_state(db, to_recover, STATE_ERRORED, STATE_NOT_ERRORED)

    return len({*to_transition, *to_add, *to_recover})
