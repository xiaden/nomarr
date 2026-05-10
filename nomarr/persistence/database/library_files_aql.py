"""Explicit library-file query operations backed by AQL."""

from __future__ import annotations

from typing import Any

from nomarr.persistence.aql.primitives import execute, normalize_limit
from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.constructor.pagination import DEFAULT_LIMIT

# Query fragment used by track projections. Requires `file` in scope.
# When no ISRC tag exists, FIRST(...) returns null and the projected `isrc` is null.
_ISRC_SUBQUERY = """
LET isrc = FIRST(
  FOR edge IN song_has_tags
    FILTER edge._from == file._id
    FOR tag IN tags
      FILTER tag._id == edge._to
      FILTER tag.name == "isrc"
      LIMIT 1
      RETURN tag.value
)
"""

# Projection fragment used with `_ISRC_SUBQUERY`. Requires `file` and `isrc`.
_TRACK_PROJECTION = """
RETURN {
  _id: file._id,
  path: file.path,
  title: file.title,
  artist: file.artist,
  album: file.album,
  isrc: isrc
}
"""


def _is_numeric_type(target_value: float | str) -> bool:
    return isinstance(target_value, (int, float)) and not isinstance(target_value, bool)


class LibraryFilesAqlOperations:
    """Explicit, reviewed library-file operations."""

    def __init__(self, db: SafeDatabase) -> None:
        self._db = db

    def list_all_file_ids(self, *, limit: int | None = None) -> list[str]:
        """Return ordered `library_files` ids."""
        effective_limit = DEFAULT_LIMIT if limit is None else limit
        query = """
        FOR file IN library_files
          SORT file._key
          LIMIT @limit
          RETURN file._id
        """
        rows = execute(self._db, query, {"limit": normalize_limit(effective_limit)})
        return [row for row in rows if isinstance(row, str)]

    def count_files_by_tag(self, tag_key: str, target_value: float | str) -> int:
        """Count files matching tag query semantics."""
        if _is_numeric_type(target_value):
            query = """
            LET tag_ids = (
              FOR tag IN tags
                FILTER tag.name == @tag_key
                FILTER IS_NUMBER(tag.value)
                RETURN tag._id
            )
            RETURN LENGTH(UNIQUE(
              FOR edge IN song_has_tags
                FILTER edge._to IN tag_ids
                RETURN edge._from
            ))
            """
            rows = execute(self._db, query, {"tag_key": tag_key})
            return int(rows[0]) if rows else 0

        query = """
        LET tag_ids = (
          FOR tag IN tags
            FILTER tag.name == @tag_key
            FILTER tag.value == @tag_value
            RETURN tag._id
        )
        RETURN LENGTH(UNIQUE(
          FOR edge IN song_has_tags
            FILTER edge._to IN tag_ids
            RETURN edge._from
        ))
        """
        rows = execute(self._db, query, {"tag_key": tag_key, "tag_value": str(target_value)})
        return int(rows[0]) if rows else 0

    def get_tracks_for_matching(self, *, library_id: str | None = None) -> list[dict[str, Any]]:
        """Return fuzzy matching track rows, optionally scoped to one library."""
        if library_id is not None:
            query = (
                """
            FOR ownership IN library_contains_file
              FILTER ownership._from == @library_id
              FOR file IN library_files
                FILTER file._id == ownership._to
                FILTER file.is_valid == true
            """
                + _ISRC_SUBQUERY
                + _TRACK_PROJECTION
            )
            rows = execute(self._db, query, {"library_id": library_id})
        else:
            query = (
                """
            FOR file IN library_files
              FILTER file.is_valid == true
            """
                + _ISRC_SUBQUERY
                + _TRACK_PROJECTION
            )
            rows = execute(self._db, query, {})

        return [row for row in rows if isinstance(row, dict)]
