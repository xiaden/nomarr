"""File tags operations for ArangoDB (edge collection).

file_tags is an EDGE collection connecting library_files → library_tags.
All operations use graph semantics (_from, _to).
"""

from typing import Any, cast

from arango.cursor import Cursor
from arango.database import StandardDatabase


class FileTagOperations:
    """Operations for the file_tags edge collection (file→tag associations)."""

    def __init__(self, db: StandardDatabase) -> None:
        self.db = db
        self.collection = db.collection("file_tags")

    def set_file_tags(
        self,
        file_id: str,
        tags: dict[str, Any],
        is_nomarr_tag: bool = False,
    ) -> None:
        """Replace all tags for a file (of the specified type).

        Args:
            file_id: File document _id (e.g., "library_files/12345")
            tags: Dict of tag_key -> tag_value
            is_nomarr_tag: True for Nomarr tags, False for external tags
        """
        # Import here to avoid circular dependency
        from nomarr.persistence.database.library_tags_aql import LibraryTagOperations

        library_tags = LibraryTagOperations(self.db)

        # Delete existing tags of this type for this file
        self.db.aql.execute(
            """
            FOR edge IN file_tags
                FILTER edge._from == @file_id
                LET tag = DOCUMENT(edge._to)
                FILTER tag.is_nomarr_tag == @is_nomarr_tag
                REMOVE edge IN file_tags
            """,
            bind_vars={"file_id": file_id, "is_nomarr_tag": is_nomarr_tag},
        )

        # Get or create tag definitions and associate with file
        for key, value in tags.items():
            tag_id = library_tags.get_or_create_tag(key, value, is_nomarr_tag)
            self.collection.insert(
                {"_from": file_id, "_to": tag_id}, silent=True
            )  # silent=True ignores duplicate edges

    def set_file_tags_mixed(
        self,
        file_id: str,
        external_tags: dict[str, Any],
        nomarr_tags: dict[str, Any],
    ) -> None:
        """Replace all tags for a file with both external and Nomarr tags.

        Args:
            file_id: File document _id (e.g., "library_files/12345")
            external_tags: External metadata tags
            nomarr_tags: Nomarr-generated tags
        """
        # Delete ALL existing tags for this file
        self.db.aql.execute(
            """
            FOR edge IN file_tags
                FILTER edge._from == @file_id
                REMOVE edge IN file_tags
            """,
            bind_vars={"file_id": file_id},
        )

        # Import here to avoid circular dependency
        from nomarr.persistence.database.library_tags_aql import LibraryTagOperations

        library_tags = LibraryTagOperations(self.db)

        # Add external tags
        for key, value in external_tags.items():
            tag_id = library_tags.get_or_create_tag(key, value, is_nomarr_tag=False)
            self.collection.insert({"_from": file_id, "_to": tag_id}, silent=True)

        # Add Nomarr tags
        for key, value in nomarr_tags.items():
            tag_id = library_tags.get_or_create_tag(key, value, is_nomarr_tag=True)
            self.collection.insert({"_from": file_id, "_to": tag_id}, silent=True)

    def get_file_tags(self, file_id: str, nomarr_only: bool = False) -> dict[str, Any]:
        """Get all tags for a file.

        Args:
            file_id: File document _id (e.g., "library_files/12345")
            nomarr_only: If True, only return Nomarr-generated tags

        Returns:
            Dict of tag_key -> tag_value
        """
        filter_clause = "FILTER tag.is_nomarr_tag == true" if nomarr_only else ""

        cursor = cast(
            Cursor,
            self.db.aql.execute(
                f"""
            FOR edge IN file_tags
                FILTER edge._from == @file_id
                LET tag = DOCUMENT(edge._to)
                {filter_clause}
                RETURN {{ key: tag.key, value: tag.value }}
            """,
                bind_vars={"file_id": file_id},
            ),
        )

        # Import here to avoid circular dependency
        from nomarr.persistence.database.library_tags_aql import LibraryTagOperations

        library_tags = LibraryTagOperations(self.db)

        tags = {}
        for item in cursor:
            tags[item["key"]] = library_tags._deserialize_value(item["value"])

        return tags

    def get_file_tags_with_metadata(self, file_id: str, nomarr_only: bool = False) -> list[dict[str, Any]]:
        """Get all tags for a file with full metadata.

        Args:
            file_id: File document _id (e.g., "library_files/12345")
            nomarr_only: If True, only return Nomarr-generated tags

        Returns:
            List of dicts with keys: 'key', 'value', 'is_nomarr_tag'
        """
        filter_clause = "FILTER tag.is_nomarr_tag == true" if nomarr_only else ""

        cursor = cast(
            Cursor,
            self.db.aql.execute(
                f"""
            FOR edge IN file_tags
                FILTER edge._from == @file_id
                LET tag = DOCUMENT(edge._to)
                {filter_clause}
                RETURN {{
                    key: tag.key,
                    value: tag.value,
                    is_nomarr_tag: tag.is_nomarr_tag
                }}
            """,
                bind_vars={"file_id": file_id},
            ),
        )

        # Import here to avoid circular dependency
        from nomarr.persistence.database.library_tags_aql import LibraryTagOperations

        library_tags = LibraryTagOperations(self.db)

        tags = []
        for item in cursor:
            tags.append(
                {
                    "key": item["key"],
                    "value": library_tags._deserialize_value(item["value"]),
                    "is_nomarr_tag": item["is_nomarr_tag"],
                }
            )

        return tags

    def get_file_tags_by_key(self, file_id: str, key: str) -> dict[str, Any]:
        """Get all tags for a file matching a specific key.

        Args:
            file_id: File document _id (e.g., "library_files/12345")
            key: Tag key to filter by (e.g., 'mood-strict', 'genre')

        Returns:
            Dict with single key -> value (or empty dict if not found)
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR edge IN file_tags
                FILTER edge._from == @file_id
                LET tag = DOCUMENT(edge._to)
                FILTER tag.key == @key
                RETURN { key: tag.key, value: tag.value }
            """,
                bind_vars={"file_id": file_id, "key": key},
            ),
        )

        # Import here to avoid circular dependency
        from nomarr.persistence.database.library_tags_aql import LibraryTagOperations

        library_tags = LibraryTagOperations(self.db)

        tags = {}
        for item in cursor:
            tags[item["key"]] = library_tags._deserialize_value(item["value"])

        return tags

    def get_file_tags_by_prefix(self, file_id: str, prefix: str) -> dict[str, Any]:
        """Get all tags for a file where key starts with a prefix.

        NOTE: In new schema, prefix filtering is deprecated. Use nomarr_only flag instead.
        This method is kept for backward compatibility.

        Args:
            file_id: File document _id
            prefix: Key prefix (deprecated - ignored in favor of is_nomarr_tag filtering)

        Returns:
            Dict of tag_key -> tag_value (Nomarr tags only)
        """
        # In the new schema, we filter by is_nomarr_tag instead of prefix
        return self.get_file_tags(file_id, nomarr_only=True)

    def get_tag_ids_for_file(self, file_id: str) -> list[str]:
        """Get all tag _ids associated with a file.

        Args:
            file_id: File document _id

        Returns:
            List of tag _ids
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR edge IN file_tags
                FILTER edge._from == @file_id
                RETURN edge._to
            """,
                bind_vars={"file_id": file_id},
            ),
        )
        return list(cursor)

    def get_files_with_tag(self, tag_id: str) -> list[str]:
        """Get all file _ids that have this tag.

        Args:
            tag_id: Tag document _id (e.g., "library_tags/12345")

        Returns:
            List of file _ids
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR edge IN file_tags
                FILTER edge._to == @tag_id
                RETURN edge._from
            """,
                bind_vars={"tag_id": tag_id},
            ),
        )
        return list(cursor)

    def delete_file_tags(self, file_id: str) -> None:
        """Delete all tag associations for a file.

        Args:
            file_id: File document _id
        """
        self.db.aql.execute(
            """
            FOR edge IN file_tags
                FILTER edge._from == @file_id
                REMOVE edge IN file_tags
            """,
            bind_vars={"file_id": file_id},
        )

    # Legacy method names for backward compatibility
    def upsert_file_tags(self, file_id: str, tags: dict[str, Any], is_nomarr_tag: bool = False) -> None:
        """Deprecated: Use set_file_tags instead."""
        self.set_file_tags(file_id, tags, is_nomarr_tag)

    def upsert_file_tags_mixed(
        self,
        file_id: str,
        external_tags: dict[str, Any],
        nomarr_tags: dict[str, Any],
    ) -> None:
        """Deprecated: Use set_file_tags_mixed instead."""
        self.set_file_tags_mixed(file_id, external_tags, nomarr_tags)

    def get_unique_tag_keys(self, nomarr_only: bool = False) -> list[str]:
        """Get list of all unique tag keys.

        Args:
            nomarr_only: If True, only return Nomarr tag keys

        Returns:
            List of unique tag keys
        """
        filter_clause = "FILTER tag.is_nomarr_tag == true" if nomarr_only else ""

        cursor = cast(
            Cursor,
            self.db.aql.execute(
                f"""
            FOR tag IN library_tags
                {filter_clause}
                RETURN DISTINCT tag.key
            """
            ),
        )
        return list(cursor)

    def get_tag_value_counts(self, key: str) -> dict[Any, int]:
        """Get value counts for a specific tag key.

        Args:
            key: Tag key to analyze

        Returns:
            Dict mapping tag value -> file count
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR tag IN library_tags
                FILTER tag.key == @key
                LET file_count = LENGTH(
                    FOR edge IN file_tags
                        FILTER edge._to == tag._id
                        RETURN 1
                )
                RETURN { value: tag.value, count: file_count }
            """,
                bind_vars={"key": key},
            ),
        )

        # Import here to avoid circular dependency
        from nomarr.persistence.database.library_tags_aql import LibraryTagOperations

        library_tags = LibraryTagOperations(self.db)

        counts = {}
        for item in cursor:
            value = library_tags._deserialize_value(item["value"])
            counts[value] = item["count"]

        return counts

    def get_tag_frequencies(self, limit: int, namespace_prefix: str) -> dict[str, Any]:
        """Get tag frequency data for analytics.

        Returns:
            Dict with keys: nom_tag_rows (list of tuples), genre_rows (list of tuples)
        """
        # Count Nomarr tag key:value combinations
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR ft IN file_tags
                FOR lt IN library_tags
                    FILTER ft.tag_id == lt._id AND lt.is_nomarr_tag == true
                    COLLECT tag_key_value = CONCAT(lt.key, ':', lt.value) WITH COUNT INTO tag_count
                    SORT tag_count DESC
                    LIMIT @limit
                    RETURN [tag_key_value, tag_count]
            """,
                bind_vars=cast(dict[str, Any], {"limit": limit}),
            ),
        )
        nom_tag_rows = [tuple(row) for row in cursor]

        # Count genre tags (non-Nomarr, key='genre')
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR ft IN file_tags
                FOR lt IN library_tags
                    FILTER ft.tag_id == lt._id AND lt.key == 'genre' AND lt.is_nomarr_tag == false
                    COLLECT genre = lt.value WITH COUNT INTO count
                    SORT count DESC
                    LIMIT @limit
                    RETURN [genre, count]
            """,
                bind_vars=cast(dict[str, Any], {"limit": limit}),
            ),
        )
        genre_rows = [tuple(row) for row in cursor]

        return {
            "nom_tag_rows": nom_tag_rows,
            "genre_rows": genre_rows,
        }

    def get_mood_and_tier_tags_for_correlation(self) -> dict[str, Any]:
        """Get mood and tier tag data for correlation analysis.

        Returns:
            Dict with keys: mood_tag_rows (list of tuples), tier_tag_keys (list), tier_tag_rows (dict)
        """
        # Get mood tags (mood-strict, mood-regular, mood-loose)
        mood_tag_keys = ["mood-strict", "mood-regular", "mood-loose"]
        mood_tag_rows = []

        for tag_key in mood_tag_keys:
            cursor = cast(
                Cursor,
                self.db.aql.execute(
                    """
                FOR ft IN file_tags
                    FOR lt IN library_tags
                        FILTER ft.tag_id == lt._id AND lt.key == @tag_key AND lt.is_nomarr_tag == true
                        RETURN [ft.file_id, lt.value]
                """,
                    bind_vars=cast(dict[str, Any], {"tag_key": tag_key}),
                ),
            )
            mood_tag_rows.extend([tuple(row) for row in cursor])

        # Get all *_tier tag keys
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR lt IN library_tags
                FILTER lt.is_nomarr_tag == true AND LIKE(lt.key, '%_tier')
                COLLECT tier_key = lt.key
                RETURN tier_key
            """,
            ),
        )
        tier_tag_keys = list(cursor)

        # Get tier tag data for each key
        tier_tag_rows = {}
        for tier_key in tier_tag_keys:
            cursor = cast(
                Cursor,
                self.db.aql.execute(
                    """
                FOR ft IN file_tags
                    FOR lt IN library_tags
                        FILTER ft.tag_id == lt._id AND lt.key == @tier_key
                        RETURN [ft.file_id, lt.value]
                """,
                    bind_vars=cast(dict[str, Any], {"tier_key": tier_key}),
                ),
            )
            tier_tag_rows[tier_key] = [tuple(row) for row in cursor]

        return {
            "mood_tag_rows": mood_tag_rows,
            "tier_tag_keys": tier_tag_keys,
            "tier_tag_rows": tier_tag_rows,
        }

    def get_mood_distribution_data(self) -> list[tuple[str, str]]:
        """Get mood tag distribution for analytics.

        Returns:
            List of (mood_type, tag_value) tuples
        """
        mood_rows = []
        for mood_type in ["mood-strict", "mood-regular", "mood-loose"]:
            cursor = cast(
                Cursor,
                self.db.aql.execute(
                    """
                FOR ft IN file_tags
                    FOR lt IN library_tags
                        FILTER ft.tag_id == lt._id AND lt.key == @mood_type AND lt.is_nomarr_tag == true
                        RETURN lt.value
                """,
                    bind_vars=cast(dict[str, Any], {"mood_type": mood_type}),
                ),
            )
            for tag_value in cursor:
                mood_rows.append((mood_type, tag_value))

        return mood_rows

    def get_file_ids_for_tags(self, tag_specs: list[tuple[str, str]]) -> dict[tuple[str, str], set[str]]:
        """Get file IDs for tag co-occurrence analysis.

        Args:
            tag_specs: List of (key, value) tuples

        Returns:
            Dict mapping (key, value) -> set of file_ids
        """
        result: dict[tuple[str, str], set[str]] = {}

        for key, value in tag_specs:
            cursor = cast(
                Cursor,
                self.db.aql.execute(
                    """
                FOR ft IN file_tags
                    FOR lt IN library_tags
                        FILTER ft.tag_id == lt._id AND lt.key == @key AND lt.value == @value
                        RETURN ft.file_id
                """,
                    bind_vars=cast(dict[str, Any], {"key": key, "value": value}),
                ),
            )
            result[(key, value)] = set(cursor)

        return result

    def get_file_ids_matching_tag(
        self,
        tag_key: str,
        operator: str,
        value: float | int | str,
    ) -> set[str]:
        """Get file IDs where a tag matches a condition.

        Args:
            tag_key: Tag key (e.g., "mood-strict")
            operator: Comparison operator (">", "<", ">=", "<=", "=", "!=")
            value: Value to compare against

        Returns:
            Set of file _ids matching the condition
        """
        # Map operators to AQL syntax
        operator_map = {
            ">": ">",
            "<": "<",
            ">=": ">=",
            "<=": "<=",
            "=": "==",
            "!=": "!=",
        }

        if operator not in operator_map:
            raise ValueError(f"Invalid operator: {operator}")

        aql_operator = operator_map[operator]

        cursor = cast(
            Cursor,
            self.db.aql.execute(
                f"""
            FOR ft IN file_tags
                FOR lt IN library_tags
                    FILTER ft.tag_id == lt._id 
                    AND lt.key == @tag_key 
                    AND TO_NUMBER(lt.value) {aql_operator} @value
                    RETURN DISTINCT ft.file_id
            """,
                bind_vars=cast(dict[str, Any], {"tag_key": tag_key, "value": value}),
            ),
        )
        return set(cursor)

    def get_file_ids_containing_tag(self, tag_key: str, substring: str) -> set[str]:
        """Get file IDs where a tag value contains a substring (case-insensitive).

        Args:
            tag_key: Tag key
            substring: Substring to search for

        Returns:
            Set of file_ids where tag value contains substring
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR ft IN file_tags
                FOR lt IN library_tags
                    FILTER ft.tag_id == lt._id 
                        AND lt.key == @tag_key
                        AND LIKE(LOWER(lt.value), LOWER(@pattern), true)
                    RETURN DISTINCT ft.file_id
            """,
                bind_vars=cast(
                    dict[str, Any],
                    {
                        "tag_key": tag_key,
                        "pattern": f"%{substring}%",
                    },
                ),
            ),
        )
        return set(cursor)

    def get_tag_summary(self, library_id: str | None = None) -> dict[str, Any]:
        """Get summary of tags in library.

        Returns dict with total_files, total_tags, tags_by_type, etc.
        """
        # Get total files and tagged files count
        if library_id:
            file_cursor = cast(
                Cursor,
                self.db.aql.execute(
                    """
                FOR file IN library_files
                    FILTER file.library_id == @library_id
                    COLLECT tagged = file.tagged WITH COUNT INTO count
                    RETURN {tagged: tagged, count: count}
                """,
                    bind_vars=cast(dict[str, Any], {"library_id": library_id}),
                ),
            )
        else:
            file_cursor = cast(
                Cursor,
                self.db.aql.execute(
                    """
                FOR file IN library_files
                    COLLECT tagged = file.tagged WITH COUNT INTO count
                    RETURN {tagged: tagged, count: count}
                """
                ),
            )

        file_stats = {0: 0, 1: 0}
        for row in file_cursor:
            file_stats[row["tagged"]] = row["count"]

        # Get tag counts by type
        tag_cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR ft IN file_tags
                FOR lt IN library_tags
                    FILTER ft.tag_id == lt._id
                    COLLECT is_nomarr = lt.is_nomarr_tag WITH COUNT INTO count
                    RETURN {is_nomarr: is_nomarr, count: count}
            """
            ),
        )

        tag_counts = {"nomarr": 0, "user": 0}
        for row in tag_cursor:
            if row["is_nomarr"]:
                tag_counts["nomarr"] = row["count"]
            else:
                tag_counts["user"] = row["count"]

        return {
            "total_files": file_stats[0] + file_stats[1],
            "tagged_files": file_stats[1],
            "untagged_files": file_stats[0],
            "nomarr_tags": tag_counts["nomarr"],
            "user_tags": tag_counts["user"],
            "total_tags": tag_counts["nomarr"] + tag_counts["user"],
        }

    def get_tag_type_stats(self, tag_key: str) -> dict[str, Any]:
        """Get usage statistics for a specific tag key.

        Args:
            tag_key: Tag key to analyze

        Returns:
            Dict with 'key', 'is_multivalue', 'total_count', 'sample_values'
        """
        # Count distinct files using this tag
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
                FOR ft IN file_tags
                    FOR lt IN library_tags
                        FILTER ft.tag_id == lt._id AND lt.key == @tag_key
                        COLLECT WITH COUNT INTO total
                        RETURN total
                """,
                bind_vars=cast(dict[str, Any], {"tag_key": tag_key}),
            ),
        )
        total_count = next(cursor, 0)

        if total_count == 0:
            return {
                "key": tag_key,
                "is_multivalue": False,
                "total_count": 0,
                "sample_values": [],
            }

        # Get sample values to detect multivalue
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
                FOR lt IN library_tags
                    FILTER lt.key == @tag_key
                    LIMIT 10
                    RETURN lt.value
                """,
                bind_vars=cast(dict[str, Any], {"tag_key": tag_key}),
            ),
        )
        sample_values = list(cursor)

        # Detect if multivalue by checking if any values are arrays
        import json

        is_multivalue = False
        for val in sample_values:
            try:
                parsed = json.loads(val)
                if isinstance(parsed, list) and len(parsed) > 1:
                    is_multivalue = True
                    break
            except (json.JSONDecodeError, TypeError):
                pass

        return {
            "key": tag_key,
            "is_multivalue": is_multivalue,
            "total_count": total_count,
            "sample_values": sample_values,
        }

    def get_unique_tag_values(self, tag_key: str) -> list[str]:
        """Get all unique values for a given tag key."""
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR lt IN library_tags
                FILTER lt.key == @tag_key
                COLLECT value = lt.value
                SORT value
                RETURN value
            """,
                bind_vars=cast(dict[str, Any], {"tag_key": tag_key}),
            ),
        )
        return list(cursor)
