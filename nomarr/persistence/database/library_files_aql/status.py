"""Status operations for library_files collection."""

import logging
from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from arango.cursor import Cursor

    from nomarr.persistence.db import Database


class LibraryFilesStatusMixin:
    """Status operations for library_files."""

    db: DatabaseLike
    collection: Any
    parent_db: "Database | None"

    def mark_file_tagged(self, file_id: str, tagged_version: str) -> None:
        """Mark file as tagged.

        Accepts _id directly (no lookup needed).

        Args:
            file_id: Document _id (e.g., "library_files/12345")
            tagged_version: Tagged version string

        """
        self.db.aql.execute(
            """
            UPDATE PARSE_IDENTIFIER(@file_id).key WITH {
                tagged: true,
                tagged_version: @version,
                last_tagged_at: @timestamp,
                needs_tagging: false
            } IN library_files
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {"file_id": file_id, "version": tagged_version, "timestamp": now_ms().value},
            ),
        )

    def mark_file_invalid(self, path: str) -> None:
        """Mark file as no longer existing on disk.

        Args:
            path: File path to mark invalid

        """
        self.db.aql.execute(
            """
            FOR file IN library_files
                FILTER file.path == @path
                UPDATE file WITH { is_valid: false } IN library_files
            """,
            bind_vars={"path": path},
        )

    def bulk_mark_invalid(self, paths: list[str]) -> None:
        """Mark multiple files as invalid.

        DEPRECATED: Use bulk_delete_files instead. Soft deletes create state explosion.

        Args:
            paths: List of file paths to mark invalid

        """
        if not paths:
            return

        self.db.aql.execute(
            """
            FOR file IN library_files
                FILTER file.path IN @paths
                UPDATE file WITH { is_valid: false } IN library_files
            """,
            bind_vars={"paths": paths},
        )

    def library_has_tagged_files(self, library_id: str) -> bool:
        """Check if library has any files with ML tags.

        Args:
            library_id: Library ID

        Returns:
            True if library has at least one tagged file

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR file IN library_files
                FILTER file.library_id == @library_id AND file.tagged == true
                SORT file._key
                LIMIT 1
                RETURN 1
            """,
                bind_vars=cast("dict[str, Any]", {"library_id": library_id}),
            ),
        )
        result = list(cursor)
        return len(result) > 0

    def get_files_needing_tagging(self, library_id: int | None, paths: list[str] | None = None) -> list[dict[str, Any]]:
        """Get files that need ML tagging.

        Args:
            library_id: Library ID (or None for all libraries)
            paths: Optional specific file paths to filter

        Returns:
            List of file dicts needing tagging

        """
        filters = ["file.needs_tagging == true", "file.is_valid == true"]
        bind_vars: dict[str, Any] = {}

        if library_id is not None:
            filters.append("file.library_id == @library_id")
            bind_vars["library_id"] = library_id

        if paths:
            filters.append("file.path IN @paths")
            bind_vars["paths"] = paths

        filter_clause = " AND ".join(filters)

        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                f"""
            FOR file IN library_files
                FILTER {filter_clause}
                RETURN file
            """,
                bind_vars=bind_vars,
            ),
        )
        return list(cursor)

    def discover_next_unprocessed_file(
        self,
        min_duration_s: int | None = None,
        allow_short: bool = True,
    ) -> dict[str, Any] | None:
        """Discover next file needing ML tagging for worker discovery.

        Query optimized for discovery-based workers:
        - Filters: needs_tagging=true, is_valid=true
        - Excludes files with active claims in worker_claims collection
        - Optional duration filter (skip files too short for ML)
        - Deterministic ordering by _key for consistent work distribution
        - LIMIT 1 for single-file claiming

        Args:
            min_duration_s: Minimum duration in seconds for ML processing.
                If provided and allow_short=False, files shorter than this
                are excluded from discovery (avoids loading audio just to skip).
            allow_short: If True, skip duration filtering (process all files).

        Returns:
            File dict or None if no work available

        """
        # Build duration filter if needed
        duration_filter = ""
        if min_duration_s is not None and not allow_short:
            # Filter out files with duration < min_duration_s
            duration_filter = f"""
                    FILTER file.duration_seconds == null OR file.duration_seconds >= {min_duration_s}"""

        query = f"""\
                FOR file IN library_files
                    FILTER file.needs_tagging == true
                    FILTER file.is_valid == true{duration_filter}
                    LET claim_key = CONCAT("claim_", file._key)
                    FILTER DOCUMENT(CONCAT("worker_claims/", claim_key)) == null
                    SORT file._key
                    LIMIT 1
                    RETURN file
                """
        logger.debug("[DB] discover_next_unprocessed_file query: %s", query.strip())
        cursor = cast(
            "Cursor",
            self.db.aql.execute(query),
        )
        # Convert cursor to list to see all results
        results = list(cursor)
        logger.debug("[DB] discover_next_unprocessed_file raw results count: %d", len(results))
        result = results[0] if results else None
        if result:
            logger.info("[DB] discover_next_unprocessed_file: found %s", result.get("_id"))
        else:
            # Debug query: count files by filter stage
            diag = cast(
                "Cursor",
                self.db.aql.execute(
                    """\
                    LET total = LENGTH(FOR f IN library_files RETURN 1)
                    LET needs_tagging = LENGTH(FOR f IN library_files FILTER f.needs_tagging == true RETURN 1)
                    LET is_valid = LENGTH(FOR f IN library_files FILTER f.needs_tagging == true AND f.is_valid == true RETURN 1)
                    LET unclaimed = LENGTH(
                        FOR f IN library_files
                            FILTER f.needs_tagging == true AND f.is_valid == true
                            LET claim_key = CONCAT("claim_", f._key)
                            FILTER DOCUMENT(CONCAT("worker_claims/", claim_key)) == null
                            RETURN 1
                    )
                    RETURN {total, needs_tagging, is_valid, unclaimed}
                    """,
                ),
            )
            diag_result: dict[str, Any] = next(iter(diag), {})
            logger.debug(
                "[DB] discover_next_unprocessed_file: no files found. "
                "Diagnostics: total=%s, needs_tagging=%s, is_valid=%s, unclaimed=%s",
                diag_result.get("total"),
                diag_result.get("needs_tagging"),
                diag_result.get("is_valid"),
                diag_result.get("unclaimed"),
            )
        return result
