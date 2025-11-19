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

    # Maximum query length to prevent ReDoS attacks
    MAX_QUERY_LENGTH: ClassVar[int] = 4096

    # Maximum limit for playlist size
    MAX_LIMIT: ClassVar[int] = 10000

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

    # Whitelisted ORDER BY columns
    VALID_ORDER_COLUMNS: ClassVar[set[str]] = {"path", "title", "artist", "album", "random()"}

    def __init__(self, db_path: str, namespace: str = "nom"):
        """
        Initialize playlist generator.

        Args:
            db_path: Path to SQLite database
            namespace: Tag namespace (default: "nom")
        """
        self.db_path = db_path
        self.namespace = namespace

    @staticmethod
    def _tokenize_query(query: str) -> tuple[list[str], list[str]]:
        """
        Tokenize query into conditions and logic operators using linear-time algorithm.

        This replaces re.split() to avoid ReDoS vulnerabilities from nested quantifiers.

        Args:
            query: Query string with AND/OR operators

        Returns:
            Tuple of (conditions, operators) where:
                - conditions: List of condition strings
                - operators: List of "AND"/"OR" operators (uppercase)

        Example:
            >>> _tokenize_query("tag:a > 1 AND tag:b < 2 OR tag:c = 3")
            (["tag:a > 1", "tag:b < 2", "tag:c = 3"], ["AND", "OR"])
        """
        conditions = []
        operators = []

        # Use regex finditer for linear-time tokenization
        # \b ensures word boundaries (prevents matching "BAND", "FORK", etc.)
        import re

        pattern = re.compile(r"\b(AND|OR)\b", re.IGNORECASE)

        last_pos = 0
        for match in pattern.finditer(query):
            # Extract condition between last position and current match
            condition = query[last_pos : match.start()].strip()
            if condition:
                conditions.append(condition)

            # Extract operator and normalize to uppercase
            operators.append(match.group(1).upper())
            last_pos = match.end()

        # Extract final condition after last operator
        final_condition = query[last_pos:].strip()
        if final_condition:
            conditions.append(final_condition)

        return conditions, operators

    def parse_query_to_nsp(self, query: str) -> dict[str, Any]:
        """
        Parse query into Navidrome .nsp JSON structure.

        Args:
            query: Smart Playlist query string

        Returns:
            Dictionary representing .nsp rules (without name/comment/sort/limit)

        Raises:
            PlaylistQueryError: If query syntax is invalid or too long
        """
        if not query or not query.strip():
            raise PlaylistQueryError("Query cannot be empty")

        # Enforce query length limit to prevent ReDoS attacks
        if len(query) > self.MAX_QUERY_LENGTH:
            raise PlaylistQueryError(f"Query too long (max {self.MAX_QUERY_LENGTH} characters)")

        # Normalize whitespace
        query = " ".join(query.split())

        # Use linear-time tokenizer instead of re.split
        condition_strings, operators = self._tokenize_query(query)

        if not condition_strings:
            raise PlaylistQueryError("No valid conditions found in query")

        conditions = []

        for i, cond_str in enumerate(condition_strings):
            # Parse individual condition: tag:KEY OPERATOR VALUE
            nsp_cond = self._parse_condition_to_nsp(cond_str)

            # Determine logic operator for this condition
            # First condition has no logic operator
            logic = operators[i - 1] if i > 0 else None
            conditions.append((nsp_cond, logic))

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
        # Use [^\s].* instead of .+ to prevent ReDoS (catastrophic backtracking)
        pattern = r"^tag:(\S+)\s+(>=|<=|!=|>|<|=|contains)\s+([^\s].*)$"
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

        SQL SANITIZATION:
        This function is a sanitizer that constructs WHERE clauses ONLY from:
        - Fixed SQL templates (EXISTS subqueries, CAST, LIKE patterns)
        - Whitelisted operators from SQL_OPERATORS dictionary
        - Parameterized placeholders ("?") for all user-controlled values

        User-controlled data (tag keys and tag values) are NEVER interpolated into
        SQL strings. They are passed as parameters to prevent SQL injection.

        Args:
            query: Smart Playlist query string

        Returns:
            Tuple of (sql_where_clause, parameters)
            - sql_where_clause: SQL string with "?" placeholders
            - parameters: List of values to bind to placeholders

        Raises:
            PlaylistQueryError: If query syntax is invalid or too long
        """
        if not query or not query.strip():
            raise PlaylistQueryError("Query cannot be empty")

        # Enforce query length limit to prevent ReDoS attacks
        if len(query) > self.MAX_QUERY_LENGTH:
            raise PlaylistQueryError(f"Query too long (max {self.MAX_QUERY_LENGTH} characters)")

        # Normalize whitespace
        query = " ".join(query.split())

        # Use linear-time tokenizer instead of re.split
        condition_strings, operators = self._tokenize_query(query)

        if not condition_strings:
            raise PlaylistQueryError("No valid conditions found in query")

        conditions = []
        parameters = []

        for cond_str in condition_strings:
            # Parse individual condition: tag:KEY OPERATOR VALUE
            sql_cond, params = self._parse_condition_to_sql(cond_str)
            conditions.append(sql_cond)
            parameters.extend(params)

        if not conditions:
            raise PlaylistQueryError("No valid conditions found in query")

        # Build SQL WHERE clause using validated operators
        where_clause = conditions[0]
        for i, logic_op in enumerate(operators):
            if i + 1 < len(conditions):
                # Operators are already uppercase from tokenizer
                where_clause += f" {logic_op} {conditions[i + 1]}"

        return where_clause, parameters

    def _parse_condition_to_sql(self, condition: str) -> tuple[str, list[Any]]:
        """
        Parse a single condition into SQL for preview queries.

        SQL SANITIZATION:
        - Extracts tag_key and value from condition using regex parsing
        - Validates operator against SQL_OPERATORS whitelist
        - Builds SQL using fixed templates (EXISTS subquery, CAST, LIKE)
        - Returns tag_key and value as parameters (never interpolated into SQL)
        - SQL string contains only "?" placeholders for user data

        Args:
            condition: Single condition string (e.g., "tag:mood_happy > 0.7")

        Returns:
            Tuple of (sql_condition, parameters)
            - sql_condition: SQL string with "?" placeholders
            - parameters: List of [tag_key, value] to bind

        Raises:
            PlaylistQueryError: If condition syntax is invalid or operator not whitelisted
        """
        # Pattern: tag:KEY OPERATOR VALUE
        # Use [^\s].* instead of .+ to prevent ReDoS (catastrophic backtracking)
        pattern = r"^tag:(\S+)\s+(>=|<=|!=|>|<|=|contains)\s+([^\s].*)$"
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
            limit: Maximum number of tracks (default: no limit, max: MAX_LIMIT)
            order_by: ORDER BY clause with whitelisted column + optional ASC/DESC
                     Valid columns: path, title, artist, album, random()

        Returns:
            List of track dictionaries with keys: file_path, title, artist, album

        Raises:
            PlaylistQueryError: If query is invalid or parameters are unsafe
        """
        where_clause, parameters = self.parse_query_to_sql(query)

        # Validate and sanitize ORDER BY clause
        validated_order_by = self._validate_order_by(order_by)

        # Validate LIMIT
        validated_limit = self._validate_limit(limit)

        # Build SQL query with parameterized WHERE clause
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

        # Add validated ordering (safe from SQL injection)
        if validated_order_by:
            sql += f" ORDER BY {validated_order_by}"
        else:
            sql += " ORDER BY RANDOM()"

        # Add validated limit (integer, not user string)
        if validated_limit:
            sql += f" LIMIT {validated_limit}"

        # Execute query with parameterized values
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

    def _validate_order_by(self, order_by: str | None) -> str | None:
        """
        Validate and sanitize ORDER BY clause against whitelist.

        SQL INJECTION PREVENTION:
        - Validates column name against VALID_ORDER_COLUMNS whitelist only
        - Validates direction against literal "ASC"/"DESC" only
        - Rejects any additional parts or SQL beyond these tokens
        - Returns validated string safe for direct SQL inclusion (no user data interpolated)

        Args:
            order_by: Raw ORDER BY string from user (e.g., "title ASC", "random()")

        Returns:
            Validated ORDER BY string safe for SQL, or None if not provided

        Raises:
            PlaylistQueryError: If order_by contains invalid column, direction, or extra clauses
        """
        if not order_by:
            return None

        # Normalize whitespace and case
        order_by = " ".join(order_by.strip().split())
        parts = order_by.split()

        if not parts:
            return None

        # Extract base column (first part)
        base_column = parts[0].lower()

        # Validate against whitelist
        if base_column not in self.VALID_ORDER_COLUMNS:
            raise PlaylistQueryError(
                f"Invalid ORDER BY column: {base_column}. Must be one of: {', '.join(sorted(self.VALID_ORDER_COLUMNS))}"
            )

        # Validate optional ASC/DESC (second part)
        direction = ""
        if len(parts) > 1:
            dir_normalized = parts[1].upper()
            if dir_normalized not in ("ASC", "DESC"):
                raise PlaylistQueryError(f"Invalid ORDER BY direction: {parts[1]}. Must be ASC or DESC")
            direction = f" {dir_normalized}"

        # Reject any additional parts (prevents injection of additional clauses)
        if len(parts) > 2:
            raise PlaylistQueryError("Invalid ORDER BY syntax: too many parts")

        # Return validated string (base_column is from whitelist, direction is validated)
        return f"{base_column}{direction}"

    def _validate_limit(self, limit: int | None) -> int | None:
        """
        Validate LIMIT parameter.

        SQL INJECTION PREVENTION:
        - Ensures limit is an integer (not a string that could contain SQL)
        - Validates bounds (positive, <= MAX_LIMIT)
        - Returns validated integer for safe direct SQL inclusion

        Args:
            limit: Raw limit value from user

        Returns:
            Validated integer limit, or None if not provided

        Raises:
            PlaylistQueryError: If limit is not an integer or out of bounds
        """
        if limit is None:
            return None

        # Ensure it's an integer
        if not isinstance(limit, int):
            raise PlaylistQueryError("LIMIT must be an integer")

        # Enforce bounds
        if limit <= 0:
            raise PlaylistQueryError("LIMIT must be positive")

        if limit > self.MAX_LIMIT:
            raise PlaylistQueryError(f"LIMIT too large (max {self.MAX_LIMIT})")

        return limit

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
