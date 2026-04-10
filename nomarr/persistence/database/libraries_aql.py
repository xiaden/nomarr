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

    from nomarr.persistence.db import Database


def list_all_library_keys(db: DatabaseLike) -> list[str]:
    """Return all library document keys."""
    cursor = cast(
        "Cursor",
        db.aql.execute(
            """
            FOR library IN libraries
                RETURN library._key
            """,
        ),
    )
    return cast("list[str]", list(cursor))


class LibrariesOperations:
    """Operations for the libraries collection."""

    def __init__(self, db: DatabaseLike, parent_db: "Database | None" = None) -> None:
        self.db = db
        self.collection = db.collection("libraries")
        self.parent_db = parent_db

    def create_library(
        self,
        name: str,
        root_path: str,
        is_enabled: bool = True,
        watch_mode: str = "off",
        file_write_mode: str = "full",
        library_auto_write: bool = False,
    ) -> str:
        """Create a new library entry.

        Args:
            name: Library name (must be unique, can be auto-generated from path)
            root_path: Absolute path to library root
            is_enabled: Whether library is enabled for scanning
            watch_mode: File watching mode ('off', 'event', or 'poll')
            file_write_mode: Tag write mode ('none', 'minimal', or 'full')
            library_auto_write: Whether to enable automatic tag writing for the library.

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
                    "library_auto_write": library_auto_write,
                    "created_at": now,
                    "updated_at": now,
                },
            ),
        )

        return str(result["_id"])

    def get_library(self, library_id: str) -> dict[str, Any] | None:
        r"""Get a library by _id or _key.

        Joins scan state from library_scans collection for API compatibility.

        Args:
            library_id: Library _id (e.g., \"libraries/12345\") or just _key (e.g., \"12345\")

        Returns:
            Library dict with scan state merged, or None if not found

        """
        # Normalize: if not prefixed with collection name, add it
        if not library_id.startswith("libraries/"):
            library_id = f"libraries/{library_id}"

        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                LET lib = DOCUMENT(@library_id)
                FILTER lib != null
                LET scan = FIRST(
                    FOR s IN OUTBOUND lib library_has_scan
                        RETURN s
                )
                RETURN MERGE(lib, {
                    scan_status: scan.status || "idle",
                    scan_progress: scan.files_processed || 0,
                    scan_total: scan.files_total || 0,
                    scanned_at: scan.completed_at,
                    scan_error: scan.error,
                    last_scan_started_at: scan.started_at,
                    scan_type_in_progress: scan.scan_type
                })
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
        """List all libraries with scan state joined.

        Batch-joins scan state from library_scans collection for API compatibility.

        Args:
            enabled_only: If True, only return enabled libraries

        Returns:
            List of library dicts with scan state merged

        """
        filter_clause = "FILTER lib.is_enabled == true" if enabled_only else ""

        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                f"""
            FOR lib IN libraries
                {filter_clause}
                LET scan = FIRST(
                    FOR s IN OUTBOUND lib library_has_scan
                        RETURN s
                )
                SORT lib.created_at ASC
                RETURN MERGE(lib, {{
                    scan_status: scan.status || "idle",
                    scan_progress: scan.files_processed || 0,
                    scan_total: scan.files_total || 0,
                    scanned_at: scan.completed_at,
                    scan_error: scan.error,
                    last_scan_started_at: scan.started_at,
                    scan_type_in_progress: scan.scan_type
                }})
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
        library_auto_write: bool | None = None,
    ) -> None:
        """Update library fields.

        Args:
            library_id: Library _id (e.g., "libraries/12345")
            name: New name (optional)
            root_path: New root path (optional)
            is_enabled: New enabled status (optional)
            watch_mode: New watch mode ('off', 'event', 'poll') (optional)
            file_write_mode: New file write mode ('none', 'minimal', 'full') (optional)
            library_auto_write: New auto-write setting (optional).

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
        if library_auto_write is not None:
            update_fields["library_auto_write"] = library_auto_write

        self.db.aql.execute(
            """
            UPDATE PARSE_IDENTIFIER(@library_id).key WITH @fields IN libraries
            """,
            bind_vars={"library_id": library_id, "fields": update_fields},
        )

    def update_library_config_fields(
        self,
        library_id: str,
        set_fields: dict[str, Any] | None = None,
        unset_fields: list[str] | None = None,
    ) -> None:
        """Update or remove arbitrary config fields on a library document.

        Uses a two-pass approach: first sets new values, then removes fields
        by setting them to ``None`` with ``keepNull: false``.

        Args:
            library_id: Library _id (e.g., "libraries/12345") or _key
            set_fields: Fields to set/update (values must be serialisable)
            unset_fields: Field names to remove from the document

        """
        if not library_id.startswith("libraries/"):
            library_id = f"libraries/{library_id}"

        if set_fields:
            fields = {**set_fields, "updated_at": now_ms().value}
            self.db.aql.execute(
                "UPDATE PARSE_IDENTIFIER(@id).key WITH @fields IN libraries",
                bind_vars={"id": library_id, "fields": fields},
            )

        if unset_fields:
            null_obj: dict[str, Any] = dict.fromkeys(unset_fields)
            null_obj["updated_at"] = now_ms().value
            self.db.aql.execute(
                "UPDATE PARSE_IDENTIFIER(@id).key WITH @fields IN libraries OPTIONS { keepNull: false }",
                bind_vars={"id": library_id, "fields": null_obj},
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

        Delegates to library_scans.update_scan() for actual storage.
        Maintains backward-compatible parameter names.

        Args:
            library_id: Library _id (e.g., "libraries/12345")
            status or scan_status: Status ('idle', 'scanning', 'complete', 'error')
            progress or scan_progress: Number of files scanned
            total or scan_total: Total files to scan
            error or scan_error: Error message if status is 'error'

        """
        assert self.parent_db is not None, "parent_db required for scan operations"

        # Support both old and new parameter names
        final_status = status or scan_status
        final_progress = progress if progress is not None else scan_progress
        final_total = total if total is not None else scan_total
        final_error = error or scan_error

        # Build update fields for library_scans (using new field names)
        update_fields: dict[str, Any] = {}

        if final_status is not None:
            update_fields["status"] = final_status
            if final_status == "complete":
                update_fields["completed_at"] = now_ms().value
                # Clear error on successful completion unless explicitly set
                if final_error is None:
                    update_fields["error"] = None

        if final_progress is not None:
            update_fields["files_processed"] = final_progress

        if final_total is not None:
            update_fields["files_total"] = final_total

        if final_error is not None:
            update_fields["error"] = final_error

        if update_fields:
            self.parent_db.library_scans.update_scan(library_id, **update_fields)

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
        """Mark a scan as started.

        Sets started_at timestamp and records scan type.
        Used to detect interrupted scans on restart.

        Args:
            library_id: Library document _id (e.g., "libraries/12345")
            scan_type: Scan type string ("quick" or "full")

        """
        assert self.parent_db is not None, "parent_db required for scan operations"
        now = now_ms().value
        self.parent_db.library_scans.update_scan(
            library_id,
            started_at=now,
            scan_type=scan_type,
        )

    def mark_scan_completed(self, library_id: str) -> None:
        """Mark a scan as completed by setting completed_at and clearing started_at.

        Args:
            library_id: Library document _id (e.g., "libraries/12345")

        """
        assert self.parent_db is not None, "parent_db required for scan operations"
        now = now_ms().value
        self.parent_db.library_scans.update_scan(
            library_id,
            completed_at=now,
            started_at=None,
            scan_type=None,
        )

    def get_scan_state(self, library_id: str) -> dict[str, Any] | None:
        """Get current scan state from library_scans collection.

        Args:
            library_id: Library document _id (e.g., "libraries/12345")

        Returns:
            Dict with started_at, completed_at, scan_type
            or None if no scan exists

        """
        assert self.parent_db is not None, "parent_db required for scan operations"
        scan = self.parent_db.library_scans.get_scan_state(library_id)
        if not scan:
            return None

        # Map to backward-compatible field names for check_interrupted_scan
        return {
            "last_scan_started_at": scan.get("started_at"),
            "last_scan_at": scan.get("completed_at"),
            "scan_type_in_progress": scan.get("scan_type"),
        }

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
