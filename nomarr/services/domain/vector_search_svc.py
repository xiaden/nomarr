"""Vector search service for similarity search on cold tiers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, NoReturn

from nomarr.helpers.dataclasses.library_dataclass import Library

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.vector_dataclass import SongVector, VectorMatch
    from nomarr.persistence.db import Database
    from nomarr.services.infrastructure.config_svc import ConfigService

logger = logging.getLogger(__name__)


class MissingSeedVectorError(ValueError):
    """Raised when the requested track has no vector for the backbone."""


class VectorIndexUnavailableError(ValueError):
    """Raised when the cold vector index is unavailable for searching."""


def _resolve_match_file_id(db: Database, match: VectorMatch) -> int | None:
    """Adapt a result's natural ``SongIdentity`` back to its transport file id.

    The authoritative reverse lookup lives in ``db.library``: a match is located
    by its owning library's natural ``(name, root_path)`` key plus its
    ``normalized_path``, and the resulting song handle is returned.  This is the
    existing application/transport adaptation boundary — no integer storage id
    ever enters ``MlDb``; identities are converted back to transport ids here.
    """
    song_obj = db.library.get_song_by_normalized_path(
        match.song.normalized_path,
        Library(name=match.song.library.name, root_path=match.song.library.root_path or ""),
    )
    return song_obj.song_id if song_obj is not None else None


class VectorSearchService:
    """Service for vector similarity search operations.

    Searches against cold tiers only (promoted vectors with indexes). Hot tiers
    are write-only and never searched.
    """

    def __init__(self, db: Database, config_svc: ConfigService) -> None:
        """Initialize vector search service.

        Args:
            db: Database instance
            config_svc: Configuration service for dynamic settings

        """
        self.db = db
        self._config_svc = config_svc

    def search_similar_tracks(
        self,
        file_id: int,
        backbone_id: str,
        limit: int,
        min_score: float = 0.0,
        nprobe: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search for similar tracks using vector similarity.

        Resolves the source track's vector from ``file_id``, then performs a
        single ANN query against the per-backbone cold tier. Cross-library
        search is the default (tiers are per-backbone, not per-library).

        Args:
            file_id: Library file handle to find similar tracks for.
            backbone_id: Backbone identifier (e.g., "effnet", "yamnet")
            limit: Maximum number of results
            min_score: Minimum cosine similarity threshold (-1 to 1). Results below
                this value are filtered out.
            nprobe: Retained for API compatibility (unused by the pgvector
                cold-tier search, which uses the global ``hnsw.ef_search``).

        Returns:
            List of transport-adapted matches with exactly the keys:
                - file_id: Library file handle
                - score: Cosine similarity in [-1, 1] (higher = more similar)
                - vector: The stored embedding vector

        Raises:
            MissingSeedVectorError: If no vector exists for the source track.
            VectorIndexUnavailableError: If the cold vector index is unavailable.
            RuntimeError: If search query fails

        """
        # The cold HNSW index is a service prerequisite; check it before looking
        # up the seed so an unavailable index remains distinct from an
        # unprocessed track (503-before-404 precedence).
        if not self.db.ml.has_vector_index(backbone_id):
            raise VectorIndexUnavailableError(f"No vector index available for backbone '{backbone_id}'.")

        # Step 1: Resolve the source file handle to a natural identity through
        # the authoritative library lookup, then read its cold-tier vector.
        song = self.db.library.resolve_song_identity(file_id)
        if song is None:
            self._raise_missing_seed(file_id, backbone_id)
        song_vector = self.db.ml.get_song_vector(backbone_id, song)
        if song_vector is None:
            self._raise_missing_seed(file_id, backbone_id)
        seed_vector = song_vector.vector

        # Step 2: Single ANN search on the per-backbone cold tier, requesting
        # the stored vector for each match so the API can echo it.
        matches = self.db.ml.search_similar_vectors(
            backbone_id,
            seed_vector,
            limit=limit,
            include_vector=True,
        )

        # Matches arrive distance-ordered (highest score first). Preserve the
        # explicit score filter and descending-score sort.
        filtered = [m for m in matches if m.score >= min_score]
        filtered.sort(key=lambda m: m.score, reverse=True)

        logger.debug(
            f"Vector search: backbone={backbone_id}, limit={limit}, nprobe={nprobe}, "
            f"raw_matches={len(matches)}, filtered={len(filtered)}"
        )

        # Transport adaptation: identity -> file_id stays here (never in MlDb).
        results: list[dict[str, Any]] = []
        for match in filtered:
            match_file_id = _resolve_match_file_id(self.db, match)
            if match_file_id is None or match.vector is None:
                continue
            results.append(
                {
                    "file_id": match_file_id,
                    "score": match.score,
                    "vector": list(match.vector),
                }
            )
        return results

    def get_track_vector(self, backbone_id: str, file_id: int) -> SongVector | None:
        """Get vector for a specific track.

        Delegates to the get_track_vector workflow, which resolves the file
        handle to a natural identity and reads the cold-tier stored vector.

        Args:
            backbone_id: Backbone identifier
            file_id: Library file handle

        Returns:
            The selected track's :class:`SongVector`, or ``None`` when no
            promoted vector exists.

        """
        from nomarr.workflows.vectors.get_track_vector_wf import get_track_vector as get_track_vector_wf

        return get_track_vector_wf(self.db, file_id, backbone_id)

    def _raise_missing_seed(self, file_id: int, backbone_id: str) -> NoReturn:
        msg = (
            f"No vector found for file '{file_id}' with backbone "
            f"'{backbone_id}'. Track may not have been processed yet."
        )
        raise MissingSeedVectorError(msg)
