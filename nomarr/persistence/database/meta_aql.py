"""Meta operations for ArangoDB (key-value config store)."""

import json
from typing import TYPE_CHECKING, Any, cast

from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor


class MetaOperations:
    """Operations for the meta collection (key-value configuration)."""

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db
        self.collection = db.collection("meta")

    def get(self, key: str) -> str | None:
        """Get a meta value by key.

        Args:
            key: Configuration key

        Returns:
            Value string or None if not found

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR meta IN meta
                FILTER meta.key == @key
                SORT meta._key
                LIMIT 1
                RETURN meta.value
            """,
                bind_vars={"key": key},
            ),
        )
        return next(cursor, None)

    def set(self, key: str, value: str) -> None:
        """Set a meta key-value pair (upsert).

        Args:
            key: Configuration key
            value: Configuration value

        """
        self.db.aql.execute(
            """
            UPSERT { key: @key }
            INSERT { key: @key, value: @value }
            UPDATE { value: @value }
            IN meta
            """,
            bind_vars={"key": key, "value": value},
        )

    def delete(self, key: str) -> None:
        """Delete a meta key.

        Args:
            key: Configuration key to delete

        """
        self.db.aql.execute(
            """
            FOR meta IN meta
                FILTER meta.key == @key
                REMOVE meta IN meta
            """,
            bind_vars={"key": key},
        )

    def get_all(self) -> dict[str, str]:
        """Get all meta key-value pairs.

        Returns:
            Dict of key -> value

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR meta IN meta
                RETURN { key: meta.key, value: meta.value }
            """,
            ),
        )
        return {item["key"]: item["value"] for item in cursor}

    def get_by_prefix(self, prefix: str) -> dict[str, str]:
        """Get all key-value pairs where key starts with prefix.

        Returns:
            Dict mapping keys to values

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR meta IN meta
                FILTER STARTS_WITH(meta.key, @prefix)
                RETURN {key: meta.key, value: meta.value}
            """,
                bind_vars=cast("dict[str, Any]", {"prefix": prefix}),
            ),
        )

        result = {}
        for row in cursor:
            result[row["key"]] = row["value"]
        return result

    def set_key(self, key: str, value: str) -> None:
        """Alias for set() for backward compatibility."""
        self.set(key, value)

    def write_gpu_resources(self, data: dict[str, Any]) -> None:
        """Write GPU resource snapshot atomically.

        The snapshot contains only resource facts (gpu_available, error_summary).
        No timestamps - monitor liveness is tracked by HealthMonitorService.
        """
        self.set_key(key="gpu_resources", value=json.dumps(data))
