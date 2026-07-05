"""Mood analysis analytics - coverage, balance, top pairs, dominant vibes."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Any, TypedDict

from nomarr.components.analytics.analytics_comp import compute_dominant_vibes
from nomarr.components.tagging.tag_stats_comp import get_library_stats

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


class _MoodPairEntry(TypedDict):
    """A co-occurring mood pair with count."""

    mood1: str
    mood2: str
    count: int


class _MoodCoverageTier(TypedDict):
    """Coverage for a single mood tier."""

    tagged: int
    percentage: float


class _MoodCoverage(TypedDict):
    """Mood coverage result."""

    total_files: int
    tiers: dict[str, _MoodCoverageTier]


_PAGE_SIZE = 1000
_MOOD_TAG_NAMES = ("nom:mood-strict", "nom:mood-regular", "nom:mood-loose")
_MOOD_TIER_MAP = {"strict": "nom:mood-strict", "regular": "nom:mood-regular", "loose": "nom:mood-loose"}


def _get_library_file_ids(db: Database, library_id: str | None) -> set[str] | None:
    """Return the allowed file-id set for a library scope when requested."""
    if library_id is None:
        return None

    file_ids: set[str] = set()
    file_docs = db.library.list_library_files(library_id)
    for file_doc in file_docs:
        file_id = file_doc.get("_id")
        if isinstance(file_id, str):
            file_ids.add(file_id)

    return file_ids


def _get_tag_docs_for_name(db: Database, name: str) -> list[dict[str, Any]]:
    """Return all tag documents for one tag name via constructor verbs."""
    tags: list[dict[str, Any]] = []
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


def _get_tag_edge_rows(db: Database, name: str, library_id: str | None = None) -> list[tuple[str, str]]:
    """Return ``(file_id, tag_value)`` rows for one tag name via intent-level searches."""
    library_file_ids = _get_library_file_ids(db, library_id)
    rows: list[tuple[str, str]] = []
    for tag_doc in _get_tag_docs_for_name(db, name):
        tag_value = tag_doc.get("value")
        if tag_value is None:
            continue
        file_docs = db.library.search_files_by_tag(name, str(tag_value), limit=None)
        if not isinstance(file_docs, list):
            continue
        for file_doc in file_docs:
            file_id = file_doc.get("_id")
            if not isinstance(file_id, str):
                continue
            if library_file_ids is not None and file_id not in library_file_ids:
                continue
            rows.append((file_id, str(tag_value)))

    return rows


def _get_tier_tag_keys(db: Database) -> list[str]:
    """Return all distinct Nomarr tier tag names."""
    total_tags = int(db.library.count_tags())
    if total_tags <= 0:
        return []

    tier_tag_keys: list[str] = []
    seen: set[str] = set()
    for name_value in db.library.list_all_tag_names(limit=total_tags):
        name = str(name_value)
        if name.startswith("nom:") and name.endswith("_tier") and name not in seen:
            seen.add(name)
            tier_tag_keys.append(name)
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
    """Return raw mood and tier tag rows for correlation analysis."""
    mood_tag_rows: list[tuple[str, str]] = []
    for name in _MOOD_TAG_NAMES:
        mood_tag_rows.extend(_get_tag_edge_rows(db, name))

    tier_tag_keys = _get_tier_tag_keys(db)
    tier_tag_rows: dict[str, list[tuple[str, str]]] = {}
    for tier_name in tier_tag_keys:
        tier_tag_rows[tier_name] = _get_tag_edge_rows(db, tier_name)

    return {"mood_tag_rows": mood_tag_rows, "tier_tag_keys": tier_tag_keys, "tier_tag_rows": tier_tag_rows}


def get_mood_distribution_data(db: Database, library_id: str | None = None) -> list[tuple[str, str]]:
    """Return ``(mood_name, tag_value)`` tuples for distribution analytics, optionally scoped to a library."""
    mood_rows: list[tuple[str, str]] = []
    for mood_type in _MOOD_TAG_NAMES:
        mood_rows.extend((mood_type, tag_value) for _, tag_value in _get_tag_edge_rows(db, mood_type, library_id))
    return mood_rows


def get_mood_coverage(db: Database, library_id: str | None = None) -> _MoodCoverage:
    """Return percentage of files tagged per mood tier (strict, regular, loose)."""
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

    tiers: dict[str, _MoodCoverageTier] = {}
    for tier_name, name in _MOOD_TIER_MAP.items():
        tagged_count = len({file_id for file_id, _ in _get_tag_edge_rows(db, name, library_id)})
        tiers[tier_name] = {
            "tagged": tagged_count,
            "percentage": round((tagged_count / total_files) * 100, 1) if total_files > 0 else 0.0,
        }

    return {"total_files": total_files, "tiers": tiers}


def get_mood_balance(db: Database, library_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """Return mood-value distribution across strict, regular, and loose tiers."""
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
) -> list[_MoodPairEntry]:
    """Return the most common co-occurring mood pairs for one tier."""
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
        _MoodPairEntry(mood1=mood1, mood2=mood2, count=count)
        for (mood1, mood2), count in sorted(
            pair_counts.items(),
            key=lambda item: (-item[1], item[0][0], item[0][1]),
        )[:limit]
    ]


def compute_mood_analysis(
    db: Database,
    library_id: str | None = None,
) -> dict[str, Any]:
    """Return mood analysis: coverage, balance, top pairs, dominant vibes."""
    coverage = get_mood_coverage(db, library_id)
    balance = get_mood_balance(db, library_id)

    top_pairs_by_tier = {
        tier: get_top_mood_pairs(db, library_id, mood_tier=tier, limit=50) for tier in ("strict", "regular", "loose")
    }

    dominant_vibes = compute_dominant_vibes(balance)

    return {
        "coverage": coverage,
        "balance": balance,
        "top_pairs_by_tier": top_pairs_by_tier,
        "dominant_vibes": dominant_vibes,
    }
