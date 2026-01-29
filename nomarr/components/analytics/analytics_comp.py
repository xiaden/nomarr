"""Analytics computation functions - pure data processing for tag statistics.

PURE LEAF-DOMAIN - These functions operate on in-memory data only:
- Take raw data (rows, dicts, lists) as input
- Perform ONLY aggregation and transformation logic
- Return structured results for presentation layers
- Do NOT import nomarr.persistence, nomarr.services, nomarr.workflows, or nomarr.interfaces
- Do NOT access databases or execute SQL

ARCHITECTURE:
- Analytics is a pure computation layer
- Data is provided by persistence layer (nomarr.persistence.analytics_queries)
- Services/workflows orchestrate: fetch data from persistence, pass to analytics
- Interfaces call services, not analytics directly
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from typing import TYPE_CHECKING

from nomarr.helpers.dto.analytics_dto import (
    ArtistTagProfile,
    ComputeArtistTagProfileParams,
    ComputeTagCoOccurrenceParams,
    ComputeTagCorrelationMatrixParams,
    ComputeTagFrequenciesParams,
    ComputeTagFrequenciesResult,
    MoodDistributionData,
    TagCoOccurrenceData,
    TagCorrelationData,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

# ──────────────────────────────────────────────────────────────────────
# Analytics Computation Functions
# ──────────────────────────────────────────────────────────────────────


def compute_tag_frequencies(
    params: ComputeTagFrequenciesParams,
) -> ComputeTagFrequenciesResult:
    """Compute frequency counts from raw tag data.

    Input tag rows are already in "key:value" format (e.g., "mood-strict:happy").
    This function just passes them through with minimal processing.

    Args:
        params: Input parameters with namespace prefix, file count, and tag rows

    Returns:
        ComputeTagFrequenciesResult with nom_tags (as key:value), standard_tags, total_files

    """
    logging.info("[analytics] Computing tag frequencies")

    # Tag rows are already in "key:value" format from persistence layer
    # Just convert to list format (no prefix stripping needed)
    nom_tag_counts = list(params.nom_tag_rows)

    return ComputeTagFrequenciesResult(
        nom_tags=nom_tag_counts,
        standard_tags={
            "artists": list(params.artist_rows),
            "genres": list(params.genre_rows),
            "albums": list(params.album_rows),
        },
        total_files=params.total_files,
    )


def compute_tag_correlation_matrix(
    params: ComputeTagCorrelationMatrixParams,
) -> TagCorrelationData:
    """Compute VALUE-based correlation matrix from raw tag data.

    Args:
        params: Parameters containing namespace, top_n, and tag data

    Returns:
        TagCorrelationData with mood-to-mood and mood-to-tier correlations

    """
    logging.info(f"[analytics] Computing VALUE-based correlation matrix (top {params.top_n} moods)")

    # Extract mood values and count occurrences (all values are JSON arrays now)
    mood_counter: Counter = Counter()
    for _file_id, tag_value in params.mood_tag_rows:
        try:
            moods = json.loads(tag_value)
            if isinstance(moods, list):
                for mood in moods:
                    mood_counter[str(mood).strip()] += 1
        except json.JSONDecodeError:
            pass

    top_moods = [mood for mood, _ in mood_counter.most_common(params.top_n)]

    if not top_moods:
        return TagCorrelationData(
            mood_correlations={},
            mood_tier_correlations={},
        )

    # Build file sets for each mood value
    mood_file_sets: dict[str, set[int]] = {mood: set() for mood in top_moods}

    for file_id, tag_value in params.mood_tag_rows:
        try:
            moods = json.loads(tag_value)
            if isinstance(moods, list):
                for mood in moods:
                    mood_str = str(mood).strip()
                    if mood_str in mood_file_sets:
                        mood_file_sets[mood_str].add(file_id)
        except json.JSONDecodeError:
            pass

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

        top_correlations = sorted(correlations.items(), key=lambda x: x[1], reverse=True)[:10]
        mood_correlations[mood_a] = dict(top_correlations)

    # 2. MOOD-TO-TIER CORRELATIONS
    mood_tier_correlations: dict[str, dict[str, float]] = {}

    for mood in top_moods:
        mood_files = mood_file_sets[mood]
        if not mood_files:
            continue

        tier_correlations: dict[str, float] = {}

        for tier_tag_key in params.tier_tag_keys:
            tier_name = tier_tag_key.replace(f"{params.namespace}:", "").replace("_tier", "").split("_")[-1]
            tier_value_counts: Counter = Counter()
            for file_id, tier_value in params.tier_tag_rows.get(tier_tag_key, []):
                if file_id in mood_files:
                    tier_value_counts[tier_value] += 1

            for tier_value, count in tier_value_counts.items():
                correlation_key = f"{tier_value}_{tier_name}"
                tier_correlations[correlation_key] = round(count / len(mood_files), 3)

        top_tiers = sorted(tier_correlations.items(), key=lambda x: x[1], reverse=True)[:10]
        mood_tier_correlations[mood] = dict(top_tiers)

    return TagCorrelationData(
        mood_correlations=mood_correlations,
        mood_tier_correlations=mood_tier_correlations,
    )


def compute_mood_distribution(
    mood_rows: Sequence[tuple[str, str]],
) -> MoodDistributionData:
    """Compute mood distribution from raw mood tag data.

    All tag values are now stored as JSON arrays.

    Args:
        mood_rows: List of (mood_type, tag_value) tuples where tag_value is JSON array string

    Returns:
        MoodDistributionData with mood tier distributions and top moods

    """
    logging.info("[analytics] Computing mood distribution")

    mood_strict_counts: Counter = Counter()
    mood_regular_counts: Counter = Counter()
    mood_loose_counts: Counter = Counter()

    counter_map = {
        "mood-strict": mood_strict_counts,
        "mood-regular": mood_regular_counts,
        "mood-loose": mood_loose_counts,
    }

    for mood_type, tag_value in mood_rows:
        counter = counter_map.get(mood_type)
        if not counter:
            continue

        # All values are JSON arrays now
        try:
            moods = json.loads(tag_value)
            if isinstance(moods, list):
                for mood in moods:
                    counter[str(mood).strip()] += 1
        except json.JSONDecodeError:
            pass

    all_moods: Counter = Counter()
    all_moods.update(mood_strict_counts)
    all_moods.update(mood_regular_counts)
    all_moods.update(mood_loose_counts)

    return MoodDistributionData(
        mood_strict=dict(mood_strict_counts.most_common(20)),
        mood_regular=dict(mood_regular_counts.most_common(20)),
        mood_loose=dict(mood_loose_counts.most_common(20)),
        top_moods=all_moods.most_common(30),
    )


def compute_artist_tag_profile(
    params: ComputeArtistTagProfileParams,
) -> ArtistTagProfile:
    """Compute tag profile for an artist from raw tag data.

    Args:
        params: Parameters containing artist info, namespace, and tag data

    Returns:
        ArtistTagProfile with artist info, top tags, and mood statistics

    """
    logging.info(f"[analytics] Computing tag profile for artist: {params.artist}")

    if params.file_count == 0:
        return ArtistTagProfile(
            artist=params.artist,
            file_count=0,
            top_tags=[],
            moods=[],
            avg_tags_per_file=0.0,
        )

    tag_counts: Counter = Counter()
    tag_values: dict[str, list[float]] = defaultdict(list)
    mood_counts: Counter = Counter()

    for tag_key, tag_value in params.tag_rows:
        tag_name = tag_key.replace(params.namespace_prefix, "")

        # All values are JSON arrays now
        try:
            values = json.loads(tag_value)
            if not isinstance(values, list):
                continue

            if tag_name in ["mood-strict", "mood-regular", "mood-loose"]:
                # Process mood tags
                for mood in values:
                    mood_counts[str(mood).strip()] += 1
            else:
                # Process other tags
                tag_counts[tag_name] += 1
                # Try to extract numeric values
                for tag_value in values:
                    try:
                        numeric_value = float(tag_value)
                        tag_values[tag_name].append(numeric_value)
                    except (ValueError, TypeError):
                        pass
        except json.JSONDecodeError:
            pass

    top_tags = []
    for tag, count in tag_counts.most_common(params.limit):
        values = tag_values.get(tag)
        avg_value = sum(values) / len(values) if values else 0.0
        top_tags.append((tag, count, avg_value))

    total_non_mood_tags = sum(
        count for tag, count in tag_counts.items() if tag not in ["mood-strict", "mood-regular", "mood-loose"]
    )

    return ArtistTagProfile(
        artist=params.artist,
        file_count=params.file_count,
        top_tags=top_tags,
        moods=mood_counts.most_common(15),
        avg_tags_per_file=total_non_mood_tags / params.file_count if params.file_count else 0.0,
    )


def compute_tag_co_occurrence(
    params: ComputeTagCoOccurrenceParams,
) -> TagCoOccurrenceData:
    """Compute tag co-occurrence matrix from tag file sets.

    Builds a matrix where matrix[j][i] = count of files having both x_tags[i] and y_tags[j].

    Args:
        params: Parameters containing X/Y tag specs and file ID mappings

    Returns:
        TagCoOccurrenceData with X/Y tags and co-occurrence matrix

    """
    logging.info(f"[analytics] Computing tag co-occurrence matrix: {len(params.x_tags)}x{len(params.y_tags)}")

    # Build the matrix: matrix[j][i] = intersection of y_tags[j] and x_tags[i] file sets
    matrix: list[list[int]] = []

    for y_tag in params.y_tags:
        row: list[int] = []
        y_key = (y_tag.key, y_tag.value)
        y_files = params.tag_data.get(y_key, set())

        for x_tag in params.x_tags:
            x_key = (x_tag.key, x_tag.value)
            x_files = params.tag_data.get(x_key, set())

            # Count files in both sets
            intersection_count = len(y_files & x_files)
            row.append(intersection_count)

        matrix.append(row)

    return TagCoOccurrenceData(
        x_tags=params.x_tags,
        y_tags=params.y_tags,
        matrix=matrix,
    )
