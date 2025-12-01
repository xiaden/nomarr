"""
Analytics computation functions - pure data processing for tag statistics.

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
from collections.abc import Sequence

from nomarr.helpers.dto.analytics_dto import (
    ArtistTagProfile,
    ComputeArtistTagProfileParams,
    ComputeMoodValueCoOccurrencesParams,
    ComputeTagCorrelationMatrixParams,
    ComputeTagFrequenciesParams,
    ComputeTagFrequenciesResult,
    MoodCoOccurrenceData,
    MoodDistributionData,
    TagCorrelationData,
)

# ──────────────────────────────────────────────────────────────────────
# Analytics Computation Functions
# ──────────────────────────────────────────────────────────────────────


def compute_tag_frequencies(
    params: ComputeTagFrequenciesParams,
) -> ComputeTagFrequenciesResult:
    """
    Compute frequency counts from raw tag data.

    Args:
        params: Input parameters with namespace prefix, file count, and tag rows

    Returns:
        ComputeTagFrequenciesResult with nom_tags, standard_tags, total_files
    """
    logging.info("[analytics] Computing tag frequencies")

    # Format results (remove namespace prefix)
    nom_tag_counts = [(tag_key.replace(params.namespace_prefix, ""), count) for tag_key, count in params.nom_tag_rows]

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
    """
    Compute VALUE-based correlation matrix from raw tag data.

    Args:
        params: Parameters containing namespace, top_n, and tag data

    Returns:
        TagCorrelationData with mood-to-mood and mood-to-tier correlations
    """
    logging.info(f"[analytics] Computing VALUE-based correlation matrix (top {params.top_n} moods)")

    # Extract mood values and count occurrences
    mood_counter: Counter = Counter()
    for _file_id, tag_value, tag_type in params.mood_tag_rows:
        if tag_type == "array":
            try:
                moods = json.loads(tag_value)
                for mood in moods:
                    mood_counter[str(mood).strip()] += 1
            except json.JSONDecodeError:
                # TODO [LOGGING]
                pass
        else:
            mood_counter[str(tag_value).strip()] += 1

    top_moods = [mood for mood, _ in mood_counter.most_common(params.top_n)]

    if not top_moods:
        return TagCorrelationData(
            mood_correlations={},
            mood_tier_correlations={},
        )

    # Build file sets for each mood value
    mood_file_sets: dict[str, set[int]] = {mood: set() for mood in top_moods}

    for file_id, tag_value, tag_type in params.mood_tag_rows:
        if tag_type == "array":
            try:
                moods = json.loads(tag_value)
                for mood in moods:
                    mood_str = str(mood).strip()
                    if mood_str in mood_file_sets:
                        mood_file_sets[mood_str].add(file_id)
            except json.JSONDecodeError:
                # TODO [LOGGING]
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
    mood_rows: Sequence[tuple[str, str, str]],
) -> MoodDistributionData:
    """
    Compute mood distribution from raw mood tag data.

    Args:
        mood_rows: List of (mood_type, tag_value, tag_type) tuples

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

    for mood_type, tag_value, tag_type in mood_rows:
        counter = counter_map.get(mood_type)
        if not counter:
            continue

        if tag_type == "array":
            try:
                moods = json.loads(tag_value)
                for mood in moods:
                    counter[str(mood).strip()] += 1
            except json.JSONDecodeError:
                pass
        else:
            counter[tag_value.strip()] += 1

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
    """
    Compute tag profile for an artist from raw tag data.

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

    for tag_key, tag_value, tag_type in params.tag_rows:
        tag_name = tag_key.replace(params.namespace_prefix, "")

        if tag_name in ["mood-strict", "mood-regular", "mood-loose"]:
            if tag_type == "array":
                try:
                    moods = json.loads(tag_value)
                    for mood in moods:
                        mood_counts[str(mood).strip()] += 1
                except json.JSONDecodeError:
                    # TODO [LOGGING]
                    pass
            else:
                mood_counts[tag_value.strip()] += 1
        else:
            tag_counts[tag_name] += 1
            if tag_type in ("float", "int"):
                try:
                    numeric_value = float(tag_value)
                    tag_values[tag_name].append(numeric_value)
                except ValueError:
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


def compute_mood_value_co_occurrences(
    params: ComputeMoodValueCoOccurrencesParams,
) -> MoodCoOccurrenceData:
    """
    Compute mood value co-occurrence statistics from raw data.

    Args:
        params: Parameters containing mood value, file IDs, and distribution data

    Returns:
        MoodCoOccurrenceData with co-occurrence patterns and distributions
    """
    logging.info(f"[analytics] Computing mood value co-occurrences for: {params.mood_value}")

    total_occurrences = len(params.matching_file_ids)

    if total_occurrences == 0:
        return MoodCoOccurrenceData(
            mood_value=params.mood_value,
            total_occurrences=0,
            mood_co_occurrences=[],
            genre_distribution=[],
            artist_distribution=[],
        )

    mood_counter: Counter = Counter()

    for file_id, tag_value, tag_type in params.mood_tag_rows:
        if file_id not in params.matching_file_ids:
            continue

        if tag_type == "array":
            try:
                moods = json.loads(tag_value)
                for mood in moods:
                    mood_str = str(mood).strip()
                    if mood_str != params.mood_value:
                        mood_counter[mood_str] += 1
            except json.JSONDecodeError:
                # TODO [LOGGING]
                pass
        else:
            mood_str = str(tag_value).strip()
            if mood_str != params.mood_value:
                mood_counter[mood_str] += 1

    mood_co_occurrences = [
        (mood, count, round((count / total_occurrences) * 100, 1))
        for mood, count in mood_counter.most_common(params.limit)
    ]

    genre_distribution = [
        (genre, count, round((count / total_occurrences) * 100, 1))
        for genre, count in params.genre_rows[: params.limit]
    ]

    artist_distribution = [
        (artist, count, round((count / total_occurrences) * 100, 1))
        for artist, count in params.artist_rows[: params.limit]
    ]

    return MoodCoOccurrenceData(
        mood_value=params.mood_value,
        total_occurrences=total_occurrences,
        mood_co_occurrences=mood_co_occurrences,
        genre_distribution=genre_distribution,
        artist_distribution=artist_distribution,
    )
