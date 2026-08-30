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
- One Observer (event mode) or polling thread (poll mode) per library
- Events/scans are debounced (configurable quiet period)
- Only relevant file types are processed (audio, playlists, artwork)
- Triggers full library scans; folder-level caching in the scan workflow
  handles incremental optimization
- Calls LibraryService.start_quick_scan() / start_full_scan() - NO direct persistence access

CRITICAL (event mode): Watchdog callbacks run on background threads.
All state mutations use threading primitives (Lock, Event, Timer) for thread safety.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from nomarr.components.library import get_library_watch_config, list_watchable_libraries
from nomarr.components.library.update_library_metadata_comp import UpdateLibraryMetadataComp
from nomarr.helpers.exceptions import LibraryAlreadyScanningError, LibraryNotFoundError
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

        # Get path — watchdog types src_path as bytes | str
        src_path = event.src_path
        if isinstance(src_path, bytes):
            src_path = src_path.decode()
        path = Path(src_path)

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
    - Make domain decisions (when to scan, what to process)
    - Trigger ML/tagging pipelines (those are manual)

    Watch Modes:
    - 'event' (default): Real-time filesystem events via watchdog
    - 'poll': Periodic full-library scans (network-mount-safe)

    Thread Safety:
    - Event mode: Watchdog callbacks execute on background threads
    - Uses lock for pending_changes access
    - Uses threading.Event for polling loop cancellation
    - Uses threading.Timer for debounce delays
    """

    def __init__(
        self,
        db: Database,
        library_service: LibraryService,
        debounce_seconds: float = 2.0,
        polling_interval_seconds: float = 300.0,
    ) -> None:
        """Initialise the FileWatcherService.

        Args:
            db: PostgreSQL database handle.
            library_service: Domain service used to trigger scans.
            debounce_seconds: Quiet period before triggering a scan after file events.
            polling_interval_seconds: Interval between polls when using poll watch mode.

        """
        self._db = db
        self.library_service = library_service
        self.debounce_seconds = debounce_seconds
        self.polling_interval_seconds = polling_interval_seconds

        # Active watchers (event mode: Observer, poll mode: Thread)
        self.observers: dict[str, Any] = {}  # Observer | Thread

        # Debouncing state (thread-safe)
        self._lock = threading.Lock()
        self.pending_changes: set[tuple[str, str]] = set()  # (library_id, relative_path)
        self._debounce_timer: threading.Timer | None = None

        # Polling state
        self.last_poll_time: dict[str, InternalSeconds] = {}
        self._stop_events: dict[str, threading.Event] = {}  # per-library cancellation

        # Libraries scheduled for cleanup (when not found)
        self._pending_cleanups: set[str] = set()

        logger.debug(
            f"FileWatcherService initialized (debounce={debounce_seconds}s, poll_interval={polling_interval_seconds}s)",
        )

    def sync_watchers(self) -> None:
        """Sync watchers with the library collection (DB is source of truth).

        - Starts watchers for libraries in DB with watch_mode != 'off'
        - Stops watchers for libraries no longer in DB or with watch_mode == 'off'

        Should be called on startup and can be called periodically if needed.
        """
        # Get libraries that should be watched from DB
        watchable = list_watchable_libraries(self._db)
        watchable_ids = {lib["id"] for lib in watchable}

        # Stop watchers for libraries no longer watchable
        for library_id in list(self.observers.keys()):
            if library_id not in watchable_ids:
                logger.info(f"Library {library_id} no longer needs watching, stopping watcher")
                self.stop_watching_library(library_id)

        # Start watchers for new watchable libraries
        for lib in watchable:
            library_id = lib["id"]
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
        # Cleanup is synchronous, but stop_watching_library avoids joining the
        # polling thread when this method is called from that thread.
        self._do_cleanup(library_id)

    def _do_cleanup(self, library_id: str) -> None:
        """Actually stop watching a library."""
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
            library_id: Library database ID

        Raises:
            ValueError: If library not found or path invalid

        """
        # Get library info (resolve by natural name, mechanism A)
        library = self.library_service.get_library_by_name(library_id)
        if library is None:
            msg = f"Library {library_id} not found"
            raise ValueError(msg)

        library_config = get_library_watch_config(self._db, library)
        if not library_config:
            msg = f"Library {library_id} not found"
            raise ValueError(msg)

        library_root = Path(library_config["root_path"])
        if not library_root.exists():
            msg = f"Library path does not exist: {library_root}"
            raise ValueError(msg)

        # Get watch mode from library config (default to 'off')
        watch_mode = library_config.get("watch_mode", "off")

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
            library_id: Library database ID
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
        Uses a daemon thread for the polling loop.

        Args:
            library_id: Library database ID

        """
        # Initialize last poll time to now (so first poll happens after interval)
        self.last_poll_time[library_id] = internal_s()

        # Create per-library stop event for cancellation
        self._stop_events[library_id] = threading.Event()

        # Start polling in a daemon thread
        thread = threading.Thread(
            target=self._polling_loop,
            args=(library_id,),
            daemon=True,
            name=f"poll-{library_id}",
        )
        thread.start()
        self.observers[library_id] = thread

        logger.info(
            f"Started polling-based watching for library {library_id} (interval={self.polling_interval_seconds}s)",
        )

    def _polling_loop(self, library_id: str) -> None:
        """Periodic polling loop for one library.

        Runs until the stop event is set. Triggers full-library scan at fixed intervals.
        Validates library still exists and is watchable before each scan.

        Args:
            library_id: Library database ID

        """
        stop_event = self._stop_events.get(library_id)
        if stop_event is None:
            return

        while not stop_event.is_set():
            # Sleep in small increments so we can respond to cancellation quickly
            if stop_event.wait(timeout=self.polling_interval_seconds):
                # Stop event was set during sleep — exit cleanly
                break

            # Validate library still exists and should be watched
            library = self.library_service.get_library_by_name(library_id)
            if library is None:
                logger.info(f"Library {library_id} no longer exists, stopping watcher")
                self._schedule_cleanup(library_id)
                return

            library_config = get_library_watch_config(self._db, library)
            if not library_config:
                logger.info(f"Library {library_id} no longer exists, stopping watcher")
                self._schedule_cleanup(library_id)
                return

            watch_mode = library_config.get("watch_mode", "off")
            if watch_mode == "off" or not library_config.get("is_enabled", True):
                logger.info(f"Library {library_id} watch_mode is '{watch_mode}' or disabled, stopping watcher")
                self._schedule_cleanup(library_id)
                return

            # Update last poll time
            self.last_poll_time[library_id] = internal_s()

            logger.debug(f"Polling library {library_id}: triggering quick scan")

            try:
                self.library_service.start_quick_scan(library)
            except LibraryNotFoundError:
                logger.warning(f"Library {library_id} no longer exists, stopping watcher")
                self._schedule_cleanup(library_id)
                return
            except LibraryAlreadyScanningError:
                logger.debug(f"Library {library_id} is already being scanned, skipping this poll")
                # Benign startup race: watcher may poll before recover_stale_states() runs, so skipping is correct.
                continue  # Don't exit the loop! Continue polling.
            except Exception as e:
                logger.error(f"Failed to trigger poll scan for library {library_id}: {e}", exc_info=True)

        logger.info(f"Polling loop stopped for library {library_id}")

    def stop_watching_library(self, library_id: str) -> None:
        """Stop watching a library.

        Handles event-based (Observer) and polling thread (threading.Thread) modes.

        Args:
            library_id: Library database ID

        """
        if library_id not in self.observers:
            logger.warning(f"No watcher found for library {library_id}")
            return

        watcher = self.observers[library_id]

        # Check watcher type and stop appropriately
        if isinstance(watcher, threading.Thread):
            # Polling mode: signal the thread to stop via event
            stop_event = self._stop_events.pop(library_id, None)
            if stop_event is not None:
                stop_event.set()
            # A polling loop can discover that its library was deleted or
            # disabled and clean itself up.  Joining the current thread raises
            # RuntimeError and leaves the watcher state partially cleaned up.
            if watcher is not threading.current_thread():
                watcher.join(timeout=5.0)
            if library_id in self.last_poll_time:
                del self.last_poll_time[library_id]
        else:
            # Event mode: stop the observer
            watcher.stop()
            watcher.join(timeout=5.0)

        del self.observers[library_id]

        # Drop any pending debounced changes for this library so a queued
        # debounce timer cannot re-trigger a scan after the watcher is gone.
        with self._lock:
            self.pending_changes = {(lib_id, path) for lib_id, path in self.pending_changes if lib_id != library_id}

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
            library_id: Library database ID
            new_mode: New watch mode ('off', 'event', or 'poll')

        Raises:
            ValueError: If library not found or new_mode is invalid

        """
        # Validate mode
        if new_mode not in ("off", "event", "poll"):
            msg = f"Invalid watch_mode: {new_mode}. Must be 'off', 'event', or 'poll'"
            raise ValueError(msg)

        # Verify library exists (resolve by natural name, mechanism A)
        library = self.library_service.get_library_by_name(library_id)
        if library is None:
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
        UpdateLibraryMetadataComp(self._db).update(library, watch_mode=new_mode)
        logger.info(f"Updated library {library_id} watch_mode to '{new_mode}'")

        # Start new mode if not 'off'
        if new_mode != "off":
            self.start_watching_library(library_id)
        else:
            logger.info(f"Watch mode is 'off' for library {library_id}, no watcher started")

    def _on_file_change(self, library_id: str, relative_path: str) -> None:
        """Handle file change event from watchdog thread.

        CRITICAL: This runs on a watchdog background thread.
        Uses threading primitives for thread-safe debounce scheduling.

        Args:
            library_id: Library database ID
            relative_path: Path relative to library root

        """
        # Add to pending changes and manage debounce timer (thread-safe)
        with self._lock:
            self.pending_changes.add((library_id, relative_path))

            # Cancel existing debounce timer
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()

            # Schedule new debounce timer
            self._debounce_timer = threading.Timer(self.debounce_seconds, self._trigger_after_debounce)
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    def _trigger_after_debounce(self) -> None:
        """Wait for quiet period, then trigger scan for affected libraries.

        Called by threading.Timer after the debounce interval elapses.
        """
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
            f"Debounce fired: {len(changes)} file changes across {len(affected_libraries)} library/libraries",
        )

        # Trigger a full scan for each affected library.
        # Folder-level caching in the scan workflow ensures only changed
        # folders are actually re-scanned.
        for library_id in affected_libraries:
            try:
                library = self.library_service.get_library_by_name(library_id)
                if library is None:
                    logger.error(f"Library {library_id} not found during debounce scan")
                    continue
                self.library_service.start_quick_scan(library)
            except Exception as e:
                logger.error(f"Failed to trigger scan for library {library_id}: {e}", exc_info=True)
