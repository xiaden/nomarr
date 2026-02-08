"""Libraries operations for ArangoDB.

CRITICAL: All mutations by _id must use PARSE_IDENTIFIER(@id).key
to extract the document key for UPDATE/REMOVE operations.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor


class LibrariesOperations:
    """Operations for the libraries collection."""

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db
        self.collection = db.collection("libraries")

    def create_library(
        self,
        name: str,
        root_path: str,
        is_enabled: bool = True,
        watch_mode: str = "off",
        file_write_mode: str = "full",
    ) -> str:
        """Create a new library entry.

        Args:
            name: Library name (must be unique, can be auto-generated from path)
            root_path: Absolute path to library root
            is_enabled: Whether library is enabled for scanning
            watch_mode: File watching mode ('off', 'event', or 'poll')
            file_write_mode: Tag write mode ('none', 'minimal', or 'full')

        Returns:
            Library _id (e.g., "libraries/12345")

        Raises:
            Duplicate key error if name already exists

        """
        now = now_ms().value

        result = cast(
            "dict[str, Any]",
            self.collection.insert(
                {
                    "name": name,
                    "root_path": root_path,
                    "is_enabled": is_enabled,
                    "watch_mode": watch_mode,
                    "file_write_mode": file_write_mode,
                    "scan_status": "idle",
                    "scan_progress": 0,
                    "scan_total": 0,
                    "scanned_at": None,
                    "scan_error": None,
                    "created_at": now,
                    "updated_at": now,
                },
            ),
        )

        return str(result["_id"])

    def get_library(self, library_id: str) -> dict[str, Any] | None:
        r"""Get a library by _id or _key.

        Args:
            library_id: Library _id (e.g., \"libraries/12345\") or just _key (e.g., \"12345\")

        Returns:
            Library dict or None if not found

        """
        # Normalize: if not prefixed with collection name, add it
        if not library_id.startswith("libraries/"):
            library_id = f"libraries/{library_id}"

        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            RETURN DOCUMENT(@library_id)
            """,
                bind_vars={"library_id": library_id},
            ),
        )

        return next(cursor, None)

    def get_library_by_name(self, name: str) -> dict[str, Any] | None:
        """Get a library by name.

        Args:
            name: Library name

        Returns:
            Library dict or None if not found

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR lib IN libraries
                FILTER lib.name == @name
                SORT lib._key
                LIMIT 1
                RETURN lib
            """,
                bind_vars={"name": name},
            ),
        )
        return next(cursor, None)

    def list_libraries(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        """List all libraries.

        Args:
            enabled_only: If True, only return enabled libraries

        Returns:
            List of library dicts

        """
        filter_clause = "FILTER lib.is_enabled == true" if enabled_only else ""

        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                f"""
            FOR lib IN libraries
                {filter_clause}
                SORT lib.created_at ASC
                RETURN lib
            """,
            ),
        )
        return list(cursor)

    def list_watchable_libraries(self) -> list[dict[str, Any]]:
        """List libraries that should be watched (enabled + watch_mode != 'off').

        Used by FileWatcherService to sync watchers with DB state.

        Returns:
            List of library dicts with _id, root_path, watch_mode

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR lib IN libraries
                FILTER lib.is_enabled == true
                FILTER lib.watch_mode != null AND lib.watch_mode != "off"
                SORT lib.created_at ASC
                RETURN { _id: lib._id, root_path: lib.root_path, watch_mode: lib.watch_mode }
            """,
            ),
        )
        return list(cursor)

    def update_library(
        self,
        library_id: str,
        name: str | None = None,
        root_path: str | None = None,
        is_enabled: bool | None = None,
        watch_mode: str | None = None,
        file_write_mode: str | None = None,
    ) -> None:
        """Update library fields.

        Args:
            library_id: Library _id (e.g., "libraries/12345")
            name: New name (optional)
            root_path: New root path (optional)
            is_enabled: New enabled status (optional)
            watch_mode: New watch mode ('off', 'event', 'poll') (optional)
            file_write_mode: New file write mode ('none', 'minimal', 'full') (optional)

        """
        update_fields: dict[str, Any] = {"updated_at": now_ms().value}

        if name is not None:
            update_fields["name"] = name
        if root_path is not None:
            update_fields["root_path"] = root_path
        if is_enabled is not None:
            update_fields["is_enabled"] = is_enabled
        if watch_mode is not None:
            if watch_mode not in ("off", "event", "poll"):
                msg = f"Invalid watch_mode: {watch_mode}. Must be 'off', 'event', or 'poll'"
                raise ValueError(msg)
            update_fields["watch_mode"] = watch_mode
        if file_write_mode is not None:
            if file_write_mode not in ("none", "minimal", "full"):
                msg = f"Invalid file_write_mode: {file_write_mode}. Must be 'none', 'minimal', or 'full'"
                raise ValueError(msg)
            update_fields["file_write_mode"] = file_write_mode

        self.db.aql.execute(
            """
            UPDATE PARSE_IDENTIFIER(@library_id).key WITH @fields IN libraries
            """,
            bind_vars={"library_id": library_id, "fields": update_fields},
        )

    def delete_library(self, library_id: str) -> None:
        """Delete a library.

        Args:
            library_id: Library _id (e.g., "libraries/12345")

        """
        self.db.aql.execute(
            """
            REMOVE PARSE_IDENTIFIER(@library_id).key IN libraries
            """,
            bind_vars={"library_id": library_id},
        )

    def update_scan_status(
        self,
        library_id: str,
        status: str | None = None,
        progress: int | None = None,
        total: int | None = None,
        error: str | None = None,
        scan_status: str | None = None,
        scan_progress: int | None = None,
        scan_total: int | None = None,
        scan_error: str | None = None,
    ) -> None:
        """Update library scan status.

        Only updates fields that are explicitly provided. Does not reset
        scan_status when only updating progress/total.

        When status is set to 'complete', scan_error is automatically cleared
        unless an explicit error value is provided.

        Args:
            library_id: Library _id (e.g., "libraries/12345")
            status or scan_status: Status ('idle', 'scanning', 'complete', 'error')
            progress or scan_progress: Number of files scanned
            total or scan_total: Total files to scan
            error or scan_error: Error message if status is 'error'

        """
        # Support both old and new parameter names
        # IMPORTANT: Only include scan_status if explicitly provided
        final_status = status or scan_status  # None if not provided
        final_progress = progress if progress is not None else scan_progress
        final_total = total if total is not None else scan_total
        final_error = error or scan_error

        # Build update fields dynamically - only include what was provided
        update_fields: dict[str, Any] = {"updated_at": now_ms().value}

        if final_status is not None:
            update_fields["scan_status"] = final_status
            if final_status == "complete":
                update_fields["scanned_at"] = now_ms().value
                # Clear scan_error on successful completion unless explicitly set
                if final_error is None:
                    update_fields["scan_error"] = None

        if final_progress is not None:
            update_fields["scan_progress"] = final_progress

        if final_total is not None:
            update_fields["scan_total"] = final_total

        if final_error is not None:
            update_fields["scan_error"] = final_error

        self.db.aql.execute(
            """
            UPDATE PARSE_IDENTIFIER(@library_id).key WITH @fields IN libraries
            """,
            bind_vars=cast("dict[str, Any]", {"library_id": library_id, "fields": update_fields}),
        )

    def find_library_containing_path(self, file_path: str) -> dict[str, Any] | None:
        """Find the library that contains the given file path.

        Uses path prefix matching to determine which library owns a file.
        Returns the most specific (longest) matching library root.

        Args:
            file_path: Absolute file path to check

        Returns:
            Library dict if found, None otherwise

        Example:
            >>> ops.find_library_containing_path("/music/rock/song.mp3")
            {"_id": "libraries/123", "name": "My Music", "root_path": "/music", ...}

        """
        # Normalize the input path
        try:
            normalized_path = Path(file_path).resolve()
        except (ValueError, OSError):
            return None

        # Get all libraries ordered by root_path length (longest first)
        # This ensures we match the most specific library
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
            FOR lib IN libraries
                SORT LENGTH(lib.root_path) DESC
                RETURN lib
            """,
            ),
        )

        library: dict[str, Any]
        for library in cursor:
            library_root = Path(library["root_path"]).resolve()

            # Check if file_path is within this library's root
            try:
                normalized_path.relative_to(library_root)
                # Success - this library contains the file
                return library
            except ValueError:
                # Not relative to this library root
                continue

        return None

    def mark_scan_started(self, library_id: str, scan_type: str) -> None:
        """Mark a scan as started by updating library document.

        Sets last_scan_started_at to current timestamp and records scan type.
        Used to detect interrupted scans on restart.

        Args:
            library_id: Library document _id (e.g., "libraries/12345")
            scan_type: Scan type string ("quick" or "full")

        """
        now = now_ms().value

        self.db.aql.execute(
            """
            UPDATE PARSE_IDENTIFIER(@library_id).key WITH {
                last_scan_started_at: @timestamp,
                scan_type_in_progress: @scan_type
            } IN libraries
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "library_id": library_id,
                    "timestamp": now,
                    "scan_type": scan_type,
                },
            ),
        )

    def mark_scan_completed(self, library_id: str) -> None:
        """Mark a scan as completed by clearing start timestamp.

        Args:
            library_id: Library document _id (e.g., "libraries/12345")

        """
        now = now_ms().value

        self.db.aql.execute(
            """
            UPDATE PARSE_IDENTIFIER(@library_id).key WITH {
                last_scan_at: @timestamp,
                last_scan_started_at: null,
                scan_type_in_progress: null
            } IN libraries
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "library_id": library_id,
                    "timestamp": now,
                },
            ),
        )

    def get_scan_state(self, library_id: str) -> dict[str, Any] | None:
        """Get current scan state from library document.

        Args:
            library_id: Library document _id (e.g., "libraries/12345")

        Returns:
            Dict with last_scan_started_at, last_scan_at, scan_type_in_progress
            or None if library not found

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                FOR lib IN libraries
                    FILTER lib._id == @library_id
                    RETURN {
                        last_scan_started_at: lib.last_scan_started_at,
                        last_scan_at: lib.last_scan_at,
                        scan_type_in_progress: lib.scan_type_in_progress
                    }
                """,
                bind_vars={"library_id": library_id},
            ),
        )

        results = list(cursor)
        return results[0] if results else None

    def check_interrupted_scan(self, library_id: str) -> tuple[bool, str | None]:
        r"""Check if a scan was interrupted.

        Args:
            library_id: Library document _id (e.g., \"libraries/12345\")

        Returns:
            Tuple of (was_interrupted, scan_type) where scan_type is
            ``"quick"`` or ``"full"`` if interrupted, ``None`` otherwise.

        A scan is interrupted if:
        - last_scan_started_at is set, AND
        - last_scan_started_at > last_scan_at (or last_scan_at is null)

        Uses integer timestamp comparison.

        """
        state = self.get_scan_state(library_id)
        if not state or not state.get("last_scan_started_at"):
            return False, None

        scan_type: str | None = state.get("scan_type_in_progress")

        # Interrupted if started but never completed
        if not state.get("last_scan_at"):
            return True, scan_type

        # Or if started after last completion (integer comparison)
        interrupted = state["last_scan_started_at"] > state["last_scan_at"]
        return interrupted, scan_type if interrupted else None
