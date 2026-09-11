"""Find tracks similar to a portable seed descriptor using vector ANN search.

Plugin recommendation flow is descriptor-only and does not require Nomarr-side
Navidrome ID mapping.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, TypedDict

from nomarr.components.ml.vectors.ml_vector_retrieve_comp import (
    search_similar_cold_track_vectors,
)
from nomarr.components.navidrome.descriptor_match_comp import (
    TrackDescriptor,
    descriptor_for_locator,
    resolve_seed_descriptor_to_file,
)
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.song_locator_codec import SongLocatorFormatError, decode_song_locator

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


class SimilarTrackResult(TypedDict):
    """A single similar track result with portable descriptor metadata."""

    title: str
    artist: str
    album: str
    album_artist: str
    duration_ms: int | None
    track_number: int | None
    disc_number: int | None
    year: int | None
    nomarr_file_key: str | None
    score: float


def find_similar_tracks(
    seed_descriptor: TrackDescriptor,
    count: int,
    backbone_id: str,
    db: Database,
) -> list[SimilarTrackResult]:
    """Find tracks similar to a portable seed descriptor.

    Pipeline:
        1. Resolve seed descriptor to a library song id
        2. Fetch the seed's :class:`SongVector` from the promoted cold tier
        3. Run ANN search on the cold tier (typed :class:`VectorMatch` results)
        4. Exclude the seed track and enrich matched song identities with
           descriptor metadata
        5. Return up to ``count`` results sorted by similarity score

    Args:
        seed_descriptor: Portable seed track descriptor from plugin.
        count: Maximum number of similar tracks to return.
        backbone_id: Vector backbone identifier (e.g., "effnet").
        db: Database instance passed through to components.

    Returns:
        List of similar tracks with portable descriptors and score,
        sorted by descending similarity score.

    Raises:
        ValueError: If seed descriptor cannot be resolved or has no vector.

    """
    # 1. Resolve seed descriptor to an opaque SongLocator token, then to a
    # mutable SongIdentity locator. No generated integer id is introduced.
    seed_token, seed_resolution_status = resolve_seed_descriptor_to_file(db, seed_descriptor)
    if seed_token is None:
        if seed_resolution_status == "descriptor_ambiguous":
            msg = "Seed descriptor matched multiple tracks in Nomarr and is ambiguous."
            raise ValueError(msg)
        msg = "Seed descriptor could not be resolved to an analyzed Nomarr track."
        raise ValueError(msg)
    try:
        seed_payload = decode_song_locator(seed_token)
    except SongLocatorFormatError:
        msg = "Seed descriptor resolved to a malformed SongLocator token."
        raise ValueError(msg) from None
    seed_identity = SongIdentity(
        library=LibraryIdentity(library_uuid=seed_payload.library_uuid),
        normalized_path=seed_payload.path,
    )

    logger.debug("Seed descriptor resolved to locator %s", seed_identity.normalized_path)

    # 2. Get seed vector from the per-backbone cold tier via the typed ML boundary.
    seed_song_vector = db.ml.get_song_vector(backbone_id, seed_identity)
    if seed_song_vector is None:
        msg = (
            f"No vector embedding found for file '{seed_identity.normalized_path}' "
            f"with backbone '{backbone_id}'. Ensure ML processing has completed."
        )
        raise ValueError(msg)

    seed_vector = seed_song_vector.vector
    logger.debug("Seed vector retrieved, dim=%d", len(seed_vector))

    # 3. ANN search on per-backbone cold tier.
    fetch_limit = count + 1  # +1 for potential self-match
    raw_matches = search_similar_cold_track_vectors(
        db=db,
        backbone_id=backbone_id,
        seed_vector=seed_vector,
        result_limit=fetch_limit,
    )

    # Exclude the seed track itself by comparing natural identities.
    retained = [m for m in raw_matches if m.song != seed_identity]
    logger.debug("ANN search returned %d results (excluding seed)", len(retained))

    if not retained:
        return []

    # 4. Enrich with metadata by resolving each match's natural SongIdentity
    # through the shared descriptor builder. No integer file id is introduced.
    output: list[SimilarTrackResult] = []
    for match in retained[:count]:
        descriptor = descriptor_for_locator(db, match.song)
        if descriptor is None:
            continue
        output.append(
            SimilarTrackResult(
                title=descriptor["title"],
                artist=descriptor["artist"],
                album=descriptor["album"],
                album_artist=descriptor["album_artist"],
                duration_ms=descriptor["duration_ms"],
                track_number=descriptor["track_number"],
                disc_number=descriptor["disc_number"],
                year=descriptor["year"],
                nomarr_file_key=descriptor["nomarr_file_key"],
                # VectorMatch.score is the canonical clamped cosine similarity
                # produced by the vector repository.
                score=match.score,
            )
        )

    logger.info(
        "find_similar_tracks: seed=%s, requested=%d, returned=%d",
        seed_identity.normalized_path,
        count,
        len(output),
    )
    return output
