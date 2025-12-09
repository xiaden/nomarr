"""Library tags operations for normalized unique tag storage."""

import json
import sqlite3
from typing import Any


class LibraryTagOperations:
    """Operations for the library_tags table (unique tag definitions)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_or_create_tag(self, key: str, value: Any, is_nomarr_tag: bool = False) -> int:
        """
        Get or create a tag definition and return its ID.

        Args:
            key: Tag key (e.g., 'mood-strict', 'genre', 'year')
            value: Tag value (will be serialized based on type)
            is_nomarr_tag: True if Nomarr-generated, False for external metadata

        Returns:
            Tag ID from library_tags table
        """
        # Detect type and serialize value
        if isinstance(value, list):
            tag_type = "array"
            value_str = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, float):
            tag_type = "float"
            value_str = str(value)
        elif isinstance(value, int):
            tag_type = "int"
            value_str = str(value)
        else:
            tag_type = "string"
            value_str = str(value)

        # Try to get existing tag
        cursor = self.conn.execute(
            """
            SELECT id FROM library_tags
            WHERE key = ? AND value = ? AND is_nomarr_tag = ?
            """,
            (key, value_str, 1 if is_nomarr_tag else 0),
        )
        row = cursor.fetchone()

        if row:
            return int(row[0])

        # Create new tag
        cursor = self.conn.execute(
            """
            INSERT INTO library_tags (key, value, type, is_nomarr_tag)
            VALUES (?, ?, ?, ?)
            """,
            (key, value_str, tag_type, 1 if is_nomarr_tag else 0),
        )
        self.conn.commit()
        tag_id = cursor.lastrowid
        if tag_id is None:
            raise RuntimeError(f"Failed to create tag: key={key}, value={value_str}")
        return tag_id

    def get_tag_by_id(self, tag_id: int) -> dict[str, Any] | None:
        """
        Get tag details by ID.

        Returns:
            Dict with 'id', 'key', 'value', 'type', 'is_nomarr_tag' or None
        """
        cursor = self.conn.execute(
            "SELECT id, key, value, type, is_nomarr_tag FROM library_tags WHERE id = ?",
            (tag_id,),
        )
        row = cursor.fetchone()

        if not row:
            return None

        # Deserialize value based on type
        tag_id, key, value_str, tag_type, is_nomarr_tag = row
        value = self._deserialize_value(value_str, tag_type)

        return {
            "id": tag_id,
            "key": key,
            "value": value,
            "type": tag_type,
            "is_nomarr_tag": bool(is_nomarr_tag),
        }

    def get_tags_by_ids(self, tag_ids: list[int]) -> list[dict[str, Any]]:
        """
        Get multiple tag details by IDs (bulk operation).

        Returns:
            List of dicts with 'id', 'key', 'value', 'type', 'is_nomarr_tag'
        """
        if not tag_ids:
            return []

        placeholders = ",".join("?" * len(tag_ids))
        cursor = self.conn.execute(
            f"""
            SELECT id, key, value, type, is_nomarr_tag
            FROM library_tags
            WHERE id IN ({placeholders})
            """,
            tag_ids,
        )

        results = []
        for row in cursor.fetchall():
            tag_id, key, value_str, tag_type, is_nomarr_tag = row
            value = self._deserialize_value(value_str, tag_type)
            results.append(
                {
                    "id": tag_id,
                    "key": key,
                    "value": value,
                    "type": tag_type,
                    "is_nomarr_tag": bool(is_nomarr_tag),
                }
            )

        return results

    def cleanup_orphaned_tags(self) -> int:
        """
        Delete tags that are no longer referenced by any file.

        Returns:
            Number of tags deleted
        """
        cursor = self.conn.execute(
            """
            DELETE FROM library_tags
            WHERE id NOT IN (SELECT DISTINCT tag_id FROM file_tags)
            """
        )
        self.conn.commit()
        return cursor.rowcount

    def get_orphaned_tag_count(self) -> int:
        """
        Count tags in library_tags that are not referenced by any file.

        Returns:
            Number of orphaned tags
        """
        cursor = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM library_tags
            WHERE id NOT IN (SELECT DISTINCT tag_id FROM file_tags)
            """
        )
        result = cursor.fetchone()
        return int(result[0]) if result else 0

    def get_tag_usage_count(self, tag_id: int) -> int:
        """
        Get number of files using this tag.

        Args:
            tag_id: Tag ID from library_tags

        Returns:
            Count of files with this tag
        """
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM file_tags WHERE tag_id = ?",
            (tag_id,),
        )
        result = cursor.fetchone()
        return int(result[0]) if result else 0

    def _deserialize_value(self, value_str: str, tag_type: str) -> Any:
        """Deserialize value based on type."""
        if tag_type == "array":
            try:
                return json.loads(value_str)
            except json.JSONDecodeError:
                return []
        elif tag_type == "float":
            try:
                return float(value_str)
            except ValueError:
                return 0.0
        elif tag_type == "int":
            try:
                return int(value_str)
            except ValueError:
                return 0
        else:
            return value_str
