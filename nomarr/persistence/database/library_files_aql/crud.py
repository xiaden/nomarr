"""CRUD operations for library_files collection."""

from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.dto import LibraryPath
from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor

    from nomarr.persistence.db import Database


class LibraryFilesCrudMixin:
    """CRUD operations for library_files."""

    db: DatabaseLike
    collection: Any
    parent_db: "Database | None"

    def upsert_library_file(
        self,
        path: LibraryPath,
        library_id: str,
        file_size: int,
        modified_time: int,
        duration_seconds: float | None = None,
        artist: str | None = None,
        album: str | None = None,
        title: str | None = None,
        last_tagged_at: int | None = None,
        has_nomarr_namespace: bool | None = None,
        last_written_mode: str | None = None,
    ) -> str:
        """Insert or update a library file entry.

        Uses (library_id, normalized_path) as upsert key, matching batch upsert.
        Stores both absolute path (for filesystem access) and normalized_path
        (POSIX relative path for identity).

        Note: calibration_hash field remains NULL until first recalibration.
        Initial processing stores raw scores only.

        Args:
            path: LibraryPath with validated file path (must have status == "valid")
            library_id: ID of owning library
            file_size: File size in bytes
            modified_time: Last modified timestamp
            duration_seconds: Audio duration
            artist: Artist name
            album: Album name
            title: Track title
            last_tagged_at: Last tagging timestamp
            has_nomarr_namespace: Whether file has nomarr tags in audio file
            last_written_mode: Inferred write mode from existing file tags

        Returns:
            Document _id (e.g., "library_files/12345")

        Raises:
            ValueError: If path status is not "valid"

        """
        if not path.is_valid():
            msg = f"Cannot upsert invalid path ({path.status}): {path.reason}"
            raise ValueError(msg)

        scanned_at = now_ms().value
        normalized_path = str(path.relative)
        absolute_path = str(path.absolute)
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            UPSERT { library_id: @library_id, normalized_path: @normalized_path }
            INSERT {
                library_id: @library_id,
                path: @path,
                normalized_path: @normalized_path,
                file_size: @file_size,
                modified_time: @modified_time,
                duration_seconds: @duration_seconds,
                artist: @artist,
                album: @album,
                title: @title,
                scanned_at: @scanned_at,
                last_tagged_at: @last_tagged_at,
                tagged: null,
                tagged_version: null,
                chromaprint: null,
                calibration_hash: null,
                needs_tagging: true,
                is_valid: true,
                // Tag writing projection state fields
                last_written_mode: @last_written_mode,
                last_written_calibration_hash: null,
                last_written_at: null,
                has_nomarr_namespace: @has_nomarr_namespace == null ? false : @has_nomarr_namespace,
                write_claimed_by: null,
                write_claimed_at: null
            }
            UPDATE {
                library_id: @library_id,
                path: @path,
                file_size: @file_size,
                modified_time: @modified_time,
                duration_seconds: @duration_seconds,
                artist: @artist,
                album: @album,
                title: @title,
                scanned_at: @scanned_at,
                last_tagged_at: @last_tagged_at != null ? @last_tagged_at : OLD.last_tagged_at,
                has_nomarr_namespace: @has_nomarr_namespace != null ? @has_nomarr_namespace : OLD.has_nomarr_namespace,
                last_written_mode: @last_written_mode != null ? @last_written_mode : OLD.last_written_mode
            }
            IN library_files
            RETURN NEW._id
            """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "library_id": library_id,
                        "path": absolute_path,
                        "normalized_path": normalized_path,
                        "file_size": file_size,
                        "modified_time": modified_time,
                        "duration_seconds": duration_seconds,
                        "artist": artist,
                        "album": album,
                        "title": title,
                        "scanned_at": scanned_at,
                        "last_tagged_at": last_tagged_at,
                        "has_nomarr_namespace": has_nomarr_namespace,
                        "last_written_mode": last_written_mode,
                    },
                ),
            ),
        )

        result = next(cursor)
        return str(result)

    def delete_library_file(self, file_id: str) -> None:
        """Remove a file from the library and clean up entity edges.

        Args:
            file_id: Document _id (e.g., "library_files/12345")

        """
        # Delete vectors from ALL backbones (hot + cold) via centralized orchestration
        if self.parent_db is not None:
            self.parent_db.delete_vectors_by_file_id(file_id)

        # Delete segment_scores_stats (derived data)
        self.db.aql.execute(
            """
            FOR doc IN segment_scores_stats
                FILTER doc.file_id == @file_id
                REMOVE doc IN segment_scores_stats
            """,
            bind_vars={"file_id": file_id},
        )

        # Delete entity edges (referential integrity)
        self.db.aql.execute(
            """
            FOR edge IN song_tag_edges
                FILTER edge._from == @file_id
                REMOVE edge IN song_tag_edges
            """,
            bind_vars={"file_id": file_id},
        )

        # Then delete the file
        self.db.aql.execute(
            """
            REMOVE PARSE_IDENTIFIER(@file_id).key IN library_files
            """,
            bind_vars={"file_id": file_id},
        )

    def upsert_batch(self, file_docs: list[dict[str, Any]]) -> int:
        """Batch upsert file documents to ArangoDB.

        More efficient than individual upserts - reduces DB roundtrips.
        Uses (library_id, normalized_path) as unique key for upsert logic.

        Args:
            file_docs: List of file documents. Each must have:
                - library_id: Library document _id
                - normalized_path: POSIX-style path relative to library root
                - Other fields as needed (file_size, modified_time, etc.)

        Returns:
            Number of documents processed

        Note: ArangoDB UPSERT does not reliably distinguish inserted vs updated.
        Workflows must not depend on this split for correctness.

        """
        if not file_docs:
            return 0

        # Use AQL UPSERT for atomic insert-or-update
        # Key on (library_id, normalized_path) tuple
        self.db.aql.execute(
            """
            FOR doc IN @docs
                UPSERT {
                    library_id: doc.library_id,
                    normalized_path: doc.normalized_path
                }
                INSERT doc
                UPDATE doc
                IN library_files
            """,
            bind_vars={"docs": file_docs},
        )

        return len(file_docs)

    def update_file_path(
        self,
        file_id: str,
        new_path: str,
        file_size: int,
        modified_time: int,
        artist: str | None = None,
        album: str | None = None,
        title: str | None = None,
        duration_seconds: float | None = None,
        normalized_path: str | None = None,
    ) -> None:
        """Update file path and metadata (for moved files).

        Updates filesystem and metadata fields but preserves ML tags.

        Args:
            file_id: Document _id (e.g., "library_files/12345")
            new_path: New file path
            file_size: File size in bytes
            modified_time: Last modified timestamp
            artist: Artist name (optional)
            album: Album name (optional)
            title: Track title (optional)
            duration_seconds: Duration in seconds (optional)
            normalized_path: Normalized path relative to library root (optional)

        """
        # Build update fields - normalized_path only included when provided
        update_fields = {
            "path": "@new_path",
            "file_size": "@file_size",
            "modified_time": "@modified_time",
            "is_valid": "1",
            "artist": "@artist",
            "album": "@album",
            "title": "@title",
            "duration_seconds": "@duration_seconds",
            "scanned_at": "@scanned_at",
        }
        bind_vars: dict[str, Any] = {
            "file_id": file_id,
            "new_path": new_path,
            "file_size": file_size,
            "modified_time": modified_time,
            "artist": artist,
            "album": album,
            "title": title,
            "duration_seconds": duration_seconds,
            "scanned_at": now_ms().value,
        }

        if normalized_path is not None:
            update_fields["normalized_path"] = "@normalized_path"
            bind_vars["normalized_path"] = normalized_path

        # Build AQL with dynamic fields
        field_assignments = ", ".join(f"{k}: {v}" for k, v in update_fields.items())
        aql = f"""
            UPDATE PARSE_IDENTIFIER(@file_id).key WITH {{
                {field_assignments}
            }} IN library_files
            """

        self.db.aql.execute(aql, bind_vars=bind_vars)

    def bulk_delete_files(self, paths: list[str]) -> int:
        """Delete multiple files by path and clean up entity edges.

        Args:
            paths: List of file paths to delete

        Returns:
            Number of files deleted

        """
        if not paths:
            return 0

        # Collect file_ids for bulk vector deletion
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                "FOR f IN library_files FILTER f.path IN @paths RETURN f._id",
                bind_vars={"paths": paths},
            ),
        )
        file_ids = list(cursor)

        # Delete vectors from ALL backbones (hot + cold) via centralized orchestration
        if self.parent_db is not None and file_ids:
            self.parent_db.delete_vectors_by_file_ids(file_ids)

        # Delete segment_scores_stats (derived data — single-pass via collected IDs)
        if file_ids:
            self.db.aql.execute(
                """
                FOR doc IN segment_scores_stats
                    FILTER doc.file_id IN @file_ids
                    REMOVE doc IN segment_scores_stats
                """,
                bind_vars={"file_ids": file_ids},
            )

        # Delete edges (edges go _from=library_files/* -> _to=tags/*)
        self.db.aql.execute(
            """
            FOR file IN library_files
                FILTER file.path IN @paths
                FOR edge IN song_tag_edges
                    FILTER edge._from == file._id
                    REMOVE edge IN song_tag_edges
            """,
            bind_vars={"paths": paths},
        )

        # Delete files and count
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                FOR file IN library_files
                    FILTER file.path IN @paths
                    REMOVE file IN library_files
                    COLLECT WITH COUNT INTO deleted
                    RETURN deleted
                """,
                bind_vars={"paths": paths},
            ),
        )

        results = list(cursor)
        return results[0] if results else 0
