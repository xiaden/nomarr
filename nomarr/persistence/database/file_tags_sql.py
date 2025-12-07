"""File tags operations for normalized tag storage."""

import json
import sqlite3
from typing import Any


class FileTagOperations:
    """Operations for the file_tags table (normalized tag storage)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert_file_tags(self, file_id: int, tags: dict[str, Any], is_nomarr_tag: bool = False) -> None:
        """
        Replace all tags for a file with new tags.
        Deletes existing tags and inserts new ones.

        Args:
            file_id: Library file ID
            tags: Dict of tag_key -> tag_value
            is_nomarr_tag: True if these are Nomarr-generated tags, False for external tags
        """
        # Delete existing tags for this file
        self.conn.execute("DELETE FROM file_tags WHERE file_id=?", (file_id,))

        # Insert new tags
        for tag_key, tag_value in tags.items():
            # Detect tag type
            if isinstance(tag_value, list):
                tag_type = "array"
                # Store arrays as JSON
                tag_value_str = json.dumps(tag_value, ensure_ascii=False)
            elif isinstance(tag_value, float):
                tag_type = "float"
                tag_value_str = str(tag_value)
            elif isinstance(tag_value, int):
                tag_type = "int"
                tag_value_str = str(tag_value)
            else:
                tag_type = "string"
                tag_value_str = str(tag_value)

            self.conn.execute(
                """
                INSERT INTO file_tags (file_id, tag_key, tag_value, tag_type, is_nomarr_tag)
                VALUES (?, ?, ?, ?, ?)
                """,
                (file_id, tag_key, tag_value_str, tag_type, 1 if is_nomarr_tag else 0),
            )

        self.conn.commit()

    def upsert_file_tags_mixed(
        self,
        file_id: int,
        external_tags: dict[str, Any],
        nomarr_tags: dict[str, Any],
    ) -> None:
        """
        Replace all tags for a file with a mix of external and Nomarr tags.
        Deletes existing tags and inserts new ones with appropriate flags.

        Args:
            file_id: Library file ID
            external_tags: Dict of tag_key -> tag_value for external tags (is_nomarr_tag=False)
            nomarr_tags: Dict of tag_key -> tag_value for Nomarr tags (is_nomarr_tag=True)
        """
        # Delete existing tags for this file
        self.conn.execute("DELETE FROM file_tags WHERE file_id=?", (file_id,))

        # Insert external tags
        for tag_key, tag_value in external_tags.items():
            tag_type, tag_value_str = self._detect_tag_type_and_serialize(tag_value)
            self.conn.execute(
                "INSERT INTO file_tags (file_id, tag_key, tag_value, tag_type, is_nomarr_tag) VALUES (?, ?, ?, ?, ?)",
                (file_id, tag_key, tag_value_str, tag_type, 0),
            )

        # Insert Nomarr tags
        for tag_key, tag_value in nomarr_tags.items():
            tag_type, tag_value_str = self._detect_tag_type_and_serialize(tag_value)
            self.conn.execute(
                "INSERT INTO file_tags (file_id, tag_key, tag_value, tag_type, is_nomarr_tag) VALUES (?, ?, ?, ?, ?)",
                (file_id, tag_key, tag_value_str, tag_type, 1),
            )

        self.conn.commit()

    def _detect_tag_type_and_serialize(self, tag_value: Any) -> tuple[str, str]:
        """Helper to detect tag type and serialize value."""
        if isinstance(tag_value, list):
            return "array", json.dumps(tag_value, ensure_ascii=False)
        elif isinstance(tag_value, float):
            return "float", str(tag_value)
        elif isinstance(tag_value, int):
            return "int", str(tag_value)
        else:
            return "string", str(tag_value)

    def get_unique_tag_keys(self, nomarr_only: bool = False) -> list[str]:
        """
        Get all unique tag keys across the library.

        Args:
            nomarr_only: If True, only return Nomarr-generated tags
        """
        if nomarr_only:
            cursor = self.conn.execute("SELECT DISTINCT tag_key FROM file_tags WHERE is_nomarr_tag=1 ORDER BY tag_key")
        else:
            cursor = self.conn.execute("SELECT DISTINCT tag_key FROM file_tags ORDER BY tag_key")
        return [row[0] for row in cursor.fetchall()]

    def get_tag_values(self, tag_key: str, limit: int = 1000) -> list[tuple[str, str]]:
        """
        Get all values for a specific tag key.

        Returns:
            List of (tag_value, tag_type) tuples
        """
        cursor = self.conn.execute(
            "SELECT tag_value, tag_type FROM file_tags WHERE tag_key=? LIMIT ?", (tag_key, limit)
        )
        return cursor.fetchall()

    def get_unique_tag_values(self, tag_key: str, nomarr_only: bool = False) -> list[str]:
        """
        Get distinct values for a specific tag key.

        Args:
            tag_key: The tag key to get values for
            nomarr_only: If True, only return values from Nomarr-generated tags

        Returns:
            List of distinct tag values
        """
        if nomarr_only:
            cursor = self.conn.execute(
                "SELECT DISTINCT tag_value FROM file_tags WHERE tag_key = ? AND is_nomarr_tag = 1 ORDER BY tag_value",
                (tag_key,),
            )
        else:
            cursor = self.conn.execute(
                "SELECT DISTINCT tag_value FROM file_tags WHERE tag_key = ? ORDER BY tag_value",
                (tag_key,),
            )
        return [row[0] for row in cursor.fetchall()]

    def get_file_tags(self, file_id: int, nomarr_only: bool = False) -> dict[str, Any]:
        """
        Get all tags for a specific file.

        Args:
            file_id: Library file ID
            nomarr_only: If True, only return Nomarr-generated tags

        Returns:
            Dict of tag_key -> tag_value (with arrays parsed from JSON)
        """
        if nomarr_only:
            cursor = self.conn.execute(
                "SELECT tag_key, tag_value, tag_type FROM file_tags WHERE file_id=? AND is_nomarr_tag=1",
                (file_id,),
            )
        else:
            cursor = self.conn.execute("SELECT tag_key, tag_value, tag_type FROM file_tags WHERE file_id=?", (file_id,))

        tags = {}
        for tag_key, tag_value, tag_type in cursor.fetchall():
            if tag_type == "array":
                try:
                    tags[tag_key] = json.loads(tag_value)
                except json.JSONDecodeError:
                    tags[tag_key] = tag_value
            elif tag_type == "float":
                tags[tag_key] = float(tag_value)
            elif tag_type == "int":
                tags[tag_key] = int(tag_value)
            else:
                tags[tag_key] = tag_value

        return tags

    def get_file_tags_by_prefix(self, file_id: int, prefix: str) -> dict[str, Any]:
        """
        Get all tags for a specific file matching a key prefix (e.g., namespace).

        Args:
            file_id: Library file ID
            prefix: Key prefix to filter by (e.g., 'essentia:')

        Returns:
            Dict of tag_key -> tag_value (with arrays parsed from JSON)
        """
        cursor = self.conn.execute(
            "SELECT tag_key, tag_value, tag_type FROM file_tags WHERE file_id=? AND tag_key LIKE ?",
            (file_id, f"{prefix}%"),
        )

        tags = {}
        for tag_key, tag_value, tag_type in cursor.fetchall():
            if tag_type == "array":
                try:
                    tags[tag_key] = json.loads(tag_value)
                except json.JSONDecodeError:
                    tags[tag_key] = tag_value
            elif tag_type == "float":
                tags[tag_key] = float(tag_value)
            elif tag_type == "int":
                tags[tag_key] = int(tag_value)
            else:
                tags[tag_key] = tag_value

        return tags

    def get_tag_type_stats(self, tag_key: str) -> dict[str, Any]:
        """
        Get statistics about a tag's type usage.

        Returns:
            Dict with: is_multivalue (bool), sample_values (list), total_count (int)
        """
        cursor = self.conn.execute("SELECT tag_value, tag_type FROM file_tags WHERE tag_key=? LIMIT 100", (tag_key,))

        rows = cursor.fetchall()
        if not rows:
            return {"is_multivalue": False, "sample_values": [], "total_count": 0}

        types = {row[1] for row in rows}
        is_multivalue = "array" in types
        sample_values = [row[0] for row in rows[:10]]

        # Get total count
        count_cursor = self.conn.execute("SELECT COUNT(*) FROM file_tags WHERE tag_key=?", (tag_key,))
        total_count = count_cursor.fetchone()[0]

        return {"is_multivalue": is_multivalue, "sample_values": sample_values, "total_count": total_count}

    def get_tag_summary(self, tag_key: str) -> dict[str, Any]:
        """
        Get a useful summary of tag values (for Navidrome preview).

        For string tags: returns all unique values with counts (case-insensitive grouping)
        For float/int tags: returns min, max, average
        For array tags: flattens all values and returns unique values with counts

        Returns:
            Dict with: type, is_multivalue, summary (str or dict), total_count (int)
        """
        # Get total count and detect type from sample
        count_cursor = self.conn.execute("SELECT COUNT(*) FROM file_tags WHERE tag_key=?", (tag_key,))
        total_count = count_cursor.fetchone()[0]

        if total_count == 0:
            return {"type": "string", "is_multivalue": False, "summary": "No data", "total_count": 0}

        # Detect type from sample
        type_cursor = self.conn.execute("SELECT DISTINCT tag_type FROM file_tags WHERE tag_key=? LIMIT 10", (tag_key,))
        types = {row[0] for row in type_cursor}
        is_multivalue = "array" in types
        detected_type = "float" if "float" in types else "int" if "int" in types else "string"

        # Generate summary based on type (using efficient SQL queries)
        if is_multivalue:
            # For arrays (mood tags), fetch and parse JSON to count individual values
            cursor = self.conn.execute("SELECT tag_value FROM file_tags WHERE tag_key=? LIMIT 10000", (tag_key,))
            value_counts: dict[str, int] = {}

            for row in cursor:
                try:
                    # Parse JSON array - decode bytes to string first
                    raw_value = row[0]
                    if isinstance(raw_value, bytes):
                        raw_value = raw_value.decode("utf-8")
                    values = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
                    if isinstance(values, list):
                        for val in values:
                            # Count individual mood values (not combinations)
                            val_str = str(val).strip()
                            value_counts[val_str] = value_counts.get(val_str, 0) + 1
                except (json.JSONDecodeError, TypeError):
                    continue

            # Sort by count descending
            sorted_values = sorted(value_counts.items(), key=lambda x: x[1], reverse=True)
            summary: dict[str, Any] | str = dict(sorted_values)

        elif detected_type in ("float", "int"):
            # Use SQL aggregation for numeric tags (much faster!)
            cursor = self.conn.execute(
                """
                SELECT
                    MIN(CAST(tag_value AS REAL)) as min_val,
                    MAX(CAST(tag_value AS REAL)) as max_val,
                    AVG(CAST(tag_value AS REAL)) as avg_val
                FROM file_tags
                WHERE tag_key=?
                """,
                (tag_key,),
            )
            row = cursor.fetchone()
            if row and row[0] is not None:
                summary = {"min": row[0], "max": row[1], "avg": row[2]}
            else:
                summary = "No valid numeric values"

        else:
            # String tags: use SQL GROUP BY with case-insensitive grouping
            # Also handle mood tags stored as delimited strings (legacy format)
            cursor = self.conn.execute(
                """
                SELECT tag_value, COUNT(*) as count
                FROM file_tags
                WHERE tag_key=?
                GROUP BY tag_value COLLATE NOCASE
                ORDER BY count DESC
                """,
                (tag_key,),
            )

            # Check if this might be a delimited mood tag
            first_value = None
            all_rows = []
            for row in cursor:
                all_rows.append(row)
                if first_value is None:
                    first_value = row[0]

            # If values contain "/" separators, it's a mood tag stored as delimited string
            if first_value and ("/" in str(first_value) or ";" in str(first_value)):
                # Parse delimited mood values and count individual moods
                value_counts = {}
                for tag_value, count in all_rows:
                    try:
                        # Split on common delimiters
                        if "/" in str(tag_value):
                            moods = str(tag_value).split("/")
                        elif ";" in str(tag_value):
                            moods = str(tag_value).split(";")
                        else:
                            moods = [str(tag_value)]

                        for mood in moods:
                            mood = mood.strip()
                            if mood:
                                value_counts[mood] = value_counts.get(mood, 0) + count
                    except Exception:
                        continue

                # Sort by count descending
                sorted_values = sorted(value_counts.items(), key=lambda x: x[1], reverse=True)
                summary = dict(sorted_values)
            else:
                # Regular string tag - just use the grouped counts
                summary = {row[0].lower(): row[1] for row in all_rows}

        return {"type": detected_type, "is_multivalue": is_multivalue, "summary": summary, "total_count": total_count}
