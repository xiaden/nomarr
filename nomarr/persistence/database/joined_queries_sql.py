"""
Multi-table JOIN queries.

Contains operations that query across multiple tables (JOINs).
Single-table operations belong in their respective *_table.py files.
ALL SQL string literals live in this module.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Literal

from nomarr.helpers.sql_helper import build_comparison, build_in_clause, build_limit_clause


class JoinedQueryOperations:
    """
    Multi-table JOIN query operations.

    Contains queries that span multiple tables. Single-table queries
    should live in their respective table-specific operations classes.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        """
        Initialize operations with database connection.

        Args:
            conn: SQLite connection
        """
        self.conn = conn

    # -------------------------------------------------------------------------
    # Simple query methods for smart playlist filtering
    # -------------------------------------------------------------------------

    # Whitelist of allowed comparison operators for tag queries
    _ALLOWED_OPERATORS = frozenset([">", "<", ">=", "<=", "=", "!="])

    def get_file_ids_matching_tag(
        self,
        tag_key: str,
        operator: Literal[">", "<", ">=", "<=", "=", "!="],
        value: float | int | str,
    ) -> set[int]:
        """
        Get file IDs where a numeric tag matches a condition.

        Uses sql_helper.build_comparison() to enforce operator whitelisting
        and prevent SQL injection via dynamic operator interpolation.

        Args:
            tag_key: Tag key (e.g., "nom:mood_happy")
            operator: Comparison operator (must be in whitelist)
            value: Numeric threshold

        Returns:
            Set of file IDs matching the condition

        Raises:
            ValueError: If operator is not in the allowed whitelist
        """
        # Build safe comparison fragment with whitelisted operator
        # This enforces that only approved operators can be used in the query
        comparison_sql = build_comparison(
            "CAST(tag_value AS REAL)",
            operator,
            allowed_operators=self._ALLOWED_OPERATORS,
            allow_expressions=True,
        )

        sql = f"""
            SELECT DISTINCT file_id
            FROM file_tags
            WHERE tag_key = ?
            AND {comparison_sql}
        """
        cursor = self.conn.cursor()
        cursor.execute(sql, (tag_key, value))
        return {row[0] for row in cursor.fetchall()}

    def get_file_ids_containing_tag(self, tag_key: str, substring: str) -> set[int]:
        """
        Get file IDs where a tag value contains a substring (case-insensitive).

        Args:
            tag_key: Tag key (e.g., "nom:genre")
            substring: Substring to search for

        Returns:
            Set of file IDs where tag value contains substring
        """
        sql = """
            SELECT DISTINCT file_id
            FROM file_tags
            WHERE tag_key = ?
            AND LOWER(tag_value) LIKE LOWER(?)
        """
        cursor = self.conn.cursor()
        cursor.execute(sql, (tag_key, f"%{substring}%"))
        return {row[0] for row in cursor.fetchall()}

    def get_tracks_by_file_ids(
        self,
        file_ids: set[int],
        order_by: list[tuple[str, Literal["asc", "desc"]]] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch track metadata for given file IDs.

        This method is preview-oriented: it uses RANDOM() ordering by default
        to provide a representative sample when no explicit ordering is given.
        This is safe for large result sets and provides varied preview results.

        Uses sql_helper.build_in_clause() and build_limit_clause() to safely
        construct dynamic SQL fragments.

        Args:
            file_ids: Set of file IDs to fetch
            order_by: List of (column, direction) tuples for ordering.
                     If None, defaults to ORDER BY RANDOM() for preview sampling.
            limit: Maximum number of tracks to return. Should be reasonable
                  (e.g., ≤100) for preview use cases to avoid performance issues.

        Returns:
            List of track dictionaries with keys: path, title, artist, album
        """
        if not file_ids:
            return []

        # Build ORDER BY clause (still using existing method for now)
        order_clause = self._build_order_by_clause(order_by)

        # Build LIMIT clause using helper
        limit_clause = build_limit_clause(limit)

        # Use helper to build safe IN clause
        in_clause = build_in_clause(len(file_ids))

        sql = f"""
            SELECT path, title, artist, album
            FROM library_files
            WHERE id {in_clause}
            {order_clause}
            {limit_clause}
        """

        cursor = self.conn.cursor()
        cursor.execute(sql, tuple(file_ids))

        results = []
        for row in cursor.fetchall():
            results.append(
                {
                    "path": row[0],
                    "title": row[1] if row[1] else self._extract_filename(row[0]),
                    "artist": row[2] if row[2] else "Unknown Artist",
                    "album": row[3] if row[3] else "Unknown Album",
                }
            )

        return results

    # -------------------------------------------------------------------------
    # Utility methods
    # -------------------------------------------------------------------------

    def _build_order_by_clause(self, order_by: list[tuple[str, Literal["asc", "desc"]]] | None) -> str:
        """
        Build SQL ORDER BY clause from validated order specifications.

        Args:
            order_by: List of (column, direction) tuples (validated by caller)

        Returns:
            SQL ORDER BY clause string (including "ORDER BY" keyword)
        """
        if not order_by:
            return "ORDER BY RANDOM()"

        # Build ORDER BY parts (column and direction are validated by caller)
        parts = []
        for column, direction in order_by:
            parts.append(f"{column} {direction.upper()}")

        return "ORDER BY " + ", ".join(parts)

    @staticmethod
    def _extract_filename(path: str) -> str:
        """
        Extract filename without extension from path.

        Args:
            path: File path

        Returns:
            Filename without extension
        """
        from pathlib import Path

        return Path(path).stem

    def search_library_files_with_tags(
        self,
        q: str = "",
        artist: str | None = None,
        album: str | None = None,
        tag_key: str | None = None,
        tag_value: str | None = None,
        tagged_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """
        Search library files with optional filtering.

        This is a joined query operation because it needs to efficiently
        return files WITH their tags in a single result set.

        Args:
            q: Text search query for artist/album/title
            artist: Filter by artist name
            album: Filter by album name
            tag_key: Filter by files that have this tag key
            tag_value: Filter by files with this specific tag key=value (requires tag_key)
            tagged_only: Only return tagged files
            limit: Maximum number of results
            offset: Pagination offset

        Returns:
            Tuple of (files list with tags, total count)
        """
        # Build WHERE clauses
        where_clauses = []
        params: list[Any] = []

        # Filter by tag key and optionally value
        if tag_key and tag_value:
            where_clauses.append(
                "library_files.id IN (SELECT file_id FROM file_tags WHERE tag_key = ? AND tag_value = ?)"
            )
            params.append(tag_key)
            params.append(tag_value)
        elif tag_key:
            where_clauses.append("library_files.id IN (SELECT file_id FROM file_tags WHERE tag_key = ?)")
            params.append(tag_key)

        # Text search across artist/album/title
        if q:
            where_clauses.append(
                "(library_files.artist LIKE ? OR library_files.album LIKE ? OR library_files.title LIKE ?)"
            )
            search_term = f"%{q}%"
            params.extend([search_term, search_term, search_term])

        # Filter by artist
        if artist:
            where_clauses.append("library_files.artist = ?")
            params.append(artist)

        # Filter by album
        if album:
            where_clauses.append("library_files.album = ?")
            params.append(album)

        # Tagged files only
        if tagged_only:
            where_clauses.append("library_files.tagged = 1")

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # Get total count
        count_query = f"SELECT COUNT(*) FROM library_files {where_sql}"
        total = int(self.conn.execute(count_query, params).fetchone()[0])

        # Get paginated files with tags in a single query
        # Use subquery to limit files first, then LEFT JOIN tags
        # This ensures LIMIT applies to files, not to file+tag rows
        files_query = f"""
            SELECT
                lf.id,
                lf.path,
                lf.library_id,
                lf.file_size,
                lf.modified_time,
                lf.duration_seconds,
                lf.artist,
                lf.album,
                lf.title,
                lf.genre,
                lf.year,
                lf.track_number,
                lf.calibration,
                lf.scanned_at,
                lf.last_tagged_at,
                lf.tagged,
                lf.tagged_version,
                lf.skip_auto_tag,
                file_tags.tag_key,
                file_tags.tag_value,
                file_tags.tag_type,
                file_tags.is_nomarr_tag
            FROM (
                SELECT * FROM library_files
                {where_sql}
                ORDER BY artist, album, track_number
                LIMIT ? OFFSET ?
            ) AS lf
            LEFT JOIN file_tags ON lf.id = file_tags.file_id
            ORDER BY lf.artist, lf.album, lf.track_number, file_tags.tag_key
        """
        params_with_limit = [*params, limit, offset]

        cur = self.conn.execute(files_query, params_with_limit)
        columns = [desc[0] for desc in cur.description]

        # Group rows by file (since LEFT JOIN creates multiple rows per file)
        files_dict: dict[int, dict[str, Any]] = {}
        for row in cur.fetchall():
            row_dict = dict(zip(columns, row, strict=False))
            file_id = row_dict["id"]

            # First time seeing this file - add it
            if file_id not in files_dict:
                # Extract file fields (everything except tag fields)
                file_data = {
                    k: v for k, v in row_dict.items() if k not in ("tag_key", "tag_value", "tag_type", "is_nomarr_tag")
                }
                file_data["tags"] = []
                files_dict[file_id] = file_data

            # Add tag if present (LEFT JOIN may have NULL tags)
            if row_dict["tag_key"] is not None:
                files_dict[file_id]["tags"].append(
                    {
                        "key": row_dict["tag_key"],
                        "value": row_dict["tag_value"],
                        "type": row_dict["tag_type"],
                        "is_nomarr": bool(row_dict["is_nomarr_tag"]),
                    }
                )

        return list(files_dict.values()), total
