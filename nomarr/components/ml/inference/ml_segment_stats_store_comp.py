"""Component-owned persistence helpers for segment score statistics."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def _segment_scores_stats_ns(db: Database) -> Any:
    """Return the runtime-wired segment-stats namespace with collection verbs attached."""
    return cast("Any", db.segment_scores_stats)


def _library_files_ns(db: Database) -> Any:
    """Return the runtime-wired library-files namespace with traversal verbs attached."""
    return cast("Any", db.library_files)


def _stats_key(file_id: str, head_name: str, tagger_version: str) -> str:
    """Build the stable document key for one segment-stats row."""
    return hashlib.sha1(f"{file_id}|{head_name}|{tagger_version}".encode()).hexdigest()


def _edge_key(file_id: str, stats_id: str) -> str:
    """Build the stable edge key linking one file to one stats row."""
    return hashlib.sha256(f"{file_id}:{stats_id}".encode()).hexdigest()[:16]


def _build_edge_namespace(db: Database) -> Any:
    """Return the runtime-wired edge namespace used for file→stats links."""
    return cast("Any", db.file_has_segment_stats)


def upsert_segment_stats(
    db: Database,
    *,
    file_id: str,
    head_name: str,
    tagger_version: str,
    num_segments: int,
    pooling_strategy: str,
    label_stats: list[dict[str, Any]],
) -> None:
    """Upsert one segment-stats document and ensure its file edge exists."""
    upsert_segment_stats_batch(
        db,
        [
            {
                "file_id": file_id,
                "head_name": head_name,
                "tagger_version": tagger_version,
                "num_segments": num_segments,
                "pooling_strategy": pooling_strategy,
                "label_stats": label_stats,
            }
        ],
    )


def upsert_segment_stats_batch(db: Database, entries: list[dict[str, Any]]) -> None:
    """Upsert multiple segment-stats documents and their file edges."""
    if not entries:
        return

    processed_at = now_ms().value
    edge_ns = _build_edge_namespace(db)
    edge_count = edge_ns.count()
    segment_scores_stats = _segment_scores_stats_ns(db)

    docs: list[dict[str, Any]] = []
    links_by_file: dict[str, list[str]] = {}
    for entry in entries:
        file_id = cast("str", entry["file_id"])
        head_name = cast("str", entry["head_name"])
        tagger_version = cast("str", entry["tagger_version"])
        key = _stats_key(file_id, head_name, tagger_version)
        stats_id = f"segment_scores_stats/{key}"
        docs.append(
            {
                "_key": key,
                "head_name": head_name,
                "tagger_version": tagger_version,
                "num_segments": int(cast("int", entry["num_segments"])),
                "pooling_strategy": cast("str", entry["pooling_strategy"]),
                "label_stats": cast("list[dict[str, Any]]", entry["label_stats"]),
                "processed_at": int(cast("int", entry.get("processed_at", processed_at))),
            }
        )
        links_by_file.setdefault(file_id, []).append(stats_id)

    for doc in docs:
        segment_scores_stats.upsert(
            _key=cast("str", doc["_key"]),
            fields={key: value for key, value in doc.items() if key != "_key"},
        )

    edge_docs: list[dict[str, str]] = []
    for file_id, stats_ids in links_by_file.items():
        existing_edges = cast(
            "list[dict[str, Any]]",
            edge_ns.get(_from=file_id, limit=edge_count or None),
        )
        existing_targets = {str(edge["_to"]) for edge in existing_edges if "_to" in edge}
        for stats_id in stats_ids:
            if stats_id in existing_targets:
                continue
            edge_docs.append(
                {
                    "_key": _edge_key(file_id, stats_id),
                    "_from": file_id,
                    "_to": stats_id,
                }
            )
            existing_targets.add(stats_id)

    if edge_docs:
        edge_ns.insert(edge_docs)


def get_segment_stats_for_file(db: Database, file_id: str) -> list[dict[str, Any]]:
    """Return all segment-stats documents linked to one file."""
    library_files = _library_files_ns(db)
    segment_scores_stats = _segment_scores_stats_ns(db)
    return cast(
        "list[dict[str, Any]]",
        library_files.file_has_segment_stats(file_id, limit=segment_scores_stats.count()),
    )


def get_segment_stats_for_files_bulk(db: Database, file_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Return segment-stats documents grouped by file id."""
    result: dict[str, list[dict[str, Any]]] = {}
    for file_id in file_ids:
        stats_docs = get_segment_stats_for_file(db, file_id)
        if stats_docs:
            result[file_id] = stats_docs
    return result


