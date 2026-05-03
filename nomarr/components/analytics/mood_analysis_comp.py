"""Mood analysis analytics - coverage, balance, top pairs, dominant vibes."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any

from nomarr.components.analytics.analytics_comp import compute_dominant_vibes
from nomarr.components.tagging.tag_stats_comp import get_library_stats

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


_PAGE_SIZE = 1000
_MOOD_TAG_NAMES = ("nom:mood-strict", "nom:mood-regular", "nom:mood-loose")
_MOOD_TIER_MAP = {"strict": "nom:mood-strict", "regular": "nom:mood-regular", "loose": "nom:mood-loose"}


def _get_library_file_ids(db: Database, library_id: str | None) -> set[str] | None:
    """Return the allowed file-id set for a library scope when requested."""
    if library_id is None:
        return None

    file_ids: set[str] = set()
    offset = 0
    while True:
        file_docs = db.libraries.traversal(
            library_id,
            "library_contains_file",
            limit=_PAGE_SIZE,
            offset=offset,
        )
        if not file_docs:
            break
        for file_doc in file_docs:
            file_id = file_doc.get("_id")
            if isinstance(file_id, str):
                file_ids.add(file_id)
        if len(file_docs) < _PAGE_SIZE:
            break
        offset += len(file_docs)

    return file_ids


def _get_tag_docs_for_name(db: Database, name: str) -> list[dict[str, Any]]:
    """Return all tag documents for one tag name via constructor verbs."""
    tags: list[dict[str, Any]] = []
    offset = 0
    while True:
        tag_page = db.tags.name.get.many(name, limit=_PAGE_SIZE, offset=offset)
        if not tag_page:
            break
        tags.extend(tag_page)
        if len(tag_page) < _PAGE_SIZE:
            break
        offset += len(tag_page)

    return tags


def _get_tag_edge_rows(db: Database, name: str, library_id: str | None = None) -> list[tuple[str, str]]:
    """Return ``(file_id, tag_value)`` rows for one tag name."""
    library_file_ids = _get_library_file_ids(db, library_id)

    tag_docs = _get_tag_docs_for_name(db, name)
    tag_id_to_value: dict[str, str] = {}
    for tag_doc in tag_docs:
        tag_id = tag_doc.get("_id")
        tag_value = tag_doc.get("value")
        if isinstance(tag_id, str) and tag_value is not None:
            tag_id_to_value[tag_id] = str(tag_value)

    if not tag_id_to_value:
        return []

    # Fetch all song→tag edges for the entire tag name in a single IN query.
    edge_docs = db.song_has_tags._to.get.in_(list(tag_id_to_value))
    rows: list[tuple[str, str]] = []
    for edge_doc in edge_docs:
        file_id = edge_doc.get("_from")
        to_id = edge_doc.get("_to")
        if not isinstance(file_id, str) or to_id not in tag_id_to_value:
            continue
        if library_file_ids is not None and file_id not in library_file_ids:
            continue
        rows.append((file_id, tag_id_to_value[str(to_id)]))

    return rows


def _get_tier_tag_keys(db: Database) -> list[str]:
    """Return all distinct Nomarr tier tag names."""
    tier_tag_keys: list[str] = []
    seen: set[str] = set()
    offset = 0
    while True:
        name_page = db.tags.name.collect(limit=_PAGE_SIZE, offset=offset)
        if not name_page:
            break
        for name_value in name_page:
            name = str(name_value)
            if name.startswith("nom:") and name.endswith("_tier") and name not in seen:
                seen.add(name)
                tier_tag_keys.append(name)
        if len(name_page) < _PAGE_SIZE:
            break
        offset += len(name_page)

    return tier_tag_keys


def _count_moods(mood_values: list[str]) -> list[dict[str, Any]]:
    """Return descending mood counts, splitting parenthetical tuples."""
    mood_counts: dict[str, int] = {}
    for mood_value in mood_values:
        if mood_value.startswith("(") and mood_value.endswith(")"):
            inner = mood_value[1:-1]
            if inner:
                for part in inner.split(","):
                    cleaned = part.strip().strip("'\"")
                    if cleaned:
                        mood_counts[cleaned] = mood_counts.get(cleaned, 0) + 1
            continue
        mood_counts[mood_value] = mood_counts.get(mood_value, 0) + 1

    return [
        {"mood": mood, "count": count}
        for mood, count in sorted(mood_counts.items(), key=lambda item: item[1], reverse=True)
    ]


def get_mood_and_tier_tags_for_correlation(db: Database) -> dict[str, Any]:
    """Get raw mood and tier tag rows for correlation analysis.

    Args:
        db: Database instance used to query mood and tier tag edges.

    Returns:
        A dictionary with three keys: ``mood_tag_rows`` containing ``(song_id,
        tag_value)`` tuples for all mood-tag names across the strict,
        regular, and loose mood tiers; ``tier_tag_keys`` containing the tier
        tag names discovered in ``tags``; and ``tier_tag_rows`` containing
        a mapping from each tier tag name to its own list of ``(song_id,
        tag_value)`` tuples.
    """
    mood_tag_rows: list[tuple[str, str]] = []
    for name in _MOOD_TAG_NAMES:
        mood_tag_rows.extend(_get_tag_edge_rows(db, name))

    tier_tag_keys = _get_tier_tag_keys(db)
    tier_tag_rows: dict[str, list[tuple[str, str]]] = {}
    for tier_name in tier_tag_keys:
        tier_tag_rows[tier_name] = _get_tag_edge_rows(db, tier_name)

    return {"mood_tag_rows": mood_tag_rows, "tier_tag_keys": tier_tag_keys, "tier_tag_rows": tier_tag_rows}


def get_mood_distribution_data(db: Database, library_id: str | None = None) -> list[tuple[str, str]]:
    """Get raw mood rows for distribution analytics.

    Args:
        db: Database instance used to query mood tags.
        library_id: Optional library document ``_id``. When provided, only mood
            tags attached to files contained in that library are included.

    Returns:
        A list of ``(mood_name, tag_value)`` tuples. ``mood_name`` is one of
        ``"nom:mood-strict"``, ``"nom:mood-regular"``, or
        ``"nom:mood-loose"``, and ``tag_value`` is the stored mood tag value for
        one matching song-tag edge.
    """
    mood_rows: list[tuple[str, str]] = []
    for mood_type in _MOOD_TAG_NAMES:
        mood_rows.extend((mood_type, tag_value) for _, tag_value in _get_tag_edge_rows(db, mood_type, library_id))
    return mood_rows


def get_mood_coverage(db: Database, library_id: str | None = None) -> dict[str, Any]:
    """Get percentage of files tagged per mood tier.

    Args:
        db: Database instance used to query library and tag statistics.
        library_id: Optional library document ``_id``. When provided, coverage is
            calculated only for files contained in that library.

    Returns:
        A dictionary with ``total_files`` and ``tiers`` keys. ``total_files`` is
        the number of files considered, and ``tiers`` maps ``strict``,
        ``regular``, and ``loose`` to dictionaries containing ``tagged`` and
        ``percentage`` values for that tier.
    """
    stats = get_library_stats(db, library_id)
    total_files = int(stats["file_count"])
    if total_files == 0:
        return {
            "total_files": 0,
            "tiers": {
                "strict": {"tagged": 0, "percentage": 0.0},
                "regular": {"tagged": 0, "percentage": 0.0},
                "loose": {"tagged": 0, "percentage": 0.0},
            },
        }

    tiers: dict[str, dict[str, Any]] = {}
    for tier_name, name in _MOOD_TIER_MAP.items():
        tagged_count = len({file_id for file_id, _ in _get_tag_edge_rows(db, name, library_id)})
        tiers[tier_name] = {
            "tagged": tagged_count,
            "percentage": round((tagged_count / total_files) * 100, 1) if total_files > 0 else 0.0,
        }

    return {"total_files": total_files, "tiers": tiers}


def get_mood_balance(db: Database, library_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """Get mood-value distribution across tiers.

    Args:
        db: Database instance used to query mood tags.
        library_id: Optional library document ``_id``. When provided, only mood
            tags attached to files contained in that library are counted.

    Returns:
        A dictionary keyed by the tier names ``strict``, ``regular``, and
        ``loose``. Each value is a list of dictionaries sorted by descending
        count, where every dictionary contains ``mood`` and ``count`` keys for a
        single parsed mood value.
    """
    result: dict[str, list[dict[str, Any]]] = {}
    for tier_name, name in _MOOD_TIER_MAP.items():
        mood_values = [mood_value for _, mood_value in _get_tag_edge_rows(db, name, library_id)]
        result[tier_name] = _count_moods(mood_values)
    return result


def get_top_mood_pairs(
    db: Database,
    library_id: str | None = None,
    limit: int = 10,
    mood_tier: str = "strict",
) -> list[dict[str, Any]]:
    """Get the most common co-occurring mood pairs for one tier.

    Args:
        db: Database instance used to query co-occurring mood tags.
        library_id: Optional library document ``_id``. When provided, only files
            contained in that library are considered.
        limit: Maximum number of mood-pair rows to return.
        mood_tier: Mood tier selector. ``"strict"`` uses only strict mood tags,
            ``"regular"`` uses both strict and regular mood tags, and
            ``"loose"`` uses strict, regular, and loose mood tags. Any other
            value falls back to the strict tier only.

    Returns:
        A list of dictionaries describing the most common co-occurring mood
        pairs. Each dictionary contains ``mood1``, ``mood2``, and ``count``
        keys.
    """
    tier_hierarchy: dict[str, list[str]] = {
        "strict": ["nom:mood-strict"],
        "regular": ["nom:mood-strict", "nom:mood-regular"],
        "loose": ["nom:mood-strict", "nom:mood-regular", "nom:mood-loose"],
    }
    names = tier_hierarchy.get(mood_tier, ["nom:mood-strict"])
    moods_by_song: dict[str, set[str]] = {}
    for name in names:
        for file_id, mood_value in _get_tag_edge_rows(db, name, library_id):
            if not mood_value:
                continue
            moods_by_song.setdefault(file_id, set()).add(mood_value)

    pair_counts: Counter[tuple[str, str]] = Counter()
    for moods in moods_by_song.values():
        ordered_moods = sorted(moods)
        if len(ordered_moods) < 2:
            continue
        for first_index, mood1 in enumerate(ordered_moods[:-1]):
            for mood2 in ordered_moods[first_index + 1 :]:
                pair_counts[(mood1, mood2)] += 1

    return [
        {"mood1": mood1, "mood2": mood2, "count": count}
        for (mood1, mood2), count in sorted(
            pair_counts.items(),
            key=lambda item: (-item[1], item[0][0], item[0][1]),
        )[:limit]
    ]


def compute_mood_analysis(
    db: Database,
    library_id: str | None = None,
) -> dict[str, Any]:
    """Get mood analysis: coverage, balance, top pairs, dominant vibes.

    Args:
        db: Database instance.
        library_id: Optional library _id to filter by.

    Returns:
        Dict with: coverage, balance, top_pairs_by_tier, dominant_vibes
    """
    # Mood coverage (% tagged per tier)
    coverage = get_mood_coverage(db, library_id)

    # Mood balance (value distribution per tier)
    balance = get_mood_balance(db, library_id)

    # Top mood pairs for all three tiers
    top_pairs_by_tier = {
        tier: get_top_mood_pairs(db, library_id, mood_tier=tier, limit=50) for tier in ("strict", "regular", "loose")
    }

    # Dominant vibes from balance data
    dominant_vibes = compute_dominant_vibes(balance)

    return {
        "coverage": coverage,
        "balance": balance,
        "top_pairs_by_tier": top_pairs_by_tier,
        "dominant_vibes": dominant_vibes,
    }
