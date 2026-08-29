"""Mood analysis analytics - coverage, balance, top pairs, dominant vibes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

from nomarr.components.analytics.analytics_comp import DominantVibeResult, compute_dominant_vibes
from nomarr.components.library.library_song_query_comp import get_library_stats

if TYPE_CHECKING:
    from nomarr.helpers.dto.repo_dto import TagRow
    from nomarr.persistence.db import Database


_PAGE_SIZE = 1000
_MOOD_TAG_NAMES = ("nom:mood-strict", "nom:mood-regular", "nom:mood-loose")


class MoodAnalysisResult(TypedDict):
    """Result shape for compute_mood_analysis."""

    coverage: dict[str, Any]
    balance: dict[str, Any]
    top_pairs_by_tier: dict[str, Any]
    dominant_vibes: list[DominantVibeResult]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_library_song_ids(db: Database, library_id: int | None) -> set[int] | None:
    """Return the allowed file-id set for a library scope when requested."""
    if library_id is None:
        return None

    file_ids: set[int] = set()
    for song in db.library.list_songs(library_id):
        file_ids.add(song.song_id)

    return file_ids


def _get_tag_docs_for_name(db: Database, name: str) -> list[TagRow]:
    """Return all tag documents for one tag name via constructor verbs."""
    tags: list[TagRow] = []
    offset = 0
    while True:
        tag_page = db.library.list_tags(name=name, limit=_PAGE_SIZE, offset=offset)
        if not tag_page:
            break
        tags.extend(tag_page)
        if len(tag_page) < _PAGE_SIZE:
            break
        offset += len(tag_page)

    return tags


def _get_tag_edge_rows(
    db: Database,
    name: str,
    library_id: int | None = None,
) -> list[tuple[int, str]]:
    """Return ``(file_id, tag_value)`` rows for one tag name."""
    library_song_ids = _get_library_song_ids(db, library_id)

    tag_docs = _get_tag_docs_for_name(db, name)
    tag_id_to_value: dict[int, str] = {}
    for tag_doc in tag_docs:
        tag_id = tag_doc.get("id")
        tag_value = tag_doc.get("value")
        if isinstance(tag_id, int) and tag_value is not None:
            tag_id_to_value[tag_id] = str(tag_value)

    if not tag_id_to_value:
        return []

    # Query files for each tag value using search_songs_by_tag
    rows: list[tuple[int, str]] = []
    for tag_value in tag_id_to_value.values():
        file_docs = db.library.search_songs_by_tag(name, tag_value, limit=None)
        for file_doc in file_docs:
            file_id = file_doc.get("id")
            if not isinstance(file_id, int):
                continue
            if library_song_ids is not None and file_id not in library_song_ids:
                continue
            rows.append((file_id, tag_value))

    return rows


def _get_tier_tag_keys(db: Database) -> list[str]:
    """Return the names of all tier tags (nom:energy_tier, etc.)."""
    # Tier tags follow the nom:<attribute>_tier pattern
    tag_names: set[str] = set()
    offset = 0
    while True:
        tag_page = db.library.list_tags(limit=_PAGE_SIZE, offset=offset)
        if not tag_page:
            break
        for tag_doc in tag_page:
            t_name = tag_doc.get("name")
            if isinstance(t_name, str) and t_name.endswith("_tier"):
                tag_names.add(t_name)
        if len(tag_page) < _PAGE_SIZE:
            break
        offset += len(tag_page)

    return sorted(tag_names)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


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
    mood_tag_rows: list[tuple[int, str]] = []
    for name in _MOOD_TAG_NAMES:
        mood_tag_rows.extend(_get_tag_edge_rows(db, name))

    tier_tag_keys = _get_tier_tag_keys(db)
    tier_tag_rows: dict[str, list[tuple[int, str]]] = {}
    for tier_name in tier_tag_keys:
        tier_tag_rows[tier_name] = _get_tag_edge_rows(db, tier_name)

    return {"mood_tag_rows": mood_tag_rows, "tier_tag_keys": tier_tag_keys, "tier_tag_rows": tier_tag_rows}


def get_mood_distribution_data(db: Database, library_id: int | None = None) -> list[tuple[str, str]]:
    """Get raw mood rows for distribution analytics.

    Args:
        db: Database instance used to query mood tags.
        library_id: Optional library id to filter by.

    Returns:
        List of ``(tag_name, tag_value)`` tuples for all mood tiers.

    """
    rows: list[tuple[str, str]] = []
    for name in _MOOD_TAG_NAMES:
        tier_rows = _get_tag_edge_rows(db, name, library_id)
        for _file_id, tag_value in tier_rows:
            rows.append((name, tag_value))
    return rows


def get_mood_coverage(db: Database, library_id: int | None = None) -> dict[str, Any]:
    """Compute mood tag coverage as percentage per tier.

    Args:
        db: Database instance.
        library_id: Optional library id to filter by.

    Returns:
        A dict with ``total_files`` and ``tiers`` containing ``tagged``
        and ``percentage`` for each of strict, regular, and loose.

    """
    stats = get_library_stats(db, library_id)
    total_files = stats.get("total_files", 0)
    if total_files == 0:
        return {
            "total_files": 0,
            "tiers": {t: {"tagged": 0, "percentage": 0.0} for t in ("strict", "regular", "loose")},
        }

    result: dict[str, Any] = {"total_files": total_files, "tiers": {}}
    for tier in ("strict", "regular", "loose"):
        name = f"nom:mood-{tier}"
        rows = _get_tag_edge_rows(db, name, library_id=library_id)
        unique_files: set[int] = set()
        for file_id, _tag_value in rows:
            unique_files.add(file_id)
        tagged = len(unique_files)
        percentage = round(tagged / total_files * 100, 1)
        result["tiers"][tier] = {"tagged": tagged, "percentage": percentage}
    return result


def get_mood_balance(db: Database, library_id: int | None = None) -> dict[str, Any]:
    """Get the value distribution (balance) for each mood tier.

    Args:
        db: Database instance.
        library_id: Optional library id to filter by.

    Returns:
        A dict with keys ``strict``, ``regular``, ``loose``, each
        containing a list of ``{"mood": ..., "count": ...}`` dicts sorted by
        descending count.  Compound mood values such as ``(happy,sad)`` are
        split into separate entries.

    """
    from collections import Counter

    result: dict[str, Any] = {}
    for tier in ("strict", "regular", "loose"):
        name = f"nom:mood-{tier}"
        rows = _get_tag_edge_rows(db, name, library_id=library_id)
        counter: Counter[str] = Counter()
        for _file_id, tag_value in rows:
            # Split compound moods like "(happy,sad)"
            if tag_value.startswith("(") and tag_value.endswith(")"):
                inner = tag_value[1:-1]
                for mood in inner.split(","):
                    mood = mood.strip()
                    if mood:
                        counter[mood] += 1
            else:
                counter[tag_value] += 1
        sorted_moods = [
            {"mood": mood, "count": count} for mood, count in sorted(counter.items(), key=lambda x: (-x[1], x[0]))
        ]
        result[tier] = sorted_moods
    return result


def _get_top_mood_pairs(
    db: Database,
    library_id: int | None,
    mood_tier: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return the most common co-occurring mood pairs for one tier.

    Reimplementation of the former db.tags.get_top_mood_pairs using the
    PostgreSQL-backed library facade via _get_tag_edge_rows.
    """
    from collections import Counter

    tier_hierarchy: dict[str, list[str]] = {
        "strict": ["nom:mood-strict"],
        "regular": ["nom:mood-strict", "nom:mood-regular"],
        "loose": ["nom:mood-strict", "nom:mood-regular", "nom:mood-loose"],
    }
    names = tier_hierarchy.get(mood_tier, ["nom:mood-strict"])

    # Fetch (file_id, tag_value) pairs for all requested mood names
    tag_value_rows: list[tuple[int, str]] = []
    for name in names:
        tag_value_rows.extend(_get_tag_edge_rows(db, name, library_id))

    # Build mood-per-song map
    moods_by_song: dict[int, set[str]] = {}
    for fid, mood_value in tag_value_rows:
        if not mood_value:
            continue
        moods_by_song.setdefault(fid, set()).add(mood_value)

    # Compute pair co-occurrences
    pair_counts: Counter[tuple[str, str]] = Counter()
    for moods in moods_by_song.values():
        ordered = sorted(moods)
        if len(ordered) < 2:
            continue
        for i, m1 in enumerate(ordered[:-1]):
            for m2 in ordered[i + 1 :]:
                pair_counts[(m1, m2)] += 1

    return [
        {"mood1": m1, "mood2": m2, "count": count}
        for (m1, m2), count in sorted(
            pair_counts.items(),
            key=lambda item: (-item[1], item[0][0], item[0][1]),
        )[:limit]
    ]


def compute_mood_analysis(
    db: Database,
    library_id: int | None = None,
) -> MoodAnalysisResult:
    """Compute mood analysis: coverage, balance, top pairs, dominant vibes.

    Args:
        db: Database instance.
        library_id: Optional library id to filter by.

    """
    coverage = get_mood_coverage(db, library_id)
    balance = get_mood_balance(db, library_id)
    top_pairs_by_tier = {
        tier: _get_top_mood_pairs(db, library_id, mood_tier=tier, limit=50) for tier in ("strict", "regular", "loose")
    }
    dominant_vibes = compute_dominant_vibes(balance)

    return {
        "coverage": coverage,
        "balance": balance,
        "top_pairs_by_tier": top_pairs_by_tier,
        "dominant_vibes": dominant_vibes,
    }
