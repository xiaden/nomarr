"""
Analytics query functions - SQL/DB access for analytics operations.

This module is part of the persistence layer and contains all SQL queries
needed for analytics computations. It provides raw data retrieval without
performing any analytics logic.

PERSISTENCE LAYER RULES:
- Contains all SQL queries for analytics
- Returns raw rows/records (sqlite3.Row or simple Python structures)
- May ONLY import nomarr.persistence.* and nomarr.helpers
- Must NOT import nomarr.analytics, nomarr.services, nomarr.workflows, or nomarr.interfaces
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def fetch_tag_frequencies_data(
    db: Database,
    namespace: str,
    limit: int,
) -> dict[str, Any]:
    """
    Fetch raw data for tag frequency analysis.

    Returns:
        {
            "total_files": int,
            "nom_tag_rows": [(tag_key, count), ...],
            "artist_rows": [(artist, count), ...],
            "genre_rows": [(genre, count), ...],
            "album_rows": [(album, count), ...]
        }
    """
    # Get total file count
    _, total_count = db.library.list_library_files(limit=1)

    # Count tags using library_tags table
    namespace_prefix = f"{namespace}:"
    cursor = db.conn.execute(
        """
        SELECT tag_key, COUNT(DISTINCT file_id) as tag_count
        FROM library_tags
        WHERE tag_key LIKE ?
        GROUP BY tag_key
        ORDER BY tag_count DESC
        LIMIT ?
        """,
        (f"{namespace_prefix}%", limit),
    )
    nom_tag_rows = cursor.fetchall()

    # Count artists
    artist_cursor = db.conn.execute(
        """
        SELECT artist, COUNT(*) as count
        FROM library_files
        WHERE artist IS NOT NULL
        GROUP BY artist
        ORDER BY count DESC
        LIMIT ?
        """,
        (limit,),
    )
    artist_rows = artist_cursor.fetchall()

    # Count genres
    genre_cursor = db.conn.execute(
        """
        SELECT genre, COUNT(*) as count
        FROM library_files
        WHERE genre IS NOT NULL
        GROUP BY genre
        ORDER BY count DESC
        LIMIT ?
        """,
        (limit,),
    )
    genre_rows = genre_cursor.fetchall()

    # Count albums
    album_cursor = db.conn.execute(
        """
        SELECT album, COUNT(*) as count
        FROM library_files
        WHERE album IS NOT NULL
        GROUP BY album
        ORDER BY count DESC
        LIMIT ?
        """,
        (limit,),
    )
    album_rows = album_cursor.fetchall()

    return {
        "total_files": total_count,
        "nom_tag_rows": nom_tag_rows,
        "artist_rows": artist_rows,
        "genre_rows": genre_rows,
        "album_rows": album_rows,
        "namespace_prefix": namespace_prefix,
    }


def fetch_tag_correlation_data(
    db: Database,
    namespace: str,
    top_n: int,
) -> dict[str, Any]:
    """
    Fetch raw data for tag correlation analysis.

    Returns:
        {
            "mood_tag_rows": [(tag_value, tag_type, file_id), ...],  # All mood tag data
            "tier_tag_keys": [tag_key, ...],  # All *_tier tag keys
            "tier_tag_rows": {tag_key: [(file_id, tag_value), ...], ...}  # Tier tag data per key
        }
    """
    mood_tag_keys = [
        f"{namespace}:mood-strict",
        f"{namespace}:mood-regular",
        f"{namespace}:mood-loose",
    ]

    # Fetch all mood tag data
    mood_tag_rows = []
    for tag_key in mood_tag_keys:
        cursor = db.conn.execute(
            "SELECT file_id, tag_value, tag_type FROM library_tags WHERE tag_key = ?",
            (tag_key,),
        )
        mood_tag_rows.extend(cursor.fetchall())

    # Get all *_tier tag keys
    tier_cursor = db.conn.execute(
        "SELECT DISTINCT tag_key FROM library_tags WHERE tag_key LIKE ? AND tag_key LIKE ?",
        (f"{namespace}:%", "%_tier"),
    )
    tier_tag_keys = [row[0] for row in tier_cursor.fetchall()]

    # Fetch tier tag data for each key (we'll need this for correlation calc)
    # Return as dict to keep query results organized by key
    tier_tag_rows = {}
    for tier_tag_key in tier_tag_keys:
        cursor = db.conn.execute(
            "SELECT file_id, tag_value FROM library_tags WHERE tag_key = ?",
            (tier_tag_key,),
        )
        tier_tag_rows[tier_tag_key] = cursor.fetchall()

    return {
        "mood_tag_rows": mood_tag_rows,
        "tier_tag_keys": tier_tag_keys,
        "tier_tag_rows": tier_tag_rows,
        "namespace": namespace,
    }


def fetch_mood_distribution_data(
    db: Database,
    namespace: str,
) -> list[tuple[str, str, str]]:
    """
    Fetch raw mood tag data for distribution analysis.

    Returns:
        List of (mood_type, tag_value, tag_type) tuples
        where mood_type is one of: "mood-strict", "mood-regular", "mood-loose"
    """
    mood_rows = []

    for mood_type in ["mood-strict", "mood-regular", "mood-loose"]:
        tag_key = f"{namespace}:{mood_type}"
        cursor = db.conn.execute(
            "SELECT tag_value, tag_type FROM library_tags WHERE tag_key = ?",
            (tag_key,),
        )
        for tag_value, tag_type in cursor.fetchall():
            mood_rows.append((mood_type, tag_value, tag_type))

    return mood_rows


def fetch_artist_tag_profile_data(
    db: Database,
    artist: str,
    namespace: str,
) -> dict[str, Any]:
    """
    Fetch raw tag data for a specific artist.

    Returns:
        {
            "files": list[dict],  # Artist's files
            "file_count": int,
            "tag_rows": [(tag_key, tag_value, tag_type), ...]  # All tags for these files
        }
    """
    # Get files for this artist
    files, file_count = db.library.list_library_files(artist=artist, limit=1000000)

    if file_count == 0:
        return {
            "files": [],
            "file_count": 0,
            "tag_rows": [],
        }

    # Get file IDs
    file_ids = [f["id"] for f in files]

    # Query tags for these files in batches
    tag_rows = []
    batch_size = 500

    for i in range(0, len(file_ids), batch_size):
        batch_ids = file_ids[i : i + batch_size]
        placeholders = ",".join("?" * len(batch_ids))

        cursor = db.conn.execute(
            f"""
            SELECT tag_key, tag_value, tag_type
            FROM library_tags
            WHERE file_id IN ({placeholders})
              AND tag_key LIKE ?
            """,
            (*batch_ids, f"{namespace}:%"),
        )
        tag_rows.extend(cursor.fetchall())

    return {
        "files": files,
        "file_count": file_count,
        "tag_rows": tag_rows,
        "namespace_prefix": f"{namespace}:",
    }


def fetch_mood_value_co_occurrence_data(
    db: Database,
    mood_value: str,
    namespace: str,
) -> dict[str, Any]:
    """
    Fetch raw data for mood value co-occurrence analysis.

    Returns:
        {
            "mood_tag_rows": [(file_id, tag_value, tag_type), ...],  # All mood tags
            "genre_rows": [(genre, count), ...],  # Genre distribution for matching files
            "artist_rows": [(artist, count), ...],  # Artist distribution for matching files
            "matching_file_ids": set[int]  # File IDs that contain the mood_value
        }
    """
    mood_tag_keys = [
        f"{namespace}:mood-strict",
        f"{namespace}:mood-regular",
        f"{namespace}:mood-loose",
    ]

    # Fetch all mood tag data and identify matching files
    mood_tag_rows = []
    matching_file_ids = set()

    for tag_key in mood_tag_keys:
        cursor = db.conn.execute(
            "SELECT file_id, tag_value, tag_type FROM library_tags WHERE tag_key = ?",
            (tag_key,),
        )

        for file_id, tag_value, tag_type in cursor.fetchall():
            mood_tag_rows.append((file_id, tag_value, tag_type))

            # Check if this file contains our mood_value
            if tag_type == "array":
                try:
                    moods = json.loads(tag_value)
                    if mood_value in [str(m).strip() for m in moods]:
                        matching_file_ids.add(file_id)
                except json.JSONDecodeError:
                    pass
            elif str(tag_value).strip() == mood_value:
                matching_file_ids.add(file_id)

    # Fetch genre distribution for matching files
    genre_rows = []
    artist_rows = []

    if matching_file_ids:
        placeholders = ",".join("?" * len(matching_file_ids))

        # Genre distribution
        genre_cursor = db.conn.execute(
            f"""
            SELECT genre, COUNT(*) as count
            FROM library_files
            WHERE id IN ({placeholders}) AND genre IS NOT NULL
            GROUP BY genre
            ORDER BY count DESC
            """,
            tuple(matching_file_ids),
        )
        genre_rows = genre_cursor.fetchall()

        # Artist distribution
        artist_cursor = db.conn.execute(
            f"""
            SELECT artist, COUNT(*) as count
            FROM library_files
            WHERE id IN ({placeholders}) AND artist IS NOT NULL
            GROUP BY artist
            ORDER BY count DESC
            """,
            tuple(matching_file_ids),
        )
        artist_rows = artist_cursor.fetchall()

    return {
        "mood_tag_rows": mood_tag_rows,
        "genre_rows": genre_rows,
        "artist_rows": artist_rows,
        "matching_file_ids": matching_file_ids,
        "mood_value": mood_value,
    }