def delete_segment_stats_for_file(db: Database, file_id: str) -> int:
    """Cascade-delete all stats rows linked to one file.

    Args:
        db: Database instance.
        file_id: Document ``_id`` of the library file whose stats should be deleted.

    Returns:
        Number of stats documents deleted.
    """
    stats_docs = get_segment_stats_for_file(db, file_id)
    if not stats_docs:
        return 0

    stats_ids = [cast("str", doc["_id"]) for doc in stats_docs if "_id" in doc]
    if not stats_ids:
        return 0

    segment_scores_stats = _segment_scores_stats_ns(db)
    return int(segment_scores_stats.delete.cascade(stats_ids))


def delete_segment_stats_for_files(db: Database, file_ids: list[str]) -> int:
    """Cascade-delete all stats rows linked to the provided files.

    Args:
        db: Database instance.
        file_ids: Document ``_id`` strings for the library files whose stats should be deleted.

    Returns:
        Total number of stats documents deleted across all files.
    """
    deleted = 0
    for file_id in file_ids:
        deleted += delete_segment_stats_for_file(db, file_id)
    return deleted


def get_high_variance_segment_stats(
    db: Database,
    head_name: str,
    label: str,
    std_threshold: float,
) -> list[dict[str, Any]]:
    """Filter constructor-backed segment stats to rows whose label std exceeds the threshold."""
    segment_scores_stats = _segment_scores_stats_ns(db)
    docs = cast(
        "list[dict[str, Any]]",
        segment_scores_stats.get(head_name=head_name, limit=segment_scores_stats.count()),
    )
    result: list[dict[str, Any]] = []
    for doc in docs:
        matches = [row for row in cast("list[dict[str, Any]]", doc.get("label_stats", [])) if row.get("label") == label]
        if not matches:
            continue
        high_variance = [row for row in matches if float(cast("float", row.get("std", 0.0))) > std_threshold]
        if not high_variance:
            continue
        result.append(
            {
                "head_name": doc.get("head_name"),
                "tagger_version": doc.get("tagger_version"),
                "num_segments": doc.get("num_segments"),
                "label_stats": high_variance,
            }
        )
    return result


def summarize_segment_stats(db: Database, head_name: str) -> dict[str, Any]:
    """Summarize constructor-backed segment stats for one head."""
    segment_scores_stats = _segment_scores_stats_ns(db)
    docs = cast(
        "list[dict[str, Any]]",
        segment_scores_stats.get(head_name=head_name, limit=segment_scores_stats.count()),
    )
    if not docs:
        return {
            "file_count": 0,
            "avg_std": None,
            "min_segments": None,
            "max_segments": None,
        }

    all_stds: list[float] = []
    for doc in docs:
        all_stds.extend(
            float(cast("float", row["std"]))
            for row in cast("list[dict[str, Any]]", doc.get("label_stats", []))
            if "std" in row
        )

    segment_counts = [int(cast("int", doc.get("num_segments", 0))) for doc in docs]
    avg_std = sum(all_stds) / len(all_stds) if all_stds else None
    return {
        "file_count": len(docs),
        "avg_std": avg_std,
        "min_segments": min(segment_counts) if segment_counts else None,
        "max_segments": max(segment_counts) if segment_counts else None,
    }
