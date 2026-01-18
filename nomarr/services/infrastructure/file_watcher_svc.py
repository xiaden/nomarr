"""File system watcher service for automatic library scanning.

This service monitors library directories for changes and triggers
targeted scans via LibraryService. It implements debouncing to batch
rapid changes and avoid excessive scanning.

Architecture:
- One Observer per library
- Events are debounced (configurable quiet period)
- Only relevant file types are processed (audio, playlists, artwork)
- Maps changed paths to parent-folder ScanTargets
- Calls LibraryService.scan_targets() - NO direct persistence access

CRITICAL: Watchdog callbacks run on background threads, NOT the asyncio event loop.
Must use thread-safe handoff via loop.call_soon_threadsafe().
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from nomarr.helpers.dto.library_dto import ScanTarget

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.domain.library_svc import LibraryService

logger = logging.getLogger(__name__)


class LibraryEventHandler(FileSystemEventHandler):
    """Handles file system events for a single library."""

    # File extensions we care about
    AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wav", ".wma", ".aac"}
    PLAYLIST_EXTENSIONS = {".m3u", ".m3u8", ".pls"}
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

    def __init__(
        self,
        library_id: str,
        library_root: Path,
        callback: Callable[[str, str], None],
    ):
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
        if name.endswith(".tmp") or name.endswith("~"):
            return True

        # OS-specific
        if name in {".DS_Store", "Thumbs.db", "desktop.ini"}:
            return True

        return False


class FileWatcherService:
    """Manages file system watchers for all libraries.

    This service is responsible for:
    1. Starting/stopping watchers per library
    2. Debouncing events (configurable quiet period)
    3. Mapping changed paths to ScanTargets
    4. Delegating to LibraryService for actual scanning

    It does NOT:
    - Access persistence directly (violates architecture)
    - Make domain decisions (when to scan, what to process)
    - Trigger ML/tagging pipelines (those are manual)

    Thread Safety:
    - Watchdog callbacks execute on background threads
    - Uses lock for pending_changes access
    - Uses loop.call_soon_threadsafe() to schedule async work
    """

    def __init__(
        self,
        db: Database,
        library_service: LibraryService,
        debounce_seconds: float = 2.0,
        event_loop: asyncio.AbstractEventLoop | None = None,
    ):
        self.db = db
        self.library_service = library_service
        self.debounce_seconds = debounce_seconds
        self.event_loop = event_loop or asyncio.get_event_loop()

        # Active watchers
        self.observers: dict[str, Observer] = {}  # type: ignore[valid-type]

        # Debouncing state (thread-safe)
        self._lock = threading.Lock()
        self.pending_changes: set[tuple[str, str]] = set()  # (library_id, relative_path)
        self.debounce_task: asyncio.Task | None = None

        logger.info(f"FileWatcherService initialized (debounce={debounce_seconds}s)")

    def start_watching_library(self, library_id: str) -> None:
        """Start watching a library for changes.

        If already watching, restarts the watcher.

        Args:
            library_id: Library document _id (e.g., "libraries/lib1")

        Raises:
            ValueError: If library not found or path invalid
        """
        # Get library info
        library = self.db.libraries.get_library(library_id)
        if not library:
            raise ValueError(f"Library {library_id} not found")

        library_root = Path(library["root_path"])
        if not library_root.exists():
            raise ValueError(f"Library path does not exist: {library_root}")

        # Stop existing watcher if any
        if library_id in self.observers:
            logger.info(f"Stopping existing watcher for library {library_id}")
            self.stop_watching_library(library_id)

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
        logger.info(f"Started watching library {library_id} at {library_root}")

    def stop_watching_library(self, library_id: str) -> None:
        """Stop watching a library.

        Args:
            library_id: Library document _id
        """
        if library_id not in self.observers:
            logger.warning(f"No watcher found for library {library_id}")
            return

        observer = self.observers[library_id]
        observer.stop()  # type: ignore[attr-defined]
        observer.join(timeout=5.0)  # type: ignore[attr-defined]

        del self.observers[library_id]
        logger.info(f"Stopped watching library {library_id}")

    def stop_all(self) -> None:
        """Stop all watchers (for shutdown)."""
        logger.info("Stopping all file watchers")
        for library_id in list(self.observers.keys()):
            self.stop_watching_library(library_id)

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
        """Wait for quiet period, then trigger scan."""
        await asyncio.sleep(self.debounce_seconds)

        # Collect pending changes (thread-safe)
        with self._lock:
            changes = self.pending_changes.copy()
            self.pending_changes.clear()

        if not changes:
            return

        logger.info(f"Debounce fired: {len(changes)} file changes detected")

        # Group by library
        by_library: dict[str, set[str]] = defaultdict(set)
        for library_id, relative_path in changes:
            by_library[library_id].add(relative_path)

        # Map to ScanTargets (parent folder per changed file)
        for library_id, paths in by_library.items():
            targets = self._paths_to_scan_targets(library_id, paths)
            logger.info(f"Triggering scan for library {library_id}: {len(targets)} target(s)")

            # Delegate to LibraryService - NO direct persistence calls
            try:
                self.library_service.scan_targets(
                    targets=list(targets),
                    batch_size=200,  # Use default batch size
                )
            except Exception as e:
                logger.error(f"Failed to trigger scan for library {library_id}: {e}", exc_info=True)

    def _paths_to_scan_targets(
        self,
        library_id: str,
        paths: set[str],
    ) -> list[ScanTarget]:
        """Convert changed file paths to ScanTargets (parent folders).

        Deduplicates targets - multiple files in same folder = one target.

        Args:
            library_id: Library document _id
            paths: Set of relative paths that changed

        Returns:
            List of deduplicated ScanTargets
        """
        folders = set()

        for path_str in paths:
            path = Path(path_str)
            # Get parent folder
            folder = str(path.parent) if path.parent != Path(".") else ""
            folders.add(folder)

        # Convert to ScanTargets
        targets = [ScanTarget(library_id=library_id, folder_path=folder) for folder in sorted(folders)]

        # Deduplicate: if we're scanning parent, don't scan children
        # Example: ["Rock", "Rock/Beatles"] -> ["Rock"]
        targets = self._deduplicate_targets(targets)

        return targets

    def _deduplicate_targets(self, targets: list[ScanTarget]) -> list[ScanTarget]:
        """Remove redundant targets (child folders when parent is being scanned).

        Args:
            targets: List of ScanTargets (may contain redundant children)

        Returns:
            Deduplicated list (no child if parent present)
        """
        if len(targets) <= 1:
            return targets

        # Sort by folder depth (shallowest first)
        sorted_targets = sorted(targets, key=lambda t: t.folder_path.count("/"))

        deduplicated: list[ScanTarget] = []
        for target in sorted_targets:
            # Check if any existing target is a parent
            is_redundant = False
            for existing in deduplicated:
                # Empty folder_path means entire library (parent of everything)
                if existing.folder_path == "":
                    is_redundant = True
                    break
                # Check if target is child of existing
                if target.folder_path.startswith(existing.folder_path + "/"):
                    is_redundant = True
                    break
            if not is_redundant:
                deduplicated.append(target)

        return deduplicated
