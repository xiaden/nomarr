"""Libraries operations for ArangoDB.

CRITICAL: All mutations by _id must use PARSE_IDENTIFIER(@id).key
to extract the document key for UPDATE/REMOVE operations.
"""

from typing import Any, cast

from arango.cursor import Cursor
from arango.database import StandardDatabase

from nomarr.helpers.time_helper import now_ms


class LibrariesOperations:
    """Operations for the libraries collection."""

    def __init__(self, db: StandardDatabase) -> None:
        self.db = db
        self.collection = db.collection("libraries")

    def create_library(
        self,
        name: str,
        root_path: str,
        is_enabled: bool = True,
        is_default: bool = False,
        watch_mode: str = "off",
    ) -> str:
        """Create a new library entry.

        Args:
            name: Library name (must be unique, can be auto-generated from path)
            root_path: Absolute path to library root
            is_enabled: Whether library is enabled for scanning
            is_default: Whether this is the default library
            watch_mode: File watching mode ('off', 'event', or 'poll')

        Returns:
            Library _id (e.g., "libraries/12345")

        Raises:
            Duplicate key error if name already exists
        """
        now = now_ms().value

        # If setting as default, clear other defaults first
        if is_default:
            self.db.aql.execute(
                """
                FOR lib IN libraries
                    FILTER lib.is_default == true
                    UPDATE lib WITH { is_default: false } IN libraries
                """
            )

        result = cast(
            dict[str, Any],
            self.collection.insert(
                {
                    "name": name,
                    "root_path": root_path,
                    "is_enabled": is_enabled,
                    "is_default": is_default,
                    "watch_mode": watch_mode,
                    "scan_status": "idle",
                    "scan_progress": 0,
                    "scan_total": 0,
                    "scanned_at": None,
                    "scan_error": None,
                    "created_at": now,
                    "updated_at": now,
                }
            ),
        )

        return str(result["_id"])

    def get_library(self, library_id: str) -> dict[str, Any] | None:
        """Get a library by _id or _key.

        Args:
            library_id: Library _id (e.g., \"libraries/12345\") or just _key (e.g., \"12345\")

        Returns:
            Library dict or None if not found
        """
        # Normalize: if not prefixed with collection name, add it
        if not library_id.startswith("libraries/"):
            library_id = f"libraries/{library_id}"

        cursor = cast(
            Cursor,
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
            Cursor,
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
            Cursor,
            self.db.aql.execute(
                f"""
            FOR lib IN libraries
                {filter_clause}
                SORT lib.created_at ASC
                RETURN lib
            """
            ),
        )
        return list(cursor)

    def get_default_library(self) -> dict[str, Any] | None:
        """Get the default library.

        Returns:
            Default library dict or None if no default set
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR lib IN libraries
                FILTER lib.is_default == true
                SORT lib._key
                LIMIT 1
                RETURN lib
            """
            ),
        )
        return next(cursor, None)

    def update_library(
        self,
        library_id: str,
        name: str | None = None,
        root_path: str | None = None,
        is_enabled: bool | None = None,
        is_default: bool | None = None,
        watch_mode: str | None = None,
    ) -> None:
        """Update library fields.

        Args:
            library_id: Library _id (e.g., "libraries/12345")
            name: New name (optional)
            root_path: New root path (optional)
            is_enabled: New enabled status (optional)
            is_default: New default status (optional)
            watch_mode: New watch mode ('off', 'event', 'poll') (optional)
        """
        update_fields: dict[str, Any] = {"updated_at": now_ms().value}

        if name is not None:
            update_fields["name"] = name
        if root_path is not None:
            update_fields["root_path"] = root_path
        if is_enabled is not None:
            update_fields["is_enabled"] = is_enabled
        if is_default is not None:
            update_fields["is_default"] = is_default
            # Clear other defaults if setting as default
            if is_default:
                self.db.aql.execute(
                    """
                    FOR lib IN libraries
                        FILTER lib._id != @library_id AND lib.is_default == true
                        UPDATE lib WITH { is_default: false } IN libraries
                    """,
                    bind_vars={"library_id": library_id},
                )
        if watch_mode is not None:
            if watch_mode not in ("off", "event", "poll"):
                raise ValueError(f"Invalid watch_mode: {watch_mode}. Must be 'off', 'event', or 'poll'")
            update_fields["watch_mode"] = watch_mode

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

        Args:
            library_id: Library _id (e.g., "libraries/12345")
            status or scan_status: Status ('idle', 'scanning', 'complete', 'error')
            progress or scan_progress: Number of files scanned
            total or scan_total: Total files to scan
            error or scan_error: Error message if status is 'error'
        """
        # Support both old and new parameter names
        final_status = status or scan_status or "idle"
        final_progress = progress if progress is not None else (scan_progress or 0)
        final_total = total if total is not None else (scan_total or 0)
        final_error = error or scan_error

        update_fields = {
            "scan_status": final_status,
            "scan_progress": final_progress,
            "scan_total": final_total,
            "scan_error": final_error,
            "scanned_at": now_ms().value if final_status == "complete" else None,
            "updated_at": now_ms().value,
        }

        self.db.aql.execute(
            """
            UPDATE PARSE_IDENTIFIER(@library_id).key WITH @fields IN libraries
            """,
            bind_vars=cast(dict[str, Any], {"library_id": library_id, "fields": update_fields}),
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
        from pathlib import Path

        # Normalize the input path
        try:
            normalized_path = Path(file_path).resolve()
        except (ValueError, OSError):
            return None

        # Get all libraries ordered by root_path length (longest first)
        # This ensures we match the most specific library
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR lib IN libraries
                SORT LENGTH(lib.root_path) DESC
                RETURN lib
            """
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

    def mark_scan_started(self, library_id: str, full_scan: bool) -> None:
        """Mark a scan as started by updating library document.

        Sets last_scan_started_at to current timestamp and records scan type.
        Used to detect interrupted scans on restart.

        Args:
            library_id: Library document _id (e.g., "libraries/12345")
            full_scan: True if scanning entire library, False if targeted scan
        """
        now = now_ms().value

        self.db.aql.execute(
            """
            UPDATE PARSE_IDENTIFIER(@library_id).key WITH {
                last_scan_started_at: @timestamp,
                full_scan_in_progress: @full_scan
            } IN libraries
            """,
            bind_vars=cast(
                dict[str, Any],
                {
                    "library_id": library_id,
                    "timestamp": now,
                    "full_scan": full_scan,
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
                full_scan_in_progress: false
            } IN libraries
            """,
            bind_vars=cast(
                dict[str, Any],
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
            Dict with last_scan_started_at, last_scan_at, full_scan_in_progress
            or None if library not found
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
                FOR lib IN libraries
                    FILTER lib._id == @library_id
                    RETURN {
                        last_scan_started_at: lib.last_scan_started_at,
                        last_scan_at: lib.last_scan_at,
                        full_scan_in_progress: lib.full_scan_in_progress
                    }
                """,
                bind_vars={"library_id": library_id},
            ),
        )

        results = list(cursor)
        return results[0] if results else None

    def check_interrupted_scan(self, library_id: str) -> tuple[bool, bool]:
        """Check if a scan was interrupted.

        Args:
            library_id: Library document _id (e.g., \"libraries/12345\")

        Returns:
            Tuple of (was_interrupted, was_full_scan)

        A scan is interrupted if:
        - last_scan_started_at is set, AND
        - last_scan_started_at > last_scan_at (or last_scan_at is null)

        Uses integer timestamp comparison.
        """
        state = self.get_scan_state(library_id)
        if not state or not state.get("last_scan_started_at"):
            return False, False

        # Interrupted if started but never completed
        if not state.get("last_scan_at"):
            return True, bool(state.get("full_scan_in_progress", False))

        # Or if started after last completion (integer comparison)
        interrupted = state["last_scan_started_at"] > state["last_scan_at"]
        return interrupted, bool(state.get("full_scan_in_progress", False))
