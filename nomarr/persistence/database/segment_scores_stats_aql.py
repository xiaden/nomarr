"""Segment scores statistics operations for ArangoDB.

segment_scores_stats collection stores per-label aggregates (mean, std, min, max)
from ML head segment-level predictions. One document per (file_id, head_name, tagger_version).
"""

import hashlib
from typing import Any, cast

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import DatabaseLike


class SegmentScoresStatsOperations:
    """Operations for the segment_scores_stats collection."""

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db
        self.collection = db.collection("segment_scores_stats")

    @staticmethod
    def _make_key(file_id: str, head_name: str, tagger_version: str) -> str:
        """Build a deterministic ArangoDB-safe _key from file_id, head_name, and tagger_version.

        Uses SHA1 hex digest which is alphanumeric-only and ArangoDB-safe.
        """
        return hashlib.sha1(f"{file_id}|{head_name}|{tagger_version}".encode()).hexdigest()

    def upsert_stats(
        self,
        file_id: str,
        head_name: str,
        tagger_version: str,
        num_segments: int,
        pooling_strategy: str,
        label_stats: list[dict[str, Any]],
    ) -> None:
        """Upsert segment statistics document for a file/head/version combination.

        Uses atomic AQL UPSERT to avoid race conditions under parallel workers.

        Args:
            file_id: Library file document ID (e.g., "library_files/12345")
            head_name: ML head name (e.g., "mood_happy")
            tagger_version: Tagger version string
            num_segments: Number of audio segments processed
            pooling_strategy: Pooling method used (e.g., "trimmed_mean")
            label_stats: List of {label, mean, std, min, max} dicts, one per class

        """
        _key = self._make_key(file_id, head_name, tagger_version)
        ts = now_ms().value

        self.db.aql.execute(
            """
            UPSERT { _key: @_key }
            INSERT {
                _key: @_key,
                file_id: @file_id,
                head_name: @head_name,
                tagger_version: @tagger_version,
                num_segments: @num_segments,
                pooling_strategy: @pooling_strategy,
                label_stats: @label_stats,
                processed_at: @ts
            }
            UPDATE {
                file_id: @file_id,
                head_name: @head_name,
                tagger_version: @tagger_version,
                num_segments: @num_segments,
                pooling_strategy: @pooling_strategy,
                label_stats: @label_stats,
                processed_at: @ts
            }
            IN segment_scores_stats
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "_key": _key,
                    "file_id": file_id,
                    "head_name": head_name,
                    "tagger_version": tagger_version,
                    "num_segments": num_segments,
                    "pooling_strategy": pooling_strategy,
                    "label_stats": label_stats,
                    "ts": ts,
                },
            ),
        )

    def get_stats_for_file(self, file_id: str) -> list[dict[str, Any]]:
        """Get all segment statistics documents for a given file.

        Args:
            file_id: Library file document ID

        Returns:
            List of segment_scores_stats documents for the file

        """
        cursor = self.db.aql.execute(
            "FOR doc IN segment_scores_stats FILTER doc.file_id == @file_id RETURN doc",
            bind_vars={"file_id": file_id},
        )
        return list(cursor)  # type: ignore[arg-type]

    def delete_by_file_id(self, file_id: str) -> int:
        """Delete all segment statistics documents for a given file.

        Args:
            file_id: Library file document ID

        Returns:
            Number of documents deleted

        """
        cursor = self.db.aql.execute(
            """
            FOR doc IN segment_scores_stats
                FILTER doc.file_id == @file_id
                REMOVE doc IN segment_scores_stats
                COLLECT WITH COUNT INTO removed
                RETURN removed
            """,
            bind_vars={"file_id": file_id},
        )
        results = list(cursor)  # type: ignore[arg-type]
        return cast("int", results[0]) if results else 0

    def delete_by_file_ids(self, file_ids: list[str]) -> int:
        """Bulk delete segment statistics documents for multiple files.

        Args:
            file_ids: List of library file document IDs

        Returns:
            Number of documents deleted

        """
        if not file_ids:
            return 0
        cursor = self.db.aql.execute(
            """
            FOR doc IN segment_scores_stats
                FILTER doc.file_id IN @file_ids
                REMOVE doc IN segment_scores_stats
                COLLECT WITH COUNT INTO removed
                RETURN removed
            """,
            bind_vars={"file_ids": file_ids},
        )
        results = list(cursor)  # type: ignore[arg-type]
        return cast("int", results[0]) if results else 0

    def truncate(self) -> None:
        """Remove all documents from the segment_scores_stats collection."""
        self.collection.truncate()

    def get_stats_for_head(self, head_name: str) -> list[dict[str, Any]]:
        """Get all segment statistics documents for a given head across all files.

        Useful for library-wide stability analysis.

        Args:
            head_name: ML head name

        Returns:
            List of segment_scores_stats documents for the head

        """
        cursor = self.db.aql.execute(
            "FOR doc IN segment_scores_stats FILTER doc.head_name == @head_name RETURN doc",
            bind_vars={"head_name": head_name},
        )
        return list(cursor)  # type: ignore[arg-type]

    def get_high_variance_files(
        self,
        head_name: str,
        label: str,
        std_threshold: float,
    ) -> list[dict[str, Any]]:
        """Find files with high variance for a specific label in a head.

        Filters segment_scores_stats by head_name, unnests label_stats,
        and returns documents where the label's std exceeds the threshold.

        Args:
            head_name: ML head name
            label: Label to check variance for
            std_threshold: Minimum std to include in results

        Returns:
            List of dicts with file_id and matching label stats

        """
        cursor = self.db.aql.execute(
            """
            FOR doc IN segment_scores_stats
                FILTER doc.head_name == @head_name
                LET matched = (
                    FOR ls IN doc.label_stats
                        FILTER ls.label == @label AND ls.std > @threshold
                        RETURN ls
                )
                FILTER LENGTH(matched) > 0
                RETURN {
                    file_id: doc.file_id,
                    head_name: doc.head_name,
                    tagger_version: doc.tagger_version,
                    num_segments: doc.num_segments,
                    label_stats: matched
                }
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "head_name": head_name,
                    "label": label,
                    "threshold": std_threshold,
                },
            ),
        )
        return list(cursor)  # type: ignore[arg-type]

    def get_stats_summary(self, head_name: str) -> dict[str, Any]:
        """Get aggregated summary statistics for a head across all files.

        Returns count of files with stats, average std across all labels,
        and min/max num_segments.

        Args:
            head_name: ML head name

        Returns:
            Dict with file_count, avg_std, min_segments, max_segments

        """
        cursor = self.db.aql.execute(
            """
            LET docs = (
                FOR doc IN segment_scores_stats
                    FILTER doc.head_name == @head_name
                    RETURN doc
            )
            LET all_stds = (
                FOR doc IN docs
                    FOR ls IN doc.label_stats
                        RETURN ls.std
            )
            RETURN {
                file_count: LENGTH(docs),
                avg_std: LENGTH(all_stds) > 0 ? AVG(all_stds) : null,
                min_segments: LENGTH(docs) > 0 ? MIN(docs[*].num_segments) : null,
                max_segments: LENGTH(docs) > 0 ? MAX(docs[*].num_segments) : null
            }
            """,
            bind_vars={"head_name": head_name},
        )
        results = list(cursor)  # type: ignore[arg-type]
        return cast("dict[str, Any]", results[0]) if results else {
            "file_count": 0,
            "avg_std": None,
            "min_segments": None,
            "max_segments": None,
        }
