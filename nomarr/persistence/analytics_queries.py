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
            "nom_tag_rows": [(tag_key:tag_value, count), ...],  # e.g., ("mood-strict:happy", 150)
            "artist_rows": [(artist, count), ...],
            "genre_rows": [(genre, count), ...],
            "album_rows": [(album, count), ...]
        }
    """
    # Get total file count
    _, total_count = db.library_files.list_library_files(limit=1)

    # Count Nomarr tag VALUES (not keys) using normalized schema
    # For array tags, we need to expand them
    namespace_prefix = f"{namespace}:"

    # This query needs to handle both scalar and array tags
    # For array tags (type='array'), we store JSON arrays like ["happy", "energetic"]
    # We need to count frequency of each VALUE across all files
    cursor = db.conn.execute(
        """
        SELECT lt.key || ':' || lt.value as tag_key_value, COUNT(DISTINCT ft.file_id) as tag_count
        FROM file_tags ft
        JOIN library_tags lt ON lt.id = ft.tag_id
        WHERE lt.is_nomarr_tag = 1
          AND lt.type IN ('string', 'float', 'int')
        GROUP BY lt.key, lt.value
        ORDER BY tag_count DESC
        LIMIT ?
        """,
        (limit,),
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

    # Count genres from library_tags (genre is now a tag)
    genre_cursor = db.conn.execute(
        """
        SELECT lt.value, COUNT(DISTINCT ft.file_id) as count
        FROM file_tags ft
        JOIN library_tags lt ON lt.id = ft.tag_id
        WHERE lt.key = 'genre' AND lt.is_nomarr_tag = 0
        GROUP BY lt.value
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
    # Fetch mood tag data using normalized schema
    mood_tag_keys = ["mood-strict", "mood-regular", "mood-loose"]

    # Fetch all mood tag data (join file_tags -> library_tags)
    mood_tag_rows = []
    for tag_key in mood_tag_keys:
        cursor = db.conn.execute(
            """
            SELECT ft.file_id, lt.value, lt.type
            FROM file_tags ft
            JOIN library_tags lt ON lt.id = ft.tag_id
            WHERE lt.key = ? AND lt.is_nomarr_tag = 1
            """,
            (tag_key,),
        )
        mood_tag_rows.extend(cursor.fetchall())

    # Get all *_tier tag keys (Nomarr tags only)
    tier_cursor = db.conn.execute(
        """
        SELECT DISTINCT lt.key
        FROM library_tags lt
        WHERE lt.key LIKE ? AND lt.is_nomarr_tag = 1
        """,
        ("%_tier",),
    )
    tier_tag_keys = [row[0] for row in tier_cursor.fetchall()]

    # Fetch tier tag data for each key using normalized schema
    tier_tag_rows = {}
    for tier_tag_key in tier_tag_keys:
        cursor = db.conn.execute(
            """
            SELECT ft.file_id, lt.value
            FROM file_tags ft
            JOIN library_tags lt ON lt.id = ft.tag_id
            WHERE lt.key = ?
            """,
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

    # Fetch mood data using normalized schema
    for mood_type in ["mood-strict", "mood-regular", "mood-loose"]:
        cursor = db.conn.execute(
            """
            SELECT lt.value, lt.type
            FROM file_tags ft
            JOIN library_tags lt ON lt.id = ft.tag_id
            WHERE lt.key = ? AND lt.is_nomarr_tag = 1
            """,
            (mood_type,),
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
    files, file_count = db.library_files.list_library_files(artist=artist, limit=1000000)

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
            SELECT lt.key, lt.value, lt.type
            FROM file_tags ft
            JOIN library_tags lt ON lt.id = ft.tag_id
            WHERE ft.file_id IN ({placeholders})
              AND lt.is_nomarr_tag = 1
            """,
            (*batch_ids,),
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
    # Fetch mood tag data using normalized schema
    mood_tag_keys = ["mood-strict", "mood-regular", "mood-loose"]

    # Fetch all mood tag data and identify matching files
    mood_tag_rows = []
    matching_file_ids = set()

    mood_value_lower = mood_value.lower().strip()

    for tag_key in mood_tag_keys:
        cursor = db.conn.execute(
            """
            SELECT ft.file_id, lt.value, lt.type
            FROM file_tags ft
            JOIN library_tags lt ON lt.id = ft.tag_id
            WHERE lt.key = ? AND lt.is_nomarr_tag = 1
            """,
            (tag_key,),
        )

        for file_id, tag_value, tag_type in cursor.fetchall():
            mood_tag_rows.append((file_id, tag_value, tag_type))

            # Check if this file contains our mood_value (case-insensitive)
            if tag_type == "array":
                try:
                    moods = json.loads(tag_value)
                    if mood_value_lower in [str(m).strip().lower() for m in moods]:
                        matching_file_ids.add(file_id)
                except json.JSONDecodeError:
                    pass
            elif str(tag_value).strip().lower() == mood_value_lower:
                matching_file_ids.add(file_id)

    # Fetch genre distribution for matching files
    genre_rows = []
    artist_rows = []

    if matching_file_ids:
        placeholders = ",".join("?" * len(matching_file_ids))

        # Genre distribution from tags
        genre_cursor = db.conn.execute(
            f"""
            SELECT lt.value, COUNT(*) as count
            FROM file_tags ft
            JOIN library_tags lt ON lt.id = ft.tag_id
            WHERE ft.file_id IN ({placeholders})
              AND lt.key = 'genre'
            GROUP BY lt.value
            ORDER BY count DESC
            """,
            tuple(matching_file_ids),
        )
        genre_rows = genre_cursor.fetchall()

        # Artist distribution (still in library_files for performance)
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
