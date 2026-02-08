"""File system watcher service for automatic library scanning.

This service monitors library directories for changes and triggers
library scans via LibraryService. It implements debouncing to batch
rapid changes and avoid excessive scanning.

Watch Modes:
- 'event': Real-time filesystem events via watchdog (default)
  - Fast response time (2-5 seconds)
  - May not work reliably on network mounts (NFS/SMB/CIFS)
- 'poll': Periodic full-library scans
  - Slower response time (30-120 seconds)
  - Reliable on network mounts
  - Conservative default: 60 seconds

Architecture:
- One Observer (event mode) or polling task (poll mode) per library
- Events/scans are debounced (configurable quiet period)
- Only relevant file types are processed (audio, playlists, artwork)
- Triggers full library scans; folder-level caching in the scan workflow
  handles incremental optimization
- Calls LibraryService.start_scan_for_library() - NO direct persistence access

CRITICAL (event mode): Watchdog callbacks run on background threads, NOT the asyncio event loop.
Must use thread-safe handoff via loop.call_soon_threadsafe().
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from nomarr.helpers.time_helper import InternalSeconds, internal_s

if TYPE_CHECKING:
    from collections.abc import Callable

    from nomarr.persistence.db import Database
    from nomarr.services.domain.library_svc import LibraryService

logger = logging.getLogger(__name__)


class LibraryEventHandler(FileSystemEventHandler):
    """Handles file system events for a single library."""

    # File extensions we care about
    AUDIO_EXTENSIONS: ClassVar[set[str]] = {
        ".mp3",
        ".flac",
        ".m4a",
        ".ogg",
        ".opus",
        ".wav",
        ".aac",
        ".wv",
        ".ape",
        ".aiff",
        ".aif",
    }
    PLAYLIST_EXTENSIONS: ClassVar[set[str]] = {".m3u", ".m3u8", ".pls"}
    IMAGE_EXTENSIONS: ClassVar[set[str]] = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

    def __init__(
        self,
        library_id: str,
        library_root: Path,
        callback: Callable[[str, str], None],
    ) -> None:
        super().__init__()
        self.library_id = library_id
        self.library_root = library_root
        self.callback = callback

    def on_any_event(self, event: FileSystemEvent) -> None:
        """Filter and forward relevant events."""
        # Ignore directory events (we care about files)
        if event.is_directory:
            return

        # Get path
        path = Path(str(event.src_path))  # type: ignore[arg-type]

        # Filter: only relevant file types
        if not self._is_relevant_file(path):
            logger.debug(f"Ignoring irrelevant file: {path}")
            return

        # Filter: ignore temp/hidden files
        if self._is_ignored_file(path):
            logger.debug(f"Ignoring temp/hidden file: {path}")
            return

        # Convert to relative path
        try:
            relative_path = path.relative_to(self.library_root)
        except ValueError:
            logger.warning(f"Event path {path} not under library root {self.library_root}")
            return

        # Forward to callback (thread-safe handoff)
        logger.debug(f"File event: {event.event_type} - {relative_path}")
        self.callback(self.library_id, str(relative_path))

    def _is_relevant_file(self, path: Path) -> bool:
        """Check if file type is relevant for scanning."""
        suffix = path.suffix.lower()
        return suffix in self.AUDIO_EXTENSIONS or suffix in self.PLAYLIST_EXTENSIONS or suffix in self.IMAGE_EXTENSIONS

    def _is_ignored_file(self, path: Path) -> bool:
        """Check if file should be ignored."""
        name = path.name

        # Hidden files
        if name.startswith("."):
            return True

        # Temp files
        if name.endswith((".tmp", "~")):
            return True

        # OS-specific
        return name in {".DS_Store", "Thumbs.db", "desktop.ini"}


class FileWatcherService:
    """Manages file system watchers for all libraries.

    This service is responsible for:
    1. Starting/stopping watchers per library
    2. Debouncing events (configurable quiet period)
    3. Triggering full library scans via LibraryService

    It does NOT:
    - Access persistence directly (violates architecture)
    - Make domain decisions (when to scan, what to process)
    - Trigger ML/tagging pipelines (those are manual)

    Watch Modes:
    - 'event' (default): Real-time filesystem events via watchdog
    - 'poll': Periodic full-library scans (network-mount-safe)

    Thread Safety:
    - Event mode: Watchdog callbacks execute on background threads
    - Uses lock for pending_changes access
    - Uses loop.call_soon_threadsafe() to schedule async work
    """

    def __init__(
        self,
        db: Database,
        library_service: LibraryService,
        debounce_seconds: float = 2.0,
        event_loop: asyncio.AbstractEventLoop | None = None,
        polling_interval_seconds: float = 60.0,
    ) -> None:
        self.db = db
        self.library_service = library_service
        self.debounce_seconds = debounce_seconds
        # Use provided loop or get running loop (avoid deprecated get_event_loop)
        try:
            self.event_loop = event_loop or asyncio.get_running_loop()
        except RuntimeError:
            # No running loop - create new one (for non-async context)
            self.event_loop = asyncio.new_event_loop()
        self.polling_interval_seconds = polling_interval_seconds

        # Active watchers (event mode: Observer, poll mode: Task or Thread)
        self.observers: dict[str, Any] = {}  # Observer | Task | Thread

        # Debouncing state (thread-safe)
        self._lock = threading.Lock()
        self.pending_changes: set[tuple[str, str]] = set()  # (library_id, relative_path)
        self.debounce_task: asyncio.Task | None = None

        # Polling state (minimal - just last poll time per library)
        self.last_poll_time: dict[str, InternalSeconds] = {}

        # Libraries scheduled for cleanup (when not found)
        self._pending_cleanups: set[str] = set()

        logger.info(
            f"FileWatcherService initialized (debounce={debounce_seconds}s, poll_interval={polling_interval_seconds}s)",
        )

    def _reset_stale_scan_statuses(self) -> None:
        """Reset stale scan_status on startup.

        If a scan was interrupted (server crash/restart), the library may be stuck
        in scan_status='scanning' even though no scan is actually running.
        This resets such libraries to 'idle' so new scans can be started.

        Called once at startup via sync_watchers().
        """
        all_libraries = self.db.libraries.list_libraries()
        reset_count = 0

        for lib in all_libraries:
            if lib.get("scan_status") == "scanning":
                library_id = lib["_id"]
                logger.warning(
                    f"[FileWatcherService] Resetting stale scan_status for library {lib.get('name', library_id)} "
                    f"(was 'scanning' at startup, likely from interrupted scan)",
                )
                self.db.libraries.update_scan_status(
                    library_id,
                    status="idle",
                    error="Scan interrupted by server restart",
                )
                reset_count += 1

        if reset_count > 0:
            logger.info(f"[FileWatcherService] Reset {reset_count} libraries with stale scan_status")

    def sync_watchers(self) -> None:
        """Sync watchers with the library collection (DB is source of truth).

        - Resets stale scan_status on startup (handles interrupted scans from crashes)
        - Starts watchers for libraries in DB with watch_mode != 'off'
        - Stops watchers for libraries no longer in DB or with watch_mode == 'off'

        Should be called on startup and can be called periodically if needed.
        """
        # Reset stale scan_status for all libraries on startup
        # If scan_status is 'scanning' but no scan is actually running (server restart),
        # reset it to 'idle' so users can start new scans
        self._reset_stale_scan_statuses()

        # Get libraries that should be watched from DB
        watchable = self.db.libraries.list_watchable_libraries()
        watchable_ids = {lib["_id"] for lib in watchable}

        # Stop watchers for libraries no longer watchable
        for library_id in list(self.observers.keys()):
            if library_id not in watchable_ids:
                logger.info(f"Library {library_id} no longer needs watching, stopping watcher")
                self.stop_watching_library(library_id)

        # Start watchers for new watchable libraries
        for lib in watchable:
            library_id = lib["_id"]
            if library_id not in self.observers:
                try:
                    self.start_watching_library(library_id)
                except ValueError as e:
                    logger.warning(f"Could not start watcher for library {library_id}: {e}")
                except Exception as e:
                    logger.error(f"Failed to start watcher for library {library_id}: {e}", exc_info=True)

    def _schedule_cleanup(self, library_id: str) -> None:
        """Schedule a library for cleanup (called from polling loop when library not found)."""
        self._pending_cleanups.add(library_id)
        # Schedule actual cleanup on event loop
        with contextlib.suppress(RuntimeError):
            # Event loop not running - just mark for cleanup
            self.event_loop.call_soon_threadsafe(self._do_cleanup, library_id)

    def _do_cleanup(self, library_id: str) -> None:
        """Actually stop watching a library (runs on event loop)."""
        if library_id in self._pending_cleanups:
            self._pending_cleanups.discard(library_id)
            if library_id in self.observers:
                self.stop_watching_library(library_id)

    def start_watching_library(self, library_id: str) -> None:
        """Start watching a library for changes.

        If already watching, restarts the watcher.

        Watch mode is determined by the library's watch_mode field:
        - 'off': No watching (method returns without starting)
        - 'event': Real-time watchdog observer
        - 'poll': Periodic polling loop

        Args:
            library_id: Library document _id (e.g., "libraries/lib1")

        Raises:
            ValueError: If library not found or path invalid

        """
        # Get library info
        library = self.db.libraries.get_library(library_id)
        if not library:
            msg = f"Library {library_id} not found"
            raise ValueError(msg)

        library_root = Path(library["root_path"])
        if not library_root.exists():
            msg = f"Library path does not exist: {library_root}"
            raise ValueError(msg)

        # Get watch mode from library config (default to 'off')
        watch_mode = library.get("watch_mode", "off")

        # If watch_mode is 'off', don't start anything
        if watch_mode == "off":
            logger.info(f"Watch mode is 'off' for library {library_id}, skipping watcher")
            return

        # Stop existing watcher if any
        if library_id in self.observers:
            logger.info(f"Stopping existing watcher for library {library_id}")
            self.stop_watching_library(library_id)

        # Branch on watch mode from library config
        if watch_mode == "event":
            self._start_event_watching(library_id, library_root)
        elif watch_mode == "poll":
            self._start_polling_library(library_id)
        else:
            # Should not reach here if validation is correct, but log just in case
            logger.warning(f"Unknown watch_mode '{watch_mode}' for library {library_id}, skipping")

    def _start_event_watching(self, library_id: str, library_root: Path) -> None:
        """Start event-based watching with watchdog Observer.

        Args:
            library_id: Library document _id
            library_root: Absolute path to library root

        """
        # Create handler
        handler = LibraryEventHandler(
            library_id=library_id,
            library_root=library_root,
            callback=self._on_file_change,
        )

        # Create and start observer
        observer = Observer()
        observer.schedule(handler, str(library_root), recursive=True)
        observer.start()

        self.observers[library_id] = observer
        logger.info(f"Started event-based watching for library {library_id} at {library_root}")

    def _start_polling_library(self, library_id: str) -> None:
        """Start polling-based watching with periodic full-library scans.

        Network-mount-safe alternative to event-based watching.
        Uses a background thread since this may be called from sync context.

        Args:
            library_id: Library document _id

        """
        # Initialize last poll time to now (so first poll happens after interval)
        self.last_poll_time[library_id] = internal_s()

        # Try to schedule on existing event loop, fall back to thread
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(self._polling_loop(library_id))
            self.observers[library_id] = task
        except RuntimeError:
            # No running event loop - use a background thread with its own loop
            def run_polling() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self._polling_loop(library_id))
                finally:
                    loop.close()

            thread = threading.Thread(target=run_polling, daemon=True, name=f"poll-{library_id}")
            thread.start()
            self.observers[library_id] = thread

        logger.info(
            f"Started polling-based watching for library {library_id} (interval={self.polling_interval_seconds}s)",
        )

    async def _polling_loop(self, library_id: str) -> None:
        """Periodic polling loop for one library.

        Runs until cancelled. Triggers full-library scan at fixed intervals.
        Validates library still exists and is watchable before each scan.

        Args:
            library_id: Library document _id

        """
        try:
            while True:
                await asyncio.sleep(self.polling_interval_seconds)

                # Validate library still exists and should be watched
                library = self.db.libraries.get_library(library_id)
                if not library:
                    logger.info(f"Library {library_id} no longer exists, stopping watcher")
                    self._schedule_cleanup(library_id)
                    return

                watch_mode = library.get("watch_mode", "off")
                if watch_mode == "off" or not library.get("is_enabled", True):
                    logger.info(f"Library {library_id} watch_mode is '{watch_mode}' or disabled, stopping watcher")
                    self._schedule_cleanup(library_id)
                    return

                # Update last poll time
                self.last_poll_time[library_id] = internal_s()

                logger.info(f"Polling library {library_id}: triggering quick scan")

                try:
                    self.library_service.start_scan_for_library(library_id, scan_type="quick")
                except ValueError as e:
                    error_msg = str(e)
                    # Library not found - stop watching it
                    if "Library not found" in error_msg:
                        logger.warning(f"Library {library_id} no longer exists, stopping watcher")
                        self._schedule_cleanup(library_id)
                        return
                    # Already scanning - skip this poll cycle, continue polling
                    if "already being scanned" in error_msg:
                        logger.debug(f"Library {library_id} is already being scanned, skipping this poll")
                        continue  # Don't exit the loop! Continue polling.
                    logger.error(f"Failed to trigger poll scan for library {library_id}: {e}", exc_info=True)
                except Exception as e:
                    logger.error(f"Failed to trigger poll scan for library {library_id}: {e}", exc_info=True)

        except asyncio.CancelledError:
            logger.info(f"Polling loop cancelled for library {library_id}")
            raise

    def stop_watching_library(self, library_id: str) -> None:
        """Stop watching a library.

        Handles event-based (Observer), polling task (asyncio.Task), and
        polling thread (threading.Thread) modes.

        Args:
            library_id: Library document _id

        """
        if library_id not in self.observers:
            logger.warning(f"No watcher found for library {library_id}")
            return

        watcher = self.observers[library_id]

        # Check watcher type and stop appropriately
        if isinstance(watcher, asyncio.Task):
            # Polling mode: cancel the task
            watcher.cancel()
            if library_id in self.last_poll_time:
                del self.last_poll_time[library_id]
        elif isinstance(watcher, threading.Thread):
            # Polling mode (thread): just remove reference, daemon thread will die
            if library_id in self.last_poll_time:
                del self.last_poll_time[library_id]
            # Note: daemon threads auto-terminate on main exit
        else:
            # Event mode: stop the observer
            watcher.stop()
            watcher.join(timeout=5.0)

        del self.observers[library_id]
        logger.info(f"Stopped watching library {library_id}")

    def stop_all(self) -> None:
        """Stop all watchers (for shutdown)."""
        logger.info("Stopping all file watchers")
        for library_id in list(self.observers.keys()):
            self.stop_watching_library(library_id)

    def switch_watch_mode(self, library_id: str, new_mode: str) -> None:
        """Switch watch mode for a library at runtime.

        Stops the existing watcher (if any), updates the library's watch_mode
        in the database, then starts the new mode (unless 'off').

        Idempotent - safe to call multiple times with the same mode.

        Args:
            library_id: Library document _id (e.g., "libraries/lib1")
            new_mode: New watch mode ('off', 'event', or 'poll')

        Raises:
            ValueError: If library not found or new_mode is invalid

        """
        # Validate mode
        if new_mode not in ("off", "event", "poll"):
            msg = f"Invalid watch_mode: {new_mode}. Must be 'off', 'event', or 'poll'"
            raise ValueError(msg)

        # Verify library exists
        library = self.db.libraries.get_library(library_id)
        if not library:
            msg = f"Library {library_id} not found"
            raise ValueError(msg)

        # Stop existing watcher if any
        if library_id in self.observers:
            logger.info(f"Stopping existing watcher for library {library_id} before mode switch")
            self.stop_watching_library(library_id)

        # Clear any pending changes for this library (debounce state)
        with self._lock:
            self.pending_changes = {(lib_id, path) for lib_id, path in self.pending_changes if lib_id != library_id}

        # Update watch_mode in database
        self.db.libraries.update_library(library_id, watch_mode=new_mode)
        logger.info(f"Updated library {library_id} watch_mode to '{new_mode}'")

        # Start new mode if not 'off'
        if new_mode != "off":
            self.start_watching_library(library_id)
        else:
            logger.info(f"Watch mode is 'off' for library {library_id}, no watcher started")

    def _on_file_change(self, library_id: str, relative_path: str) -> None:
        """Handle file change event from watchdog thread.

        CRITICAL: This runs on a watchdog background thread, NOT the event loop.
        Must use thread-safe handoff to schedule async work.

        Args:
            library_id: Library document _id
            relative_path: Path relative to library root

        """
        # Add to pending changes (thread-safe)
        with self._lock:
            self.pending_changes.add((library_id, relative_path))

            # Cancel existing debounce timer
            if self.debounce_task and not self.debounce_task.done():
                self.debounce_task.cancel()

        # Schedule new debounce timer (thread-safe handoff to event loop)
        self.event_loop.call_soon_threadsafe(self._schedule_debounce)

    def _schedule_debounce(self) -> None:
        """Schedule debounce coroutine in event loop.

        Called from event loop context (via call_soon_threadsafe).
        Safe to create asyncio tasks here.
        """
        self.debounce_task = asyncio.create_task(self._trigger_after_debounce())

    async def _trigger_after_debounce(self) -> None:
        """Wait for quiet period, then trigger scan for affected libraries."""
        await asyncio.sleep(self.debounce_seconds)

        # Collect pending changes (thread-safe)
        with self._lock:
            changes = self.pending_changes.copy()
            self.pending_changes.clear()

        if not changes:
            return

        # Group by library — we only need the library IDs
        affected_libraries: set[str] = set()
        for library_id, _relative_path in changes:
            affected_libraries.add(library_id)

        logger.info(
            f"Debounce fired: {len(changes)} file changes across "
            f"{len(affected_libraries)} library/libraries",
        )

        # Trigger a full scan for each affected library.
        # Folder-level caching in the scan workflow ensures only changed
        # folders are actually re-scanned.
        for library_id in affected_libraries:
            try:
                self.library_service.start_scan_for_library(library_id, scan_type="quick")
            except Exception as e:
                logger.error(f"Failed to trigger scan for library {library_id}: {e}", exc_info=True)

