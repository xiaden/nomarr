"""Find tracks similar to a portable seed descriptor using vector ANN search."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, TypedDict

from nomarr.components.library.library_file_mutation_comp import get_file_library_key
from nomarr.components.library.library_file_query_comp import get_files_by_ids_with_tags
from nomarr.components.ml.vectors.ml_vector_retrieve_comp import (
    get_cold_track_vector,
    search_similar_cold_track_vectors,
)
from nomarr.components.navidrome.descriptor_match_comp import TrackDescriptor, resolve_seed_descriptor_to_file

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
    musicbrainz_track_id: str | None
    musicbrainz_recording_id: str | None
    nomarr_file_key: str | None
    score: float


def find_similar_tracks(
    seed_descriptor: TrackDescriptor,
    count: int,
    backbone_id: str,
    db: Database,
    vector_group_size: int = 15,
    vector_search_thoroughness: int = 10,
) -> list[SimilarTrackResult]:
    """Find tracks similar to a portable seed descriptor.

    Pipeline:
        1. Resolve seed descriptor to Nomarr file_id
        2. Fetch seed vector from the promoted cold collection via components
        3. Run ANN search on cold collection
        4. Enrich result file_ids with descriptor metadata
        6. Return up to ``count`` results sorted by similarity score

    Args:
        seed_descriptor: Portable seed track descriptor from plugin.
        count: Maximum number of similar tracks to return.
        backbone_id: Vector backbone identifier (e.g., "effnet").
        db: Database instance passed through to components.
        vector_group_size: Songs per neighbourhood for nLists calculation.
        vector_search_thoroughness: Percentage of neighbourhoods to probe (1-100).

    Returns:
        List of similar tracks with portable descriptors and score,
        sorted by descending similarity score.

    Raises:
        ValueError: If seed descriptor cannot be resolved or has no vector.

    """
    # 1. Resolve seed descriptor to Nomarr file_id
    seed_file_id = resolve_seed_descriptor_to_file(db, seed_descriptor)
    if seed_file_id is None:
        msg = "Seed descriptor could not be resolved to an analyzed Nomarr track."
        raise ValueError(msg)

    logger.debug("Seed descriptor resolved to file_id %s", seed_file_id)

    # Auto-resolve library_key from the file document (library_id field is "libraries/{key}")
    library_key = get_file_library_key(db, seed_file_id)
    if library_key is None:
        msg = f"Could not resolve library for file '{seed_file_id}'. File may have been deleted."
        raise ValueError(msg)

    logger.debug("Resolved library_key=%s for file_id %s", library_key, seed_file_id)

    # 2. Get seed vector from cold collection through the vector component
    seed_doc = get_cold_track_vector(db, seed_file_id, backbone_id, library_key)
    if seed_doc is None:
        msg = (
            f"No vector embedding found for file '{seed_file_id}' "
            f"with backbone '{backbone_id}'. Ensure ML processing has completed."
        )
        raise ValueError(msg)

    seed_vector: list[float] = seed_doc["vector_n"]
    logger.debug("Seed vector retrieved, dim=%d", len(seed_vector))

    # 3. ANN search on cold collection
    fetch_limit = count + 1  # +1 for potential self-match
    raw_results = search_similar_cold_track_vectors(
        db=db,
        backbone_id=backbone_id,
        library_key=library_key,
        seed_vector=seed_vector,
        result_limit=fetch_limit,
        vector_group_size=vector_group_size,
        vector_search_thoroughness=vector_search_thoroughness,
    )

    # Exclude the seed track itself from results
    results = [r for r in raw_results if r["file_id"] != seed_file_id]
    logger.debug("ANN search returned %d results (excluding seed)", len(results))

    if not results:
        return []

    # 4. Enrich with metadata
    results = results[:count]
    enrichment_file_ids = [r["file_id"] for r in results]
    file_docs = get_files_by_ids_with_tags(db, enrichment_file_ids)
    file_docs_by_id: dict[str, dict] = {doc["_id"]: doc for doc in file_docs}

    # 5. Build result list
    output: list[SimilarTrackResult] = []
    for result in results:
        file_id = result["file_id"]
        doc = file_docs_by_id.get(file_id, {})
        tags = {
            str(tag.get("key", "")).casefold(): str(tag.get("value", ""))
            for tag in doc.get("tags", [])
            if isinstance(tag, dict) and isinstance(tag.get("key"), str)
        }
        duration_seconds = doc.get("duration_seconds")
        duration_ms = int(float(duration_seconds) * 1000.0) if isinstance(duration_seconds, (int, float)) else None
        track_number_raw = tags.get("track_number") or tags.get("tracknumber") or ""
        disc_number_raw = tags.get("disc_number") or tags.get("discnumber") or ""

        output.append(
            SimilarTrackResult(
                title=doc.get("title", ""),
                artist=doc.get("artist", ""),
                album=doc.get("album", ""),
                album_artist=tags.get("album_artist", tags.get("albumartist", "")),
                duration_ms=duration_ms,
                track_number=int("".join(ch for ch in track_number_raw if ch.isdigit()))
                if any(ch.isdigit() for ch in track_number_raw)
                else None,
                disc_number=int("".join(ch for ch in disc_number_raw if ch.isdigit()))
                if any(ch.isdigit() for ch in disc_number_raw)
                else None,
                year=doc.get("year") if isinstance(doc.get("year"), int) else None,
                musicbrainz_track_id=(
                    tags.get("musicbrainz_trackid")
                    or tags.get("musicbrainz_track_id")
                    or tags.get("musicbrainz/release track id")
                    or None
                ),
                musicbrainz_recording_id=(
                    tags.get("musicbrainz_recordingid")
                    or tags.get("musicbrainz_recording_id")
                    or tags.get("musicbrainzid")
                    or tags.get("musicbrainz_id")
                    or None
                ),
                nomarr_file_key=doc.get("_key"),
                score=float(result["score"]),
            )
        )

    logger.info(
        "find_similar_tracks: seed=%s, requested=%d, returned=%d",
        seed_file_id,
        count,
        len(output),
    )
    return output
