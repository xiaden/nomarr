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
    ) -> str:
        """Insert or update a library file entry.

        Uses absolute path as upsert key (globally unique across all libraries).
        Stores both absolute path (for filesystem access) and normalized_path
        (POSIX relative path for display/identity within library).

        Library ownership is tracked via ``library_contains_file`` edges,
        not via a ``library_id`` field on the document.

        State fields (tagged, calibrated, etc.) are managed via
        ``file_has_state`` edges, not flat fields on the document.

        Args:
            path: LibraryPath with validated file path (must have status == "valid")
            library_id: ID of owning library (used for edge, not stored on doc)
            file_size: File size in bytes
            modified_time: Last modified timestamp
            duration_seconds: Audio duration
            artist: Artist name
            album: Album name
            title: Track title
            last_tagged_at: Last tagging timestamp (triggers set_tagged edge)

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

        # Upsert file document — key on absolute path (globally unique)
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            UPSERT { path: @path }
            INSERT {
                path: @path,
                normalized_path: @normalized_path,
                file_size: @file_size,
                modified_time: @modified_time,
                duration_seconds: @duration_seconds,
                artist: @artist,
                album: @album,
                title: @title,
                scanned_at: @scanned_at,
                chromaprint: null
            }
            UPDATE {
                normalized_path: @normalized_path,
                file_size: @file_size,
                modified_time: @modified_time,
                duration_seconds: @duration_seconds,
                artist: @artist,
                album: @album,
                title: @title,
                scanned_at: @scanned_at
            }
            IN library_files
            RETURN NEW._id
            """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "path": absolute_path,
                        "normalized_path": normalized_path,
                        "file_size": file_size,
                        "modified_time": modified_time,
                        "duration_seconds": duration_seconds,
                        "artist": artist,
                        "album": album,
                        "title": title,
                        "scanned_at": scanned_at,
                    },
                ),
            ),
        )

        result = next(cursor)
        file_id = str(result)

        # Upsert library->file edge for ownership tracking
        self.db.aql.execute(
            """
            UPSERT { _from: @library_id, _to: @file_id }
            INSERT { _from: @library_id, _to: @file_id }
            UPDATE {}
            IN library_contains_file
            """,
            bind_vars={"library_id": library_id, "file_id": file_id},
        )

        # Initialize file state edges (all-negative) for new files
        if self.parent_db is not None:
            self.parent_db.file_states.initialize_file_states(file_id)

            # File was previously tagged — transition to tagged state
            if last_tagged_at is not None:
                self.parent_db.file_states.set_tagged(file_id)

        return file_id

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
            FOR edge IN song_has_tags
                FILTER edge._from == @file_id
                REMOVE edge IN song_has_tags
            """,
            bind_vars={"file_id": file_id},
        )


        # Delete file state edges
        if self.parent_db is not None:
            self.parent_db.file_states.clear_all_states(file_id)
        # Then delete the file
        self.db.aql.execute(
            """
            REMOVE PARSE_IDENTIFIER(@file_id).key IN library_files
            """,
            bind_vars={"file_id": file_id},
        )

    def upsert_batch(self, file_docs: list[dict[str, Any]]) -> list[str]:
        """Batch upsert file documents to ArangoDB.

        More efficient than individual upserts - reduces DB roundtrips.
        Uses absolute path as unique key (globally unique across libraries).

        Library ownership is tracked via ``library_contains_file`` edges,
        not via a ``library_id`` field on the document.

        Args:
            file_docs: List of file documents. Each must have:
                - path: Absolute file path (used as upsert key)
                - library_id: Library document _id (for edge creation, not stored)
                - normalized_path: POSIX-style path relative to library root
                - Other fields as needed (file_size, modified_time, etc.)

        Returns:
            List of document _ids (inserted or updated)

        Note: ArangoDB UPSERT does not reliably distinguish inserted vs updated.
        Workflows must not depend on this split for correctness.

        """
        if not file_docs:
            return []

        # Extract library_ids before removing from docs (needed for edge creation)
        library_ids = [doc.get("library_id") for doc in file_docs]

        # Remove library_id from docs - ownership tracked via edges
        clean_docs = [{k: v for k, v in doc.items() if k != "library_id"} for doc in file_docs]

        # Use AQL UPSERT for atomic insert-or-update, return _ids
        # Key on path (absolute path is globally unique)
        cursor = self.db.aql.execute(
            """
            FOR doc IN @docs
                UPSERT { path: doc.path }
                INSERT doc
                UPDATE doc
                IN library_files
                RETURN NEW._id
            """,
            bind_vars={"docs": clean_docs},
        )

        result: list[str] = list(cursor)  # type: ignore[arg-type]

        # Batch upsert edges for library ownership
        edge_docs = [
            {"_from": lib_id, "_to": file_id}
            for lib_id, file_id in zip(library_ids, result, strict=True)
            if lib_id is not None
        ]
        if edge_docs:
            self.db.aql.execute(
                """
                FOR edge IN @edges
                    UPSERT { _from: edge._from, _to: edge._to }
                    INSERT edge
                    UPDATE {}
                    IN library_contains_file
                """,
                bind_vars={"edges": edge_docs},
            )

        # Initialize file state edges for all upserted files
        if self.parent_db is not None and result:
            self.parent_db.file_states.initialize_file_states_batch(result)

        return result

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

    def update_file_modified_time(self, file_key: str, modified_time_ms: int) -> None:
        """Update only the modified_time of a library file after a tag write.

        Args:
            file_key: Document _key (e.g., "12345")
            modified_time_ms: New mtime in milliseconds since epoch

        """
        bind_vars: dict[str, Any] = {"key": file_key, "mtime": modified_time_ms}
        self.db.aql.execute(
            "UPDATE @key WITH { modified_time: @mtime } IN library_files",
            bind_vars=bind_vars,
        )

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
                FOR edge IN song_has_tags
                    FILTER edge._from == file._id
                    REMOVE edge IN song_has_tags
            """,
            bind_vars={"paths": paths},
        )

        # Delete file state edges
        if file_ids and self.parent_db is not None:
            self.parent_db.file_states.clear_all_states_batch(file_ids)
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


    def delete_files_for_library(self, library_id: str) -> int:
        """Delete all files for a library and cascade to derived data.

        Uses edge traversal via ``library_contains_file`` for library filtering.

        Removes, in order:
        1. Track-level embedding vectors (all backbones, hot + cold)
        2. segment_scores_stats (per-label head stats)
        3. song_has_tags (entity edges)
        4. file_has_state (state edges)
        5. library_contains_file edges
        6. library_files documents

        Args:
            library_id: Library _id (e.g., "libraries/12345")

        Returns:
            Number of library_files documents deleted

        """
        if not library_id:
            return 0

        # Collect file_ids via edge traversal
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                "FOR f IN OUTBOUND @library_id library_contains_file RETURN f._id",
                bind_vars={"library_id": library_id},
            ),
        )
        file_ids = list(cursor)

        if not file_ids:
            return 0

        # Delete vectors from ALL backbones (hot + cold)
        if self.parent_db is not None:
            self.parent_db.delete_vectors_by_file_ids(file_ids)

        # Delete segment_scores_stats (derived data)
        self.db.aql.execute(
            """
            FOR doc IN segment_scores_stats
                FILTER doc.file_id IN @file_ids
                REMOVE doc IN segment_scores_stats
            """,
            bind_vars={"file_ids": file_ids},
        )

        # Delete song_has_tags
        self.db.aql.execute(
            """
            FOR edge IN song_has_tags
                FILTER edge._from IN @file_ids
                REMOVE edge IN song_has_tags
            """,
            bind_vars={"file_ids": file_ids},
        )

        # Delete file state edges
        if self.parent_db is not None:
            self.parent_db.file_states.clear_all_states_batch(file_ids)

        # Delete library_contains_file edges
        self.db.aql.execute(
            """
            FOR edge IN library_contains_file
                FILTER edge._from == @library_id
                REMOVE edge IN library_contains_file
            """,
            bind_vars={"library_id": library_id},
        )

        # Delete library_files documents by collected IDs
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                FOR f IN library_files
                    FILTER f._id IN @file_ids
                    REMOVE f IN library_files
                    COLLECT WITH COUNT INTO deleted
                    RETURN deleted
                """,
                bind_vars={"file_ids": file_ids},
            ),
        )
        results = list(cursor)
        return results[0] if results else 0


    def get_file_library_key(self, file_id: str) -> str | None:
        """Return the library ``_key`` for a given file document ID.

        Uses edge traversal via ``library_contains_file`` to find the owning
        library, then returns the trailing key component.

        Args:
            file_id: Document ``_id`` (e.g. ``"library_files/12345"``).

        Returns:
            Library ``_key`` string, or ``None`` if no edge found.

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                FOR edge IN library_contains_file
                    FILTER edge._to == @file_id
                    LIMIT 1
                    RETURN edge._from
                """,
                bind_vars={"file_id": file_id},
            ),
        )
        results = list(cursor)
        if not results or not results[0]:
            return None
        library_id: str = results[0]
        return library_id.split("/")[-1]
