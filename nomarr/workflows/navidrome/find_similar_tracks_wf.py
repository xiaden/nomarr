"""Find tracks similar to a Navidrome seed track using vector ANN search.

Resolves a Navidrome song ID to a Nomarr file, retrieves its vector
embedding from the cold collection, runs approximate nearest neighbor
search, maps results back to Navidrome IDs, and enriches with metadata.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, TypedDict

from nomarr.helpers.vector_params_helper import compute_nlists, compute_nprobe

if TYPE_CHECKING:
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


class SimilarTrackResult(TypedDict):
    """A single similar track result with Navidrome ID and metadata."""

    nd_id: str
    name: str
    artist: str
    album: str
    score: float


def find_similar_tracks(
    seed_nd_id: str,
    count: int,
    backbone_id: str,
    db: Database,
    vector_group_size: int = 15,
    vector_search_thoroughness: int = 10,
) -> list[SimilarTrackResult]:
    """Find tracks similar to a Navidrome seed track.

    Pipeline:
        1. Resolve seed Navidrome ID to Nomarr file_id
        2. Fetch seed vector from cold collection (fallback to hot)
        3. Run ANN search on cold collection (over-fetch 2x to compensate for unmapped)
        4. Resolve result file_ids to Navidrome IDs
        5. Enrich mapped results with metadata (title, artist, album)
        6. Return up to ``count`` results sorted by similarity score

    Args:
        seed_nd_id: Navidrome mediafile ID of the seed track.
        count: Maximum number of similar tracks to return.
        backbone_id: Vector backbone identifier (e.g., "effnet").
        db: Database instance for persistence access.
        vector_group_size: Songs per neighbourhood for nLists calculation.
        vector_search_thoroughness: Percentage of neighbourhoods to probe (1-100).

    Returns:
        List of similar tracks with Navidrome IDs and metadata,
        sorted by descending similarity score.

    Raises:
        ValueError: If seed ID is not in the song map or has no vector.

    """
    # 1. Resolve seed Navidrome ID to Nomarr file_id
    seed_file_id = db.navidrome_tracks.resolve_nd_to_file(seed_nd_id)
    if seed_file_id is None:
        msg = f"Navidrome song ID '{seed_nd_id}' not found in track map. Run sync first."
        raise ValueError(msg)

    logger.debug("Seed ND ID %s resolved to file_id %s", seed_nd_id, seed_file_id)

    # Auto-resolve library_key from the file document (library_id field is "libraries/{key}")
    library_key = db.library_files.get_file_library_key(seed_file_id)
    if library_key is None:
        msg = f"Could not resolve library for file '{seed_file_id}'. File may have been deleted."
        raise ValueError(msg)

    logger.debug("Resolved library_key=%s for file_id %s", library_key, seed_file_id)

    # 2. Get seed vector from cold collection
    cold_ops = db.get_vectors_track_cold(backbone_id, library_key)
    seed_doc = cold_ops.get_vector(seed_file_id)

    if seed_doc is None:
        msg = (
            f"No vector embedding found for file '{seed_file_id}' "
            f"with backbone '{backbone_id}'. Ensure ML processing has completed."
        )
        raise ValueError(msg)

    seed_vector: list[float] = seed_doc["vector_n"]
    logger.debug("Seed vector retrieved, dim=%d", len(seed_vector))

    # 3. ANN search on cold collection (over-fetch to compensate for unmapped results)
    fetch_limit = count * 2 + 1  # +1 for potential self-match
    doc_count = cold_ops.count()
    nlists = compute_nlists(doc_count, vector_group_size)
    nprobe = compute_nprobe(nlists, vector_search_thoroughness)
    raw_results = cold_ops.search_similar(seed_vector, fetch_limit, nprobe=nprobe)

    # Exclude the seed track itself from results
    results = [r for r in raw_results if r["file_id"] != seed_file_id]
    logger.debug("ANN search returned %d results (excluding seed)", len(results))

    if not results:
        return []

    # 4. Resolve result file_ids to Navidrome IDs
    result_file_ids = [r["file_id"] for r in results]
    file_id_to_nd_id = db.navidrome_tracks.bulk_resolve_files_to_nd(result_file_ids)

    # Filter to only results that have a Navidrome mapping
    mapped_results = [(r, file_id_to_nd_id[r["file_id"]]) for r in results if r["file_id"] in file_id_to_nd_id]

    unmapped_count = len(results) - len(mapped_results)
    if unmapped_count > 0:
        if unmapped_count > len(results) * 0.5:
            logger.warning(
                "High ANN unmapped ratio; many similar-track results had no Navidrome mapping",
                extra={
                    "backbone_id": backbone_id,
                    "library_key": library_key,
                    "seed_nd_id": seed_nd_id,
                    "total_results": len(results),
                    "unmapped_count": unmapped_count,
                },
            )
        else:
            logger.debug(
                "Some ANN results had no Navidrome mapping, skipped",
                extra={
                    "backbone_id": backbone_id,
                    "library_key": library_key,
                    "seed_nd_id": seed_nd_id,
                    "total_results": len(results),
                    "unmapped_count": unmapped_count,
                },
            )

    if not mapped_results:
        return []

    # Trim to requested count before metadata enrichment
    mapped_results = mapped_results[:count]

    # 5. Enrich with metadata
    enrichment_file_ids = [r["file_id"] for r, _ in mapped_results]
    file_docs = db.library_files.get_files_by_ids_with_tags(enrichment_file_ids)
    file_docs_by_id: dict[str, dict] = {doc["_id"]: doc for doc in file_docs}

    # 6. Build result list
    output: list[SimilarTrackResult] = []
    for result, nd_id in mapped_results:
        file_id = result["file_id"]
        doc = file_docs_by_id.get(file_id, {})

        output.append(
            SimilarTrackResult(
                nd_id=nd_id,
                name=doc.get("title", ""),
                artist=doc.get("artist", ""),
                album=doc.get("album", ""),
                score=float(result["score"]),
            )
        )

    logger.info(
        "find_similar_tracks: seed=%s, requested=%d, returned=%d",
        seed_nd_id,
        count,
        len(output),
    )
    return output
