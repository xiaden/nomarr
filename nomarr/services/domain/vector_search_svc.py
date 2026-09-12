"""Vector search service for similarity search on cold tiers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, NoReturn

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
    from nomarr.helpers.dataclasses.vector_dataclass import SongVector, VectorMatch
    from nomarr.persistence.db import Database
    from nomarr.services.infrastructure.config_svc import ConfigService

logger = logging.getLogger(__name__)


class MissingSeedVectorError(ValueError):
    """Raised when the requested track has no vector for the backbone."""


class VectorIndexUnavailableError(ValueError):
    """Raised when the cold vector index is unavailable for searching."""


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
        song: SongIdentity,
        backbone_id: str,
        limit: int,
        min_score: float = 0.0,
        nprobe: int | None = None,
    ) -> list[VectorMatch]:
        """Search for similar tracks using vector similarity.

        Reads the source track's stored vector through its semantic
        ``SongIdentity`` locator, then performs a single ANN query against the
        per-backbone cold tier. Cross-library search is the default (tiers are
        per-backbone, not per-library).

        Args:
            song: Semantic ``SongIdentity`` locator addressing the source track.
            backbone_id: Backbone identifier (e.g., "effnet", "yamnet")
            limit: Maximum number of results
            min_score: Minimum cosine similarity threshold (-1 to 1). Results below
                this value are filtered out.
            nprobe: Retained for API compatibility (unused by the pgvector
                cold-tier search, which uses the global ``hnsw.ef_search``).

        Returns:
            Score-descending, threshold-filtered ``VectorMatch`` values, each
            carrying the matched ``SongIdentity`` locator and its stored
            embedding. No generated integer identity or transport key is
            produced here; opaque wire encoding happens at the interface
            boundary.

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

        # Read the source track's cold-tier vector through its semantic locator.
        song_vector = self.db.ml.get_song_vector(backbone_id, song)
        if song_vector is None:
            self._raise_missing_seed(backbone_id)
        seed_vector = song_vector.vector

        # Single ANN search on the per-backbone cold tier, requesting the
        # stored vector for each match so the API can echo it.
        matches = self.db.ml.search_similar_vectors(
            backbone_id,
            seed_vector,
            limit=limit,
            min_score=min_score,
            include_vector=True,
        )

        # Matches arrive distance-ordered (highest score first). Preserve the
        # explicit score filter and descending-score sort, dropping any match
        # whose stored vector was not returned.
        filtered = [m for m in matches if m.score >= min_score and m.vector is not None]
        filtered.sort(key=lambda m: m.score, reverse=True)

        logger.debug(
            f"Vector search: backbone={backbone_id}, limit={limit}, nprobe={nprobe}, "
            f"raw_matches={len(matches)}, filtered={len(filtered)}"
        )
        return filtered

    def get_track_vector(self, backbone_id: str, song: SongIdentity) -> SongVector | None:
        """Get the promoted cold-tier vector for a semantic song locator.

        Args:
            backbone_id: Backbone identifier
            song: Semantic ``SongIdentity`` locator addressing the track

        Returns:
            The selected track's :class:`SongVector`, or ``None`` when no
            promoted vector exists.

        """
        return self.db.ml.get_song_vector(backbone_id, song)

    def _raise_missing_seed(self, backbone_id: str) -> NoReturn:
        msg = f"No vector found for backbone '{backbone_id}'. Track may not have been processed yet."
        raise MissingSeedVectorError(msg)
