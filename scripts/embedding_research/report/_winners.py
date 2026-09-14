"""Class-scoped and baseline neighborhood rows for the winners report section.

Both surfaces are rendered from the normalized frames and kept strictly separate: class
neighborhoods are keyed by ``(corpus_search_class_id, query, candidate)`` while baseline
neighborhoods are keyed by ``(backbone, query, candidate)``.  Uniqueness is always scoped
by the owning class/backbone; the same ``(query, candidate)`` pair under two classes is
never collapsed into one row.
"""

from __future__ import annotations

from typing import Any

CLASS_NEIGHBORHOOD_COLUMNS = ["corpus_search_class_id", "query_song_id", "candidate_song_id", "rank", "score"]
BASELINE_NEIGHBORHOOD_COLUMNS = ["backbone", "query_song_id", "candidate_song_id", "rank", "score"]


def _project(rows: Any, columns: list[str], scope: tuple[str, ...]) -> list[dict[str, Any]]:
    if rows is None:
        return []
    seen: set[tuple[Any, ...]] = set()
    projected: list[dict[str, Any]] = []
    for row in rows:
        key = tuple(row[column] for column in scope)
        if key in seen:
            continue
        seen.add(key)
        projected.append({column: row[column] for column in columns})
    return projected


def class_neighborhood_rows(frames: Any) -> list[dict[str, Any]]:
    """Class-scoped neighborhood rows, unique by ``(class, query, candidate)``."""
    rows = None if frames is None else frames.class_neighborhoods
    return _project(rows, CLASS_NEIGHBORHOOD_COLUMNS, ("corpus_search_class_id", "query_song_id", "candidate_song_id"))


def baseline_neighborhood_rows(frames: Any) -> list[dict[str, Any]]:
    """Baseline neighborhood rows, unique by ``(backbone, query, candidate)``."""
    rows = None if frames is None else frames.baseline_neighborhoods
    return _project(rows, BASELINE_NEIGHBORHOOD_COLUMNS, ("backbone", "query_song_id", "candidate_song_id"))


__all__ = [
    "BASELINE_NEIGHBORHOOD_COLUMNS",
    "CLASS_NEIGHBORHOOD_COLUMNS",
    "baseline_neighborhood_rows",
    "class_neighborhood_rows",
]
