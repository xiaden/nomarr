"""
Navidrome Smart Playlist Generator

Parses Smart Playlist query syntax and generates .nsp (Navidrome Smart Playlist) files.

Query Syntax:
    tag:KEY OPERATOR VALUE [AND|OR tag:KEY OPERATOR VALUE ...]

Operators:
    >   - Greater than (numeric) → gt
    <   - Less than (numeric) → lt
    >=  - Greater than or equal → use > (no gte in Navidrome)
    <=  - Less than or equal → use < (no lte in Navidrome)
    =   - Equals (numeric or string) → is
    !=  - Not equals → isNot
    contains - String contains (case-insensitive) → contains

Examples:
    tag:mood_happy > 0.7
    tag:mood_happy > 0.7 AND tag:energy > 0.6
    tag:genre = Rock
    tag:artist contains Beatles
    tag:bpm > 120 AND tag:danceability > 0.8

Output Format:
    Generates .nsp JSON files compatible with Navidrome Smart Playlists.
"""

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, ClassVar


class PlaylistQueryError(Exception):
    """Raised when a playlist query is invalid."""

    pass


class PlaylistGenerator:
    """Generates Navidrome Smart Playlists (.nsp) from query syntax."""

    # Operator mappings to SQL (for preview)
    SQL_OPERATORS: ClassVar[dict[str, str]] = {
        ">": ">",
        "<": "<",
        ">=": ">=",
        "<=": "<=",
        "=": "=",
        "!=": "!=",
        "contains": "LIKE",
    }

    # Operator mappings to Navidrome .nsp operators
    NSP_OPERATORS: ClassVar[dict[str, str]] = {
        ">": "gt",
        "<": "lt",
        ">=": "gt",  # No gte in Navidrome, use gt
        "<=": "lt",  # No lte in Navidrome, use lt
        "=": "is",
        "!=": "isNot",
        "contains": "contains",
    }

    def __init__(self, db_path: str, namespace: str = "nom"):
        """
        Initialize playlist generator.

        Args:
            db_path: Path to SQLite database
            namespace: Tag namespace (default: "nom")
        """
        self.db_path = db_path
        self.namespace = namespace

    def parse_query_to_nsp(self, query: str) -> dict[str, Any]:
        """
        Parse query into Navidrome .nsp JSON structure.

        Args:
            query: Smart Playlist query string

        Returns:
            Dictionary representing .nsp rules (without name/comment/sort/limit)

        Raises:
            PlaylistQueryError: If query syntax is invalid
        """
        if not query or not query.strip():
            raise PlaylistQueryError("Query cannot be empty")

        # Normalize whitespace
        query = " ".join(query.split())

        # Split by AND/OR (case-insensitive)
        parts = re.split(r"\s+(AND|OR)\s+", query, flags=re.IGNORECASE)

        conditions = []
        current_logic = None

        for part in parts:
            part_upper = part.upper()
            if part_upper in ("AND", "OR"):
                current_logic = part_upper
            else:
                # Parse individual condition
                nsp_rule = self._parse_condition_to_nsp(part)
                conditions.append((nsp_rule, current_logic))

        if not conditions:
            raise PlaylistQueryError("No valid conditions found in query")

        # Build .nsp structure
        # If all conditions are AND, use "all": [...]
        # If all conditions are OR, use "any": [...]
        # If mixed, we need nested structure

        logic_types = {logic for _, logic in conditions[1:] if logic}

        if not logic_types or logic_types == {"AND"}:
            # All AND conditions
            return {"all": [cond for cond, _ in conditions]}
        elif logic_types == {"OR"}:
            # All OR conditions
            return {"any": [cond for cond, _ in conditions]}
        else:
            # Mixed logic - default to all for safety
            # TODO: Support complex nested logic
            return {"all": [cond for cond, _ in conditions]}

    def _parse_condition_to_nsp(self, condition: str) -> dict[str, Any]:
        """
        Parse a single condition into Navidrome .nsp rule.

        Args:
            condition: Single condition string (e.g., "tag:mood_happy > 0.7")

        Returns:
            Dictionary representing a single .nsp rule

        Raises:
            PlaylistQueryError: If condition syntax is invalid
        """
        # Pattern: tag:KEY OPERATOR VALUE
        pattern = r"^tag:(\S+)\s+(>=|<=|!=|>|<|=|contains)\s+(.+)$"
        match = re.match(pattern, condition.strip(), re.IGNORECASE)

        if not match:
            raise PlaylistQueryError(f"Invalid condition syntax: {condition}")

        tag_key, operator, value = match.groups()
        operator = operator.lower()

        if operator not in self.NSP_OPERATORS:
            raise PlaylistQueryError(f"Unsupported operator for .nsp: {operator}")

        # Remove namespace prefix (Navidrome uses field names without namespace)
        if tag_key.startswith(f"{self.namespace}:"):
            field_name = tag_key[len(self.namespace) + 1 :]
        else:
            field_name = tag_key

        # Convert hyphens to underscores (Navidrome field naming)
        field_name = field_name.replace("-", "_")

        # Convert value to appropriate type
        value = value.strip().strip('"').strip("'")

        # Try to convert to number
        try:
            if "." in value:
                value = float(value)
            else:
                value = int(value)
        except ValueError:
            # Keep as string
            pass

        # Build .nsp rule
        nsp_op = self.NSP_OPERATORS[operator]

        return {nsp_op: {field_name: value}}

    def parse_query_to_sql(self, query: str) -> tuple[str, list[Any]]:
        """
        Parse Smart Playlist query into SQL WHERE clause for preview.

        Args:
            query: Smart Playlist query string

        Returns:
            Tuple of (sql_where_clause, parameters)

        Raises:
            PlaylistQueryError: If query syntax is invalid
        """
        if not query or not query.strip():
            raise PlaylistQueryError("Query cannot be empty")

        # Normalize whitespace
        query = " ".join(query.split())

        # Split by AND/OR (case-insensitive)
        parts = re.split(r"\s+(AND|OR)\s+", query, flags=re.IGNORECASE)

        conditions = []
        parameters = []
        logic_ops = []

        for part in parts:
            part_upper = part.upper()
            if part_upper in ("AND", "OR"):
                logic_ops.append(part_upper)
            else:
                # Parse individual condition: tag:KEY OPERATOR VALUE
                sql_cond, params = self._parse_condition_to_sql(part)
                conditions.append(sql_cond)
                parameters.extend(params)

        if not conditions:
            raise PlaylistQueryError("No valid conditions found in query")

        # Build SQL WHERE clause
        where_clause = conditions[0]
        for i, logic_op in enumerate(logic_ops):
            if i + 1 < len(conditions):
                where_clause += f" {logic_op} {conditions[i + 1]}"

        return where_clause, parameters

    def _parse_condition_to_sql(self, condition: str) -> tuple[str, list[Any]]:
        """
        Parse a single condition into SQL for preview queries.

        Args:
            condition: Single condition string (e.g., "tag:mood_happy > 0.7")

        Returns:
            Tuple of (sql_condition, parameters)

        Raises:
            PlaylistQueryError: If condition syntax is invalid
        """
        # Pattern: tag:KEY OPERATOR VALUE
        pattern = r"^tag:(\S+)\s+(>=|<=|!=|>|<|=|contains)\s+(.+)$"
        match = re.match(pattern, condition.strip(), re.IGNORECASE)

        if not match:
            raise PlaylistQueryError(f"Invalid condition syntax: {condition}")

        tag_key, operator, value = match.groups()
        operator = operator.lower()

        if operator not in self.SQL_OPERATORS:
            raise PlaylistQueryError(f"Unknown operator: {operator}")

        # Add namespace prefix if not present
        if not tag_key.startswith(f"{self.namespace}:"):
            full_tag_key = f"{self.namespace}:{tag_key}"
        else:
            full_tag_key = tag_key

        # Convert value to appropriate type
        value = value.strip().strip('"').strip("'")

        # Try to convert to number
        try:
            if "." in value:
                value = float(value)
            else:
                value = int(value)
        except ValueError:
            # Keep as string
            pass

        # Build SQL condition
        sql_op = self.SQL_OPERATORS[operator]

        params: list[str | float | int]
        if operator == "contains":
            # Case-insensitive LIKE
            sql_cond = "EXISTS (SELECT 1 FROM library_tags lt2 WHERE lt2.file_id = lt.file_id AND lt2.tag_key = ? AND LOWER(lt2.tag_value) LIKE LOWER(?))"
            params = [full_tag_key, f"%{value}%"]
        else:
            # Direct comparison
            sql_cond = f"EXISTS (SELECT 1 FROM library_tags lt2 WHERE lt2.file_id = lt.file_id AND lt2.tag_key = ? AND CAST(lt2.tag_value AS REAL) {sql_op} ?)"
            params = [full_tag_key, value]

        return sql_cond, params

    def generate_playlist(
        self, query: str, limit: int | None = None, order_by: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Generate playlist preview from Smart Playlist query.

        Args:
            query: Smart Playlist query string
            limit: Maximum number of tracks (default: no limit)
            order_by: SQL ORDER BY clause (default: random)

        Returns:
            List of track dictionaries with keys: file_path, title, artist, album

        Raises:
            PlaylistQueryError: If query is invalid
        """
        where_clause, parameters = self.parse_query_to_sql(query)

        # Build SQL query
        sql = f"""
            SELECT DISTINCT
                lf.path,
                lf.title,
                lf.artist,
                lf.album
            FROM library_files lf
            INNER JOIN library_tags lt ON lf.id = lt.file_id
            WHERE {where_clause}
        """

        # Add ordering
        if order_by:
            sql += f" ORDER BY {order_by}"
        else:
            sql += " ORDER BY RANDOM()"

        # Add limit
        if limit and limit > 0:
            sql += f" LIMIT {limit}"

        # Execute query
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(sql, parameters)

                results = []
                for row in cursor.fetchall():
                    results.append(
                        {
                            "file_path": row["path"],
                            "title": row["title"] or Path(row["path"]).stem,
                            "artist": row["artist"] or "Unknown Artist",
                            "album": row["album"] or "Unknown Album",
                        }
                    )

                return results
        except sqlite3.Error as e:
            raise PlaylistQueryError(f"Database error: {e}") from e

    def generate_nsp(
        self,
        query: str,
        playlist_name: str = "Playlist",
        comment: str = "",
        sort: str | None = None,
        limit: int | None = None,
    ) -> str:
        """
        Generate Navidrome Smart Playlist (.nsp) JSON content.

        Args:
            query: Smart Playlist query string
            playlist_name: Playlist name
            comment: Optional playlist description
            sort: Sort order (e.g., "-rating,title")
            limit: Maximum number of tracks

        Returns:
            .nsp JSON content as string
        """
        rules = self.parse_query_to_nsp(query)

        nsp = {
            "name": playlist_name,
            "comment": comment or f"Generated from query: {query}",
            **rules,
        }

        if sort:
            nsp["sort"] = sort

        if limit and limit > 0:
            nsp["limit"] = limit

        return json.dumps(nsp, indent=2)

    def preview_playlist(self, query: str, preview_limit: int = 10) -> dict[str, Any]:
        """
        Preview playlist results without generating full file.

        Args:
            query: Smart Playlist query string
            preview_limit: Number of sample tracks to return

        Returns:
            Dictionary with keys:
                - total_count: Total matching tracks
                - sample_tracks: List of sample track dictionaries
                - query: Original query string
        """
        # Get total count
        where_clause, parameters = self.parse_query_to_sql(query)

        count_sql = f"""
            SELECT COUNT(DISTINCT lf.id)
            FROM library_files lf
            INNER JOIN library_tags lt ON lf.id = lt.file_id
            WHERE {where_clause}
        """

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(count_sql, parameters)
                total_count = cursor.fetchone()[0]
        except sqlite3.Error as e:
            raise PlaylistQueryError(f"Database error: {e}") from e

        # Get sample tracks
        sample_tracks = self.generate_playlist(query, limit=preview_limit)

        return {"total_count": total_count, "sample_tracks": sample_tracks, "query": query}


def preview_playlist_query(db_path: str, query: str, namespace: str = "nom", preview_limit: int = 10) -> dict[str, Any]:
    """
    Preview a Smart Playlist query.

    Args:
        db_path: Path to SQLite database
        query: Smart Playlist query string
        namespace: Tag namespace
        preview_limit: Number of sample tracks

    Returns:
        Preview dictionary
    """
    generator = PlaylistGenerator(db_path, namespace)
    return generator.preview_playlist(query, preview_limit)


def generate_nsp_playlist(
    db_path: str,
    query: str,
    playlist_name: str = "Playlist",
    comment: str = "",
    namespace: str = "nom",
    sort: str | None = None,
    limit: int | None = None,
) -> str:
    """
    Generate Navidrome Smart Playlist (.nsp) from query.

    Args:
        db_path: Path to SQLite database
        query: Smart Playlist query string
        playlist_name: Playlist name
        comment: Playlist description
        namespace: Tag namespace
        sort: Sort order
        limit: Maximum tracks

    Returns:
        .nsp JSON content string
    """
    generator = PlaylistGenerator(db_path, namespace)
    return generator.generate_nsp(query, playlist_name, comment, sort, limit)
