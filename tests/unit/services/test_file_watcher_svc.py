"""
Unit tests for FileWatcherService (Phase 4).

Tests verify:
- File event filtering (audio files only, ignore temp/hidden)
- Debouncing behavior (batches rapid changes)
- Path-to-ScanTarget mapping
- Target deduplication (parent folders subsume children)
- Thread-safe event handling
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dto.library_dto import ScanTarget
from nomarr.services.infrastructure.file_watcher_svc import (
    FileWatcherService,
    LibraryEventHandler,
)


@pytest.fixture
def temp_library(tmp_path):
    """Create temporary library directory with structure."""
    library_root = tmp_path / "music"
    library_root.mkdir()

    # Create folder structure
    (library_root / "Rock").mkdir()
    (library_root / "Rock" / "Beatles").mkdir()
    (library_root / "Jazz").mkdir()

    return library_root


@pytest.fixture
def mock_db(temp_library):
    """Mock Database with one library."""

    class MockDB:
        class LibrariesOps:
            def __init__(self, library_root):
                self.library_root = library_root

            def get_library(self, library_id):
                return {
                    "_id": library_id,
                    "_key": library_id.split("/")[-1],
                    "name": "Test Library",
                    "root_path": str(self.library_root),
                    "is_enabled": True,
                    "is_default": True,
                }

        def __init__(self):
            self.libraries = self.LibrariesOps(temp_library)

    return MockDB()


@pytest.fixture
def mock_library_service():
    """Mock LibraryService that records scan calls."""

    class MockLibraryService:
        def __init__(self):
            self.scan_calls = []

        def scan_targets(self, targets, batch_size=200):
            self.scan_calls.append({"targets": targets, "batch_size": batch_size})
            return {"status": "ok"}

    return MockLibraryService()


class TestLibraryEventHandler:
    """Test file event filtering."""

    def test_filters_audio_files(self, temp_library):
        """Handler should accept audio files."""
        received_events = []

        def callback(library_id, relative_path):
            received_events.append((library_id, relative_path))

        handler = LibraryEventHandler(
            library_id="libraries/lib1",
            library_root=temp_library,
            callback=callback,
        )

        # Create audio file
        audio_file = temp_library / "Rock" / "song.mp3"
        audio_file.touch()

        # Simulate file event
        from watchdog.events import FileModifiedEvent

        event = FileModifiedEvent(str(audio_file))
        handler.on_any_event(event)

        # Should receive event (normalize path for cross-platform)
        assert len(received_events) == 1
        assert received_events[0][0] == "libraries/lib1"
        # Path may use OS separators, normalize to forward slashes for comparison
        received_path = received_events[0][1].replace("\\", "/")
        assert received_path == "Rock/song.mp3"

    def test_ignores_non_audio_files(self, temp_library):
        """Handler should ignore non-audio files."""
        received_events = []

        def callback(library_id, relative_path):
            received_events.append((library_id, relative_path))

        handler = LibraryEventHandler(
            library_id="libraries/lib1",
            library_root=temp_library,
            callback=callback,
        )

        # Create non-audio file
        text_file = temp_library / "Rock" / "notes.txt"
        text_file.touch()

        # Simulate file event
        from watchdog.events import FileModifiedEvent

        event = FileModifiedEvent(str(text_file))
        handler.on_any_event(event)

        # Should NOT receive event
        assert len(received_events) == 0

    def test_ignores_temp_files(self, temp_library):
        """Handler should ignore temporary files."""
        received_events = []

        def callback(library_id, relative_path):
            received_events.append((library_id, relative_path))

        handler = LibraryEventHandler(
            library_id="libraries/lib1",
            library_root=temp_library,
            callback=callback,
        )

        # Create temp file (audio extension but temp naming)
        temp_file = temp_library / "Rock" / ".song.mp3"
        temp_file.touch()

        # Simulate file event
        from watchdog.events import FileModifiedEvent

        event = FileModifiedEvent(str(temp_file))
        handler.on_any_event(event)

        # Should NOT receive event
        assert len(received_events) == 0

    def test_ignores_directory_events(self, temp_library):
        """Handler should ignore directory events."""
        received_events = []

        def callback(library_id, relative_path):
            received_events.append((library_id, relative_path))

        handler = LibraryEventHandler(
            library_id="libraries/lib1",
            library_root=temp_library,
            callback=callback,
        )

        # Simulate directory event
        from watchdog.events import DirModifiedEvent

        event = DirModifiedEvent(str(temp_library / "Rock"))
        handler.on_any_event(event)

        # Should NOT receive event
        assert len(received_events) == 0


class TestFileWatcherService:
    """Test file watcher service behavior."""

    @pytest.mark.asyncio
    async def test_debouncing_batches_changes(self, mock_db, mock_library_service, temp_library):
        """Debouncing should batch rapid changes."""
        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
            debounce_seconds=0.1,  # Short debounce for testing
        )

        # Simulate multiple file changes
        watcher._on_file_change("libraries/lib1", "Rock/song1.mp3")
        watcher._on_file_change("libraries/lib1", "Rock/song2.mp3")
        watcher._on_file_change("libraries/lib1", "Jazz/track.flac")

        # Wait for debounce
        await asyncio.sleep(0.2)

        # Should have triggered one scan with all changes
        assert len(mock_library_service.scan_calls) == 1
        call = mock_library_service.scan_calls[0]

        # Should have 2 targets (Rock/ and Jazz/)
        targets = call["targets"]
        assert len(targets) == 2

        target_folders = {t.folder_path for t in targets}
        assert "Rock" in target_folders
        assert "Jazz" in target_folders

    @pytest.mark.asyncio
    async def test_maps_files_to_parent_folders(self, mock_db, mock_library_service, temp_library):
        """Changed files should map to their parent folders."""
        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
            debounce_seconds=0.1,
        )

        # Simulate changes in deep folder
        watcher._on_file_change("libraries/lib1", "Rock/Beatles/Help.mp3")
        watcher._on_file_change("libraries/lib1", "Rock/Beatles/Yesterday.mp3")

        # Wait for debounce
        await asyncio.sleep(0.2)

        # Should have one target: Rock/Beatles
        assert len(mock_library_service.scan_calls) == 1
        targets = mock_library_service.scan_calls[0]["targets"]
        assert len(targets) == 1
        assert targets[0].folder_path == "Rock/Beatles"

    def test_deduplicates_parent_child_targets(self, mock_db, mock_library_service):
        """Should remove child targets when parent is being scanned."""
        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
            debounce_seconds=0.1,
        )

        targets = [
            ScanTarget(library_id="lib1", folder_path="Rock"),
            ScanTarget(library_id="lib1", folder_path="Rock/Beatles"),
            ScanTarget(library_id="lib1", folder_path="Rock/Beatles/Early"),
            ScanTarget(library_id="lib1", folder_path="Jazz"),
        ]

        deduplicated = watcher._deduplicate_targets(targets)

        # Should only have Rock and Jazz (Beatles and Early are subsumed by Rock)
        assert len(deduplicated) == 2
        folders = {t.folder_path for t in deduplicated}
        assert folders == {"Rock", "Jazz"}

    def test_empty_folder_path_subsumes_all(self, mock_db, mock_library_service):
        """Empty folder_path (full library scan) should subsume all other targets."""
        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
            debounce_seconds=0.1,
        )

        targets = [
            ScanTarget(library_id="lib1", folder_path=""),  # Full library
            ScanTarget(library_id="lib1", folder_path="Rock"),
            ScanTarget(library_id="lib1", folder_path="Jazz"),
        ]

        deduplicated = watcher._deduplicate_targets(targets)

        # Should only have empty folder_path
        assert len(deduplicated) == 1
        assert deduplicated[0].folder_path == ""


class TestThreadSafety:
    """Test thread-safe event handling."""

    @pytest.mark.asyncio
    async def test_handles_concurrent_events(self, mock_db, mock_library_service):
        """Should handle events from multiple threads safely."""
        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
            debounce_seconds=0.1,
        )

        # Simulate events from multiple "threads" (synchronously for testing)
        for i in range(10):
            watcher._on_file_change("libraries/lib1", f"Rock/song{i}.mp3")

        # Wait for debounce
        await asyncio.sleep(0.2)

        # Should have batched all events
        assert len(mock_library_service.scan_calls) == 1

        # Should have one target (all in same folder)
        targets = mock_library_service.scan_calls[0]["targets"]
        assert len(targets) == 1
        assert targets[0].folder_path == "Rock"


class TestWatcherLifecycle:
    """Test watcher start/stop lifecycle."""

    def test_start_watching_library(self, mock_db, mock_library_service, temp_library):
        """Should start watching a library."""
        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
            debounce_seconds=0.1,
        )

        watcher.start_watching_library("libraries/lib1")

        # Should have one observer
        assert len(watcher.observers) == 1
        assert "libraries/lib1" in watcher.observers

        # Cleanup
        watcher.stop_all()

    def test_stop_watching_library(self, mock_db, mock_library_service, temp_library):
        """Should stop watching a library."""
        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
            debounce_seconds=0.1,
        )

        watcher.start_watching_library("libraries/lib1")
        watcher.stop_watching_library("libraries/lib1")

        # Should have no observers
        assert len(watcher.observers) == 0

    def test_stop_all_watchers(self, mock_db, mock_library_service, temp_library):
        """Should stop all watchers."""
        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
            debounce_seconds=0.1,
        )

        # Start multiple watchers (same library for testing)
        watcher.start_watching_library("libraries/lib1")

        watcher.stop_all()

        # Should have no observers
        assert len(watcher.observers) == 0

    def test_raises_on_invalid_library(self, mock_library_service):
        """Should raise if library not found."""
        mock_db_invalid = MagicMock()
        mock_db_invalid.libraries.get_library.return_value = None

        watcher = FileWatcherService(
            db=mock_db_invalid,
            library_service=mock_library_service,
            debounce_seconds=0.1,
        )

        with pytest.raises(ValueError, match="not found"):
            watcher.start_watching_library("libraries/invalid")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
