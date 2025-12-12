"""File tags operations for file-to-tag associations (join table)."""

import json
import sqlite3
from typing import Any


class FileTagOperations:
    """Operations for the file_tags table (many-to-many file<->tag associations)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def set_file_tags(
        self,
        file_id: int,
        tags: dict[str, Any],
        is_nomarr_tag: bool = False,
    ) -> None:
        """
        Replace all tags for a file (of the specified type).

        Args:
            file_id: Library file ID
            tags: Dict of tag_key -> tag_value
            is_nomarr_tag: True for Nomarr tags, False for external tags
        """
        # Import here to avoid circular dependency
        from nomarr.persistence.database.library_tags_sql import LibraryTagOperations

        library_tags = LibraryTagOperations(self.conn)

        # Delete existing tags of this type for this file
        self.conn.execute(
            """
            DELETE FROM file_tags
            WHERE file_id = ?
            AND tag_id IN (
                SELECT id FROM library_tags WHERE is_nomarr_tag = ?
            )
            """,
            (file_id, 1 if is_nomarr_tag else 0),
        )

        # Get or create tag definitions and associate with file
        for key, value in tags.items():
            tag_id = library_tags.get_or_create_tag(key, value, is_nomarr_tag)
            self.conn.execute(
                "INSERT OR IGNORE INTO file_tags (file_id, tag_id) VALUES (?, ?)",
                (file_id, tag_id),
            )

        self.conn.commit()

    def set_file_tags_mixed(
        self,
        file_id: int,
        external_tags: dict[str, Any],
        nomarr_tags: dict[str, Any],
    ) -> None:
        """
        Replace all tags for a file with both external and Nomarr tags.

        Args:
            file_id: Library file ID
            external_tags: External metadata tags
            nomarr_tags: Nomarr-generated tags
        """
        # Delete ALL existing tags for this file
        self.conn.execute("DELETE FROM file_tags WHERE file_id = ?", (file_id,))

        # Import here to avoid circular dependency
        from nomarr.persistence.database.library_tags_sql import LibraryTagOperations

        library_tags = LibraryTagOperations(self.conn)

        # Add external tags
        for key, value in external_tags.items():
            tag_id = library_tags.get_or_create_tag(key, value, is_nomarr_tag=False)
            self.conn.execute(
                "INSERT OR IGNORE INTO file_tags (file_id, tag_id) VALUES (?, ?)",
                (file_id, tag_id),
            )

        # Add Nomarr tags
        for key, value in nomarr_tags.items():
            tag_id = library_tags.get_or_create_tag(key, value, is_nomarr_tag=True)
            self.conn.execute(
                "INSERT OR IGNORE INTO file_tags (file_id, tag_id) VALUES (?, ?)",
                (file_id, tag_id),
            )

        self.conn.commit()

    def get_file_tags(self, file_id: int, nomarr_only: bool = False) -> dict[str, Any]:
        """
        Get all tags for a file.

        Args:
            file_id: Library file ID
            nomarr_only: If True, only return Nomarr-generated tags

        Returns:
            Dict of tag_key -> tag_value
        """
        if nomarr_only:
            cursor = self.conn.execute(
                """
                SELECT lt.key, lt.value
                FROM file_tags ft
                JOIN library_tags lt ON lt.id = ft.tag_id
                WHERE ft.file_id = ? AND lt.is_nomarr_tag = 1
                """,
                (file_id,),
            )
        else:
            cursor = self.conn.execute(
                """
                SELECT lt.key, lt.value
                FROM file_tags ft
                JOIN library_tags lt ON lt.id = ft.tag_id
                WHERE ft.file_id = ?
                """,
                (file_id,),
            )

        # Import here to avoid circular dependency
        from nomarr.persistence.database.library_tags_sql import LibraryTagOperations

        library_tags = LibraryTagOperations(self.conn)

        tags = {}
        for key, value_str in cursor.fetchall():
            tags[key] = library_tags._deserialize_value(value_str)

        return tags

    def get_file_tags_with_metadata(self, file_id: int, nomarr_only: bool = False) -> list[dict[str, Any]]:
        """
        Get all tags for a file with full metadata (key, value, type, is_nomarr_tag).

        Args:
            file_id: Library file ID
            nomarr_only: If True, only return Nomarr-generated tags

        Returns:
            List of dicts with keys: 'key', 'value', 'type', 'is_nomarr_tag'
        """
        if nomarr_only:
            cursor = self.conn.execute(
                """
                SELECT lt.key, lt.value, lt.is_nomarr_tag
                FROM file_tags ft
                JOIN library_tags lt ON lt.id = ft.tag_id
                WHERE ft.file_id = ? AND lt.is_nomarr_tag = 1
                """,
                (file_id,),
            )
        else:
            cursor = self.conn.execute(
                """
                SELECT lt.key, lt.value, lt.is_nomarr_tag
                FROM file_tags ft
                JOIN library_tags lt ON lt.id = ft.tag_id
                WHERE ft.file_id = ?
                """,
                (file_id,),
            )

        # Import here to avoid circular dependency
        from nomarr.persistence.database.library_tags_sql import LibraryTagOperations

        library_tags = LibraryTagOperations(self.conn)

        tags = []
        for key, value_str, is_nomarr_tag in cursor.fetchall():
            tags.append(
                {
                    "key": key,
                    "value": library_tags._deserialize_value(value_str),
                    "is_nomarr_tag": bool(is_nomarr_tag),
                }
            )

        return tags

    def get_file_tags_by_key(self, file_id: int, key: str) -> dict[str, Any]:
        """
        Get all tags for a file matching a specific key.

        Args:
            file_id: Library file ID
            key: Tag key to filter by (e.g., 'mood-strict', 'genre')

        Returns:
            Dict with single key -> value (or empty dict if not found)
        """
        cursor = self.conn.execute(
            """
            SELECT lt.key, lt.value
            FROM file_tags ft
            JOIN library_tags lt ON lt.id = ft.tag_id
            WHERE ft.file_id = ? AND lt.key = ?
            """,
            (file_id, key),
        )

        # Import here to avoid circular dependency
        from nomarr.persistence.database.library_tags_sql import LibraryTagOperations

        library_tags = LibraryTagOperations(self.conn)

        tags = {}
        for key, value_str in cursor.fetchall():
            tags[key] = library_tags._deserialize_value(value_str)

        return tags

    def get_file_tags_by_prefix(self, file_id: int, prefix: str) -> dict[str, Any]:
        """
        Get all tags for a file where key starts with a prefix.
        NOTE: In new schema, prefix filtering is deprecated. Use nomarr_only flag instead.
        This method is kept for backward compatibility.

        Args:
            file_id: Library file ID
            prefix: Key prefix (deprecated - ignored in favor of is_nomarr_tag filtering)

        Returns:
            Dict of tag_key -> tag_value (Nomarr tags only)
        """
        # In the new schema, we filter by is_nomarr_tag instead of prefix
        # This maintains backward compatibility for code expecting namespace-prefixed keys
        return self.get_file_tags(file_id, nomarr_only=True)

    def get_tag_ids_for_file(self, file_id: int) -> list[int]:
        """
        Get all tag IDs associated with a file.

        Args:
            file_id: Library file ID

        Returns:
            List of tag IDs
        """
        cursor = self.conn.execute(
            "SELECT tag_id FROM file_tags WHERE file_id = ?",
            (file_id,),
        )
        return [row[0] for row in cursor.fetchall()]

    def get_files_with_tag(self, tag_id: int) -> list[int]:
        """
        Get all file IDs that have this tag.

        Args:
            tag_id: Tag ID from library_tags

        Returns:
            List of file IDs
        """
        cursor = self.conn.execute(
            "SELECT file_id FROM file_tags WHERE tag_id = ?",
            (tag_id,),
        )
        return [row[0] for row in cursor.fetchall()]

    def delete_file_tags(self, file_id: int) -> None:
        """
        Delete all tag associations for a file.
        (Usually handled automatically by ON DELETE CASCADE)

        Args:
            file_id: Library file ID
        """
        self.conn.execute("DELETE FROM file_tags WHERE file_id = ?", (file_id,))
        self.conn.commit()

    # Legacy method names for backward compatibility during migration
    def upsert_file_tags(self, file_id: int, tags: dict[str, Any], is_nomarr_tag: bool = False) -> None:
        """Deprecated: Use set_file_tags instead."""
        self.set_file_tags(file_id, tags, is_nomarr_tag)

    def upsert_file_tags_mixed(
        self,
        file_id: int,
        external_tags: dict[str, Any],
        nomarr_tags: dict[str, Any],
    ) -> None:
        """Deprecated: Use set_file_tags_mixed instead."""
        self.set_file_tags_mixed(file_id, external_tags, nomarr_tags)

    def get_unique_tag_keys(self, nomarr_only: bool = False) -> list[str]:
        """
        Get list of all unique tag keys.

        Args:
            nomarr_only: If True, only return Nomarr tag keys

        Returns:
            List of unique tag keys
        """
        if nomarr_only:
            cursor = self.conn.execute(
                """
                SELECT DISTINCT lt.key
                FROM library_tags lt
                WHERE lt.is_nomarr_tag = 1
                ORDER BY lt.key
                """
            )
        else:
            cursor = self.conn.execute(
                """
                SELECT DISTINCT lt.key
                FROM library_tags lt
                ORDER BY lt.key
                """
            )
        return [row[0] for row in cursor.fetchall()]

    def get_unique_tag_values(self, tag_key: str, nomarr_only: bool = False) -> list[str]:
        """
        Get list of unique values for a specific tag key.

        Args:
            tag_key: Tag key to get values for
            nomarr_only: If True, only return values from Nomarr tags

        Returns:
            List of unique tag values as strings
        """
        if nomarr_only:
            cursor = self.conn.execute(
                """
                SELECT DISTINCT lt.value
                FROM library_tags lt
                WHERE lt.key = ? AND lt.is_nomarr_tag = 1
                ORDER BY lt.value
                """,
                (tag_key,),
            )
        else:
            cursor = self.conn.execute(
                """
                SELECT DISTINCT lt.value
                FROM library_tags lt
                WHERE lt.key = ?
                ORDER BY lt.value
                """,
                (tag_key,),
            )
        return [row[0] for row in cursor.fetchall()]

    def get_tag_summary(self, tag_key: str) -> dict[str, Any]:
        """
        Get summary statistics for a specific tag key.

        Args:
            tag_key: Tag key to summarize

        Returns:
            Dict with 'key', 'total_files', and 'unique_values' count
        """
        # Count files using this tag key
        cursor = self.conn.execute(
            """
            SELECT COUNT(DISTINCT ft.file_id)
            FROM file_tags ft
            JOIN library_tags lt ON lt.id = ft.tag_id
            WHERE lt.key = ?
            """,
            (tag_key,),
        )
        total_files = cursor.fetchone()[0] or 0

        # Count unique values
        cursor = self.conn.execute(
            """
            SELECT COUNT(DISTINCT lt.value)
            FROM library_tags lt
            WHERE lt.key = ?
            """,
            (tag_key,),
        )
        unique_values = cursor.fetchone()[0] or 0

        return {
            "key": tag_key,
            "total_files": int(total_files),
            "unique_values": int(unique_values),
        }

    def get_tag_type_stats(self, tag_key: str) -> dict[str, Any]:
        """
        Get usage statistics for a specific tag key.

        Since all values are now stored as JSON arrays, we infer the type
        by checking if arrays are multi-valued or single-valued.

        Args:
            tag_key: Tag key to analyze

        Returns:
            Dict with 'key', 'is_multivalue', 'total_files', 'sample_values'
        """
        # Count distinct files using this tag
        cursor = self.conn.execute(
            """
            SELECT COUNT(DISTINCT ft.file_id)
            FROM file_tags ft
            JOIN library_tags lt ON lt.id = ft.tag_id
            WHERE lt.key = ?
            """,
            (tag_key,),
        )
        row = cursor.fetchone()
        total_files = int(row[0]) if row else 0

        if total_files == 0:
            return {
                "key": tag_key,
                "is_multivalue": False,
                "total_files": 0,
                "sample_values": [],
            }

        # Get sample values (first 5 unique arrays)
        cursor = self.conn.execute(
            """
            SELECT DISTINCT lt.value
            FROM library_tags lt
            WHERE lt.key = ?
            LIMIT 5
            """,
            (tag_key,),
        )
        sample_values = [row[0] for row in cursor.fetchall()]

        # Infer if multi-value by checking if any array has > 1 element
        is_multivalue = False
        for val_str in sample_values:
            try:
                arr = json.loads(val_str)
                if isinstance(arr, list) and len(arr) > 1:
                    is_multivalue = True
                    break
            except json.JSONDecodeError:
                pass

        return {
            "key": tag_key,
            "is_multivalue": is_multivalue,
            "total_files": total_files,
            "sample_values": sample_values,
        }
