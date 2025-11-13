"""
Analytics engine for tag statistics, co-occurrences, and correlations.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from typing import Any

from nomarr.data.db import Database


def get_tag_frequencies(db: Database, namespace: str = "nom", limit: int = 50) -> dict[str, Any]:
    """
    Get frequency counts for all tags in the library.

    Returns:
        {
            "nom_tags": [(tag_name, count), ...],  # Tags without namespace prefix
            "standard_tags": {
                "artists": [(artist, count), ...],
                "genres": [(genre, count), ...],
                "albums": [(album, count), ...]
            },
            "total_files": int
        }
    """
    logging.info("[analytics] Computing tag frequencies")

    # Get all library files for total count
    _, total_count = db.list_library_files(limit=1)

    # Count tags using library_tags table (FAST - no JSON parsing)
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

    # Format results (remove namespace prefix)
    nom_tag_counts = [(tag_key.replace(namespace_prefix, ""), count) for tag_key, count in cursor.fetchall()]

    # Count standard metadata (still needs library_files table)
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
    artist_counts = artist_cursor.fetchall()

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
    genre_counts = genre_cursor.fetchall()

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
    album_counts = album_cursor.fetchall()

    return {
        "nom_tags": nom_tag_counts,
        "standard_tags": {
            "artists": artist_counts,
            "genres": genre_counts,
            "albums": album_counts,
        },
        "total_files": total_count,
    }


def get_tag_correlation_matrix(
    db: Database,
    namespace: str = "nom",
    top_n: int = 20,
) -> dict[str, Any]:
    """
    Compute VALUE-based correlation matrix for mood values, genres, and tier tags.

    This analyzes actual tag VALUES (e.g., "happy", "Rock", "high") not tag keys.
    Returns co-occurrence patterns between:
    - Mood values (from mood-strict/regular/loose)
    - Genre values
    - Tier values (e.g., "high", "medium", "low" from *_tier tags)

    Returns:
        {
            "mood_correlations": {
                "happy": {"energetic": 0.75, "dark": 0.05, ...},
                "dark": {"aggressive": 0.60, ...}
            },
            "mood_genre_correlations": {
                "happy": {"Pop": 0.40, "Rock": 0.30, ...},
                "dark": {"Metal": 0.50, ...}
            },
            "mood_tier_correlations": {
                "happy": {"high_energy": 0.80, "high_danceability": 0.65, ...},
                "dark": {"low_valence": 0.70, ...}
            }
        }

    Matrix values are conditional probability: P(B|A) = files with both / files with A
    """
    logging.info(f"[analytics] Computing VALUE-based correlation matrix (top {top_n} moods)")

    # Get top N mood values across all mood tiers
    mood_counter: Counter = Counter()
    mood_tag_keys = [
        f"{namespace}:mood-strict",
        f"{namespace}:mood-regular",
        f"{namespace}:mood-loose",
    ]

    for tag_key in mood_tag_keys:
        cursor = db.conn.execute(
            "SELECT tag_value, tag_type FROM library_tags WHERE tag_key = ?",
            (tag_key,),
        )
        for tag_value, tag_type in cursor.fetchall():
            if tag_type == "array":
                try:
                    moods = json.loads(tag_value)
                    for mood in moods:
                        mood_counter[str(mood).strip()] += 1
                except json.JSONDecodeError:
                    pass
            else:
                mood_counter[str(tag_value).strip()] += 1

    top_moods = [mood for mood, _ in mood_counter.most_common(top_n)]

    if not top_moods:
        return {
            "mood_correlations": {},
            "mood_genre_correlations": {},
            "mood_tier_correlations": {},
        }

    # Build file sets for each mood value (for fast intersection)
    mood_file_sets: dict[str, set[int]] = {mood: set() for mood in top_moods}

    for tag_key in mood_tag_keys:
        cursor = db.conn.execute(
            "SELECT file_id, tag_value, tag_type FROM library_tags WHERE tag_key = ?",
            (tag_key,),
        )
        for file_id, tag_value, tag_type in cursor.fetchall():
            if tag_type == "array":
                try:
                    moods = json.loads(tag_value)
                    for mood in moods:
                        mood_str = str(mood).strip()
                        if mood_str in mood_file_sets:
                            mood_file_sets[mood_str].add(file_id)
                except json.JSONDecodeError:
                    pass
            else:
                mood_str = str(tag_value).strip()
                if mood_str in mood_file_sets:
                    mood_file_sets[mood_str].add(file_id)

    # 1. MOOD-TO-MOOD CORRELATIONS
    mood_correlations: dict[str, dict[str, float]] = {}
    for mood_a in top_moods:
        files_a = mood_file_sets[mood_a]
        if not files_a:
            continue

        correlations: dict[str, float] = {}
        for mood_b in top_moods:
            if mood_a == mood_b:
                continue
            files_b = mood_file_sets[mood_b]
            intersection = len(files_a & files_b)
            if files_a:
                correlations[mood_b] = round(intersection / len(files_a), 3)

        # Only include top correlations to reduce noise
        top_correlations = sorted(correlations.items(), key=lambda x: x[1], reverse=True)[:10]
        mood_correlations[mood_a] = dict(top_correlations)

    # 2. MOOD-TO-GENRE CORRELATIONS
    mood_genre_correlations: dict[str, dict[str, float]] = {}
    for mood in top_moods:
        mood_files = mood_file_sets[mood]
        if not mood_files:
            continue

        # Get genre distribution for files with this mood
        placeholders = ",".join("?" * len(mood_files))
        cursor = db.conn.execute(
            f"SELECT genre, COUNT(*) FROM library_files WHERE id IN ({placeholders}) AND genre IS NOT NULL GROUP BY genre",
            tuple(mood_files),
        )

        genre_counts = {}
        for genre, count in cursor.fetchall():
            genre_counts[genre] = round(count / len(mood_files), 3)

        # Top 5 genres per mood
        top_genres = sorted(genre_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        mood_genre_correlations[mood] = dict(top_genres)

    # 3. MOOD-TO-TIER CORRELATIONS (e.g., happy → high_energy)
    mood_tier_correlations: dict[str, dict[str, float]] = {}

    # Get all *_tier tags
    tier_cursor = db.conn.execute(
        "SELECT DISTINCT tag_key FROM library_tags WHERE tag_key LIKE ? AND tag_key LIKE ?",
        (f"{namespace}:%", "%_tier"),
    )
    tier_tag_keys = [row[0] for row in tier_cursor.fetchall()]

    for mood in top_moods:
        mood_files = mood_file_sets[mood]
        if not mood_files:
            continue

        tier_correlations: dict[str, float] = {}

        for tier_tag_key in tier_tag_keys:
            # Extract base tag name (e.g., "effnet_energy_tier" → "energy")
            tier_name = tier_tag_key.replace(f"{namespace}:", "").replace("_tier", "").split("_")[-1]

            # Count tier values for this mood's files
            placeholders = ",".join("?" * len(mood_files))
            cursor = db.conn.execute(
                f"SELECT tag_value, COUNT(*) FROM library_tags WHERE tag_key = ? AND file_id IN ({placeholders}) GROUP BY tag_value",
                (tier_tag_key, *mood_files),
            )

            for tier_value, count in cursor.fetchall():
                # Create descriptive correlation key (e.g., "high_energy", "low_valence")
                correlation_key = f"{tier_value}_{tier_name}"
                tier_correlations[correlation_key] = round(count / len(mood_files), 3)

        # Top 10 tier correlations per mood
        top_tiers = sorted(tier_correlations.items(), key=lambda x: x[1], reverse=True)[:10]
        mood_tier_correlations[mood] = dict(top_tiers)

    return {
        "mood_correlations": mood_correlations,
        "mood_genre_correlations": mood_genre_correlations,
        "mood_tier_correlations": mood_tier_correlations,
    }


def get_mood_distribution(db: Database, namespace: str = "nom") -> dict[str, Any]:
    """
    Get distribution of mood tags across the library.

    Returns:
        {
            "mood_strict": {mood: count, ...},
            "mood_regular": {mood: count, ...},
            "mood_loose": {mood: count, ...},
            "top_moods": [(mood, count), ...]
        }
    """
    logging.info("[analytics] Computing mood distribution")

    mood_strict_counts: Counter = Counter()
    mood_regular_counts: Counter = Counter()
    mood_loose_counts: Counter = Counter()

    # Query each mood type from library_tags (FAST - indexed)
    for mood_type, counter in [
        ("mood-strict", mood_strict_counts),
        ("mood-regular", mood_regular_counts),
        ("mood-loose", mood_loose_counts),
    ]:
        tag_key = f"{namespace}:{mood_type}"
        cursor = db.conn.execute(
            "SELECT tag_value, tag_type FROM library_tags WHERE tag_key = ?",
            (tag_key,),
        )

        for tag_value, tag_type in cursor.fetchall():
            # Handle arrays (multi-value moods)
            if tag_type == "array":
                try:
                    moods = json.loads(tag_value)
                    for mood in moods:
                        counter[str(mood).strip()] += 1
                except json.JSONDecodeError:
                    pass
            else:
                # Single mood value
                counter[tag_value.strip()] += 1

    # Combine all moods for top list
    all_moods: Counter = Counter()
    all_moods.update(mood_strict_counts)
    all_moods.update(mood_regular_counts)
    all_moods.update(mood_loose_counts)

    return {
        "mood_strict": dict(mood_strict_counts.most_common(20)),
        "mood_regular": dict(mood_regular_counts.most_common(20)),
        "mood_loose": dict(mood_loose_counts.most_common(20)),
        "top_moods": all_moods.most_common(30),
    }


def get_artist_tag_profile(
    db: Database,
    artist: str,
    namespace: str = "nom",
    limit: int = 20,
) -> dict[str, Any]:
    """
    Get tag profile for a specific artist.

    Returns:
        {
            "artist": artist_name,
            "file_count": int,
            "top_tags": [(tag, count, avg_value), ...],
            "moods": [(mood, count), ...],
            "avg_tags_per_file": float
        }
    """
    logging.info(f"[analytics] Computing tag profile for artist: {artist}")

    # Get files for this artist
    files, file_count = db.list_library_files(artist=artist, limit=1000000)

    if file_count == 0:
        return {
            "artist": artist,
            "file_count": 0,
            "top_tags": [],
            "moods": [],
            "avg_tags_per_file": 0.0,
        }

    # Get file IDs
    file_ids = [f["id"] for f in files]

    # Query tags for these files (FAST - indexed query with IN clause)
    tag_counts: Counter = Counter()
    tag_values: defaultdict = defaultdict(list)
    mood_counts: Counter = Counter()

    # Use batched queries for large artist catalogs
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

        for tag_key, tag_value, tag_type in cursor.fetchall():
            tag_name = tag_key.replace(f"{namespace}:", "")

            # Handle mood tags separately
            if tag_name in ["mood-strict", "mood-regular", "mood-loose"]:
                if tag_type == "array":
                    try:
                        moods = json.loads(tag_value)
                        for mood in moods:
                            mood_counts[str(mood).strip()] += 1
                    except json.JSONDecodeError:
                        pass
                else:
                    mood_counts[tag_value.strip()] += 1
            else:
                # Regular tags
                tag_counts[tag_name] += 1

                # Try to extract numeric value
                if tag_type in ("float", "int"):
                    try:
                        numeric_value = float(tag_value)
                        tag_values[tag_name].append(numeric_value)
                    except ValueError:
                        pass

    # Compute averages
    top_tags = []
    for tag, count in tag_counts.most_common(limit):
        values = tag_values.get(tag)
        if values:
            avg_value = sum(values) / len(values)
        else:
            avg_value = 0.0
        top_tags.append((tag, count, avg_value))

    # Calculate avg tags per file (excluding mood tags)
    total_non_mood_tags = sum(
        count for tag, count in tag_counts.items() if tag not in ["mood-strict", "mood-regular", "mood-loose"]
    )

    return {
        "artist": artist,
        "file_count": file_count,
        "top_tags": top_tags,
        "moods": mood_counts.most_common(15),
        "avg_tags_per_file": total_non_mood_tags / file_count if file_count else 0.0,
    }


def get_mood_value_co_occurrences(
    db: Database,
    mood_value: str,
    namespace: str = "nom",
    limit: int = 20,
) -> dict[str, Any]:
    """
    Get co-occurrence statistics for a specific mood VALUE (not tag key).
    Shows which other mood values and genres appear with this mood.

    Args:
        db: Database instance
        mood_value: Mood value to analyze (e.g., "happy", "aggressive")
        namespace: Tag namespace
        limit: Max results per category

    Returns:
        {
            "mood_value": str,
            "total_occurrences": int,
            "mood_co_occurrences": [(mood, count, percentage), ...],
            "genre_distribution": [(genre, count, percentage), ...],
            "artist_distribution": [(artist, count, percentage), ...]
        }
    """
    logging.info(f"[analytics] Computing mood value co-occurrences for: {mood_value}")

    # Find all files that have this mood value in ANY mood tier (strict/regular/loose)
    # Mood values are stored as JSON arrays in library_tags
    mood_tag_keys = [
        f"{namespace}:mood-strict",
        f"{namespace}:mood-regular",
        f"{namespace}:mood-loose",
    ]

    # Get file IDs that contain this mood value
    file_ids = set()
    for tag_key in mood_tag_keys:
        cursor = db.conn.execute(
            "SELECT file_id, tag_value, tag_type FROM library_tags WHERE tag_key = ?",
            (tag_key,),
        )

        for file_id, tag_value, tag_type in cursor.fetchall():
            if tag_type == "array":
                try:
                    moods = json.loads(tag_value)
                    if mood_value in [str(m).strip() for m in moods]:
                        file_ids.add(file_id)
                except json.JSONDecodeError:
                    pass
            elif str(tag_value).strip() == mood_value:
                file_ids.add(file_id)

    total_occurrences = len(file_ids)

    if total_occurrences == 0:
        return {
            "mood_value": mood_value,
            "total_occurrences": 0,
            "mood_co_occurrences": [],
            "genre_distribution": [],
            "artist_distribution": [],
        }

    # Get co-occurring mood values
    mood_counter: Counter = Counter()
    for tag_key in mood_tag_keys:
        cursor = db.conn.execute(
            "SELECT file_id, tag_value, tag_type FROM library_tags WHERE tag_key = ? AND file_id IN ({})".format(
                ",".join("?" * len(file_ids))
            ),
            (tag_key, *file_ids),
        )

        for _, tag_value, tag_type in cursor.fetchall():
            if tag_type == "array":
                try:
                    moods = json.loads(tag_value)
                    for mood in moods:
                        mood_str = str(mood).strip()
                        if mood_str != mood_value:  # Exclude self
                            mood_counter[mood_str] += 1
                except json.JSONDecodeError:
                    pass
            else:
                mood_str = str(tag_value).strip()
                if mood_str != mood_value:
                    mood_counter[mood_str] += 1

    mood_co_occurrences = [
        (mood, count, round((count / total_occurrences) * 100, 1)) for mood, count in mood_counter.most_common(limit)
    ]

    # Get genre distribution
    genre_cursor = db.conn.execute(
        "SELECT genre, COUNT(*) as count FROM library_files WHERE id IN ({}) AND genre IS NOT NULL GROUP BY genre ORDER BY count DESC LIMIT ?".format(
            ",".join("?" * len(file_ids))
        ),
        (*file_ids, limit),
    )
    genre_distribution = [
        (genre, count, round((count / total_occurrences) * 100, 1)) for genre, count in genre_cursor.fetchall()
    ]

    # Get artist distribution
    artist_cursor = db.conn.execute(
        "SELECT artist, COUNT(*) as count FROM library_files WHERE id IN ({}) AND artist IS NOT NULL GROUP BY artist ORDER BY count DESC LIMIT ?".format(
            ",".join("?" * len(file_ids))
        ),
        (*file_ids, limit),
    )
    artist_distribution = [
        (artist, count, round((count / total_occurrences) * 100, 1)) for artist, count in artist_cursor.fetchall()
    ]

    return {
        "mood_value": mood_value,
        "total_occurrences": total_occurrences,
        "mood_co_occurrences": mood_co_occurrences,
        "genre_distribution": genre_distribution,
        "artist_distribution": artist_distribution,
    }
