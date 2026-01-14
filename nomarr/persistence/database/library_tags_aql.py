"""Library tags operations for ArangoDB.

CRITICAL: All mutations by _id must use PARSE_IDENTIFIER(@id).key
to extract the document key for UPDATE/REMOVE operations.
"""

import json
from typing import Any, cast

from arango.cursor import Cursor
from arango.database import StandardDatabase


class LibraryTagOperations:
    """Operations for the library_tags collection (unique tag definitions)."""

    def __init__(self, db: StandardDatabase) -> None:
        self.db = db
        self.collection = db.collection("library_tags")

    def get_or_create_tag(self, key: str, value: Any, is_nomarr_tag: bool = False) -> str:
        """Get or create a tag definition and return its _id.

        All values are stored as JSON arrays for consistency.
        Scalars are automatically wrapped: "foo" → ["foo"], 123 → [123]

        Args:
            key: Tag key (e.g., 'mood-strict', 'genre', 'year')
            value: Tag value (will be wrapped in array if not already a list)
            is_nomarr_tag: True if Nomarr-generated, False for external metadata

        Returns:
            Tag _id (e.g., "library_tags/12345")
        """
        # Wrap scalars in arrays for consistent storage
        if not isinstance(value, list):
            value = [value]

        # Serialize to JSON array
        value_str = json.dumps(value, ensure_ascii=False)

        # Try to get existing tag
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR tag IN library_tags
                FILTER tag.key == @key
                    AND tag.value == @value
                    AND tag.is_nomarr_tag == @is_nomarr_tag
                LIMIT 1
                RETURN tag._id
            """,
                bind_vars={"key": key, "value": value_str, "is_nomarr_tag": is_nomarr_tag},
            ),
        )
        result = list(cursor)

        if result:
            return str(result[0])

        # Create new tag
        insert_result = cast(
            dict[str, Any], self.collection.insert({"key": key, "value": value_str, "is_nomarr_tag": is_nomarr_tag})
        )

        return str(insert_result["_id"])

    def get_tag_by_id(self, tag_id: str) -> dict[str, Any] | None:
        """Get tag details by _id.

        Args:
            tag_id: Document _id (e.g., "library_tags/12345")

        Returns:
            Dict with '_id', 'key', 'value', 'is_nomarr_tag' or None
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            RETURN DOCUMENT(@tag_id)
            """,
                bind_vars={"tag_id": tag_id},
            ),
        )
        tag: dict[str, Any] | None = next(cursor, None)

        if not tag:
            return None

        # Deserialize value from JSON
        tag["value"] = self._deserialize_value(tag["value"])
        return tag

    def get_tags_by_ids(self, tag_ids: list[str]) -> list[dict[str, Any]]:
        """Get multiple tag details by _ids (bulk operation).

        Args:
            tag_ids: List of document _ids

        Returns:
            List of dicts with '_id', 'key', 'value', 'is_nomarr_tag'
        """
        if not tag_ids:
            return []

        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR tag_id IN @tag_ids
                LET tag = DOCUMENT(tag_id)
                FILTER tag != null
                RETURN tag
            """,
                bind_vars={"tag_ids": tag_ids},
            ),
        )

        results = []
        for tag in cursor:
            tag["value"] = self._deserialize_value(tag["value"])
            results.append(tag)

        return results

    def cleanup_orphaned_tags(self) -> int:
        """Delete tags that are no longer referenced by any file.

        Returns:
            Number of tags deleted
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR tag IN library_tags
                LET has_refs = (
                    FOR edge IN file_tags
                        FILTER edge._to == tag._id
                        LIMIT 1
                        RETURN 1
                )
                FILTER LENGTH(has_refs) == 0
                REMOVE tag IN library_tags
                RETURN 1
            """
            ),
        )
        return len(list(cursor))

    def get_orphaned_tag_count(self) -> int:
        """Count tags not referenced by any file.

        Returns:
            Number of orphaned tags
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR tag IN library_tags
                LET has_refs = (
                    FOR edge IN file_tags
                        FILTER edge._to == tag._id
                        LIMIT 1
                        RETURN 1
                )
                FILTER LENGTH(has_refs) == 0
                COLLECT WITH COUNT INTO total
                RETURN total
            """
            ),
        )
        return next(cursor, 0)

    def get_all_tags(self) -> list[dict[str, Any]]:
        """Get all tags in the library.

        Returns:
            List of all tag dicts
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR tag IN library_tags
                RETURN tag
            """
            ),
        )
        results = []
        for tag in cursor:
            tag["value"] = self._deserialize_value(tag["value"])
            results.append(tag)
        return results

    def _deserialize_value(self, value_str: str) -> Any:
        """Deserialize JSON value string.

        Args:
            value_str: JSON array string

        Returns:
            Deserialized value (list or scalar)
        """
        try:
            value = json.loads(value_str)
            # Unwrap single-element arrays
            if isinstance(value, list) and len(value) == 1:
                return value[0]
            return value
        except Exception:
            return value_str
