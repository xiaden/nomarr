"""V022: Seed config_pp_max_genre_playlists in meta for existing installations.

Adds the new personal-playlists config key with default value ``5`` without
overwriting any existing user-provided value.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

# Required metadata
MIGRATION_VERSION: str = "0.2.2"
DESCRIPTION: str = "Seed config_pp_max_genre_playlists default value"


def upgrade(db: DatabaseLike) -> None:
    """Seed the new config key for existing installations without overwriting."""
    db.aql.execute(  # type: ignore[union-attr]
        """
        UPSERT { key: @key }
        INSERT { key: @key, value: @value }
        UPDATE {}
        IN meta
        """,
        bind_vars={"key": "config_pp_max_genre_playlists", "value": "5"},
    )
    logger.info("V022: ensured meta config_pp_max_genre_playlists default is present")
