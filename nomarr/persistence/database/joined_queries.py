"""
Multi-table JOIN queries.

Contains operations that query across multiple tables (JOINs).
Single-table operations belong in their respective *_table.py files.
ALL SQL string literals live in this module.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Literal

from nomarr.workflows.navidrome.parse_smart_playlist_query import SmartPlaylistFilter, TagCondition


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

    def select_tracks_for_smart_playlist(
        self,
        filter: SmartPlaylistFilter,
        order_by: list[tuple[str, Literal["asc", "desc"]]] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Execute smart playlist filter and return matching tracks.

        Args:
            filter: Parsed smart playlist filter
            order_by: List of (column, direction) tuples for ordering
            limit: Maximum number of tracks to return

        Returns:
            List of track dictionaries with keys: path, title, artist, album

        Raises:
            sqlite3.Error: If database query fails
        """
        # Build WHERE clause from filter
        where_clause, parameters = self._build_where_clause(filter)

        # Build ORDER BY clause
        order_clause = self._build_order_by_clause(order_by)

        # Build LIMIT clause
        limit_clause = f" LIMIT {limit}" if limit else ""

        # Build full SQL query
        sql = f"""
            SELECT DISTINCT
                lf.path,
                lf.title,
                lf.artist,
                lf.album
            FROM library_files lf
            INNER JOIN library_tags lt ON lf.id = lt.file_id
            WHERE {where_clause}
            {order_clause}
            {limit_clause}
        """

        # Execute query
        cursor = self.conn.cursor()
        cursor.execute(sql, parameters)

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

    def count_tracks_for_smart_playlist(self, filter: SmartPlaylistFilter) -> int:
        """
        Count total tracks matching smart playlist filter.

        Args:
            filter: Parsed smart playlist filter

        Returns:
            Total count of matching tracks

        Raises:
            sqlite3.Error: If database query fails
        """
        where_clause, parameters = self._build_where_clause(filter)

        sql = f"""
            SELECT COUNT(DISTINCT lf.id)
            FROM library_files lf
            INNER JOIN library_tags lt ON lf.id = lt.file_id
            WHERE {where_clause}
        """

        cursor = self.conn.cursor()
        cursor.execute(sql, parameters)
        result = cursor.fetchone()
        return int(result[0]) if result else 0

    def _build_where_clause(self, filter: SmartPlaylistFilter) -> tuple[str, list[Any]]:
        """
        Build SQL WHERE clause from SmartPlaylistFilter.

        SQL SANITIZATION:
        - Uses parameterized queries ("?") for all user-controlled data
        - Tag keys and values are passed as parameters, never interpolated
        - Operators are validated by the parser before reaching this layer

        Args:
            filter: Parsed smart playlist filter

        Returns:
            Tuple of (where_clause_sql, parameters)
        """
        conditions = []
        parameters = []

        # Handle all_conditions (AND)
        if filter.all_conditions:
            for cond in filter.all_conditions:
                sql_cond, params = self._build_condition_sql(cond)
                conditions.append(sql_cond)
                parameters.extend(params)

            # Join with AND
            if len(conditions) == 1:
                where_clause = conditions[0]
            else:
                where_clause = " AND ".join(f"({c})" for c in conditions)

        # Handle any_conditions (OR)
        elif filter.any_conditions:
            for cond in filter.any_conditions:
                sql_cond, params = self._build_condition_sql(cond)
                conditions.append(sql_cond)
                parameters.extend(params)

            # Join with OR
            if len(conditions) == 1:
                where_clause = conditions[0]
            else:
                where_clause = " OR ".join(f"({c})" for c in conditions)
        else:
            # No conditions - match all
            where_clause = "1=1"

        return where_clause, parameters

    def _build_condition_sql(self, condition: TagCondition) -> tuple[str, list[Any]]:
        """
        Build SQL for a single tag condition.

        SQL SANITIZATION:
        - Tag key and value are passed as parameterized values ("?")
        - Operator is validated by parser (only allows specific string literals)
        - No user data is interpolated into SQL strings

        Args:
            condition: Single tag condition

        Returns:
            Tuple of (sql_condition, parameters)
        """
        tag_key = condition.tag_key
        operator = condition.operator
        value = condition.value

        params: list[str | float | int]

        if operator == "contains":
            # Case-insensitive string contains
            sql_cond = """
                EXISTS (
                    SELECT 1 FROM library_tags lt2
                    WHERE lt2.file_id = lt.file_id
                    AND lt2.tag_key = ?
                    AND LOWER(lt2.tag_value) LIKE LOWER(?)
                )
            """
            params = [tag_key, f"%{value}%"]
        else:
            # Numeric comparison
            sql_operator = self._map_operator_to_sql(operator)
            sql_cond = f"""
                EXISTS (
                    SELECT 1 FROM library_tags lt2
                    WHERE lt2.file_id = lt.file_id
                    AND lt2.tag_key = ?
                    AND CAST(lt2.tag_value AS REAL) {sql_operator} ?
                )
            """
            params = [tag_key, value]

        return sql_cond, params

    def _map_operator_to_sql(self, operator: str) -> str:
        """
        Map validated operator to SQL comparison operator.

        Args:
            operator: Operator string (already validated by parser)

        Returns:
            SQL operator string (safe for direct interpolation)
        """
        # These operators are validated by the parser before reaching this layer
        operator_map = {
            ">": ">",
            "<": "<",
            ">=": ">=",
            "<=": "<=",
            "=": "=",
            "!=": "!=",
        }
        return operator_map.get(operator, "=")

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
