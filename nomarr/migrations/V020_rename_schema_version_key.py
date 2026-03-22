"""V020: Rename meta.schema_version key to meta.version (integer → semver transition).

Background
----------
The integer-versioning era stored the current schema version as a document
{_key: "schema_version", value: <int>} in the ``meta`` collection.  The new
semver-based runner (Plan A) will write and read a {_key: "version", value:
<semver-str>} document instead.  This migration creates the new key set to
the current known version ("0.2.0") and removes the old integer key.

Idempotency
-----------
If {_key: "version"} already exists the migration exits early — it was
either already applied or the runner seeded it on first boot.
"""

import logging

from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

# Required metadata
MIGRATION_VERSION: str = "0.2.0"
DESCRIPTION: str = "Rename meta.schema_version key to meta.version (integer to semver transition)"


def upgrade(db: DatabaseLike) -> None:
    """Create meta.version and remove meta.schema_version."""
    # Idempotency check: if meta.version already exists, nothing to do.
    cursor = db.aql.execute(  # type: ignore[union-attr]
        "FOR doc IN meta FILTER doc._key == 'version' LIMIT 1 RETURN doc"
    )
    for _doc in cursor:  # type: ignore[union-attr]
        logger.info("V020: meta.version already exists — skipping (idempotent)")
        return

    # Insert the new semver key.
    db.aql.execute(  # type: ignore[union-attr]
        "INSERT {_key: 'version', value: '0.2.0'} INTO meta"
    )
    logger.info("V020: inserted meta.version = '0.2.0'")

    # Remove the old integer key — ignore if already absent.
    db.aql.execute("REMOVE {_key: 'schema_version'} IN meta OPTIONS {ignoreErrors: true}")  # type: ignore[union-attr]
    logger.debug("V020: ensured meta.schema_version removed (if it existed)")
