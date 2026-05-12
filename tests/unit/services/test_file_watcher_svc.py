"""Unit tests for FileWatcherService.

Tests verify:
- File event filtering (audio files only, ignore temp/hidden)
- Thread-safe event handling
- Watch lifecycle (start/stop)
- Per-library watch modes (event/poll/off)
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.exceptions import LibraryAlreadyScanningError, LibraryNotFoundError
from nomarr.services.infrastructure.file_watcher_svc import (
    FileWatcherService,
    LibraryEventHandler,
)


def _mock_get_library_watch_config(mock_db, library_id: str):
    """Return watch config from the fixture-backed mock database."""
    return mock_db.library.get_library(library_id)


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
                self.libraries = {}  # Store library documents

            def get_library(self, library_id):
                # Return stored library if exists, else default
                if library_id in self.libraries:
                    return self.libraries[library_id]

                # Default library (for backward compat with existing tests)
                return {
                    "_id": library_id,
                    "_key": library_id.split("/")[-1],
                    "name": "Test Library",
                    "root_path": str(self.library_root),
                    "is_enabled": True,
                    "watch_mode": "off",  # Default to 'off'
                }

            def update_library(self, library_id, **kwargs):
                """Update library document (mock implementation)."""
                if library_id not in self.libraries:
                    # Initialize if doesn't exist
                    self.libraries[library_id] = self.get_library(library_id)

                # Apply updates
                for key, value in kwargs.items():
                    self.libraries[library_id][key] = value

        def __init__(self):
            self.library = self.LibrariesOps(temp_library)

    return MockDB()


@pytest.fixture
def mock_library_service():
    """Mock LibraryService that records scan calls."""

    class MockLibraryService:
        def __init__(self):
            self.scan_calls = []

        def start_quick_scan(self, library_id: str) -> dict[str, str]:
            self.scan_calls.append({"library_id": library_id, "scan_type": "quick"})
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

        # Should have batched all events into a single scan call
        assert len(mock_library_service.scan_calls) == 1
        assert mock_library_service.scan_calls[0]["library_id"] == "libraries/lib1"
        assert mock_library_service.scan_calls[0]["scan_type"] == "quick"


class TestWatcherLifecycle:
    """Test watcher start/stop lifecycle."""

    def test_start_watching_library(self, mock_db, mock_library_service, temp_library):
        """Should start watching a library (when watch_mode is enabled)."""
        # Set watch_mode to 'event' so watcher actually starts
        mock_db.library.update_library("libraries/lib1", watch_mode="event")

        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
            debounce_seconds=0.1,
        )

        with patch(
            "nomarr.services.infrastructure.file_watcher_svc.get_library_watch_config",
            side_effect=lambda _db, library_id: _mock_get_library_watch_config(mock_db, library_id),
        ):
            watcher.start_watching_library("libraries/lib1")

        # Should have one observer
        assert len(watcher.observers) == 1
        assert "libraries/lib1" in watcher.observers

        # Cleanup
        watcher.stop_all()

    def test_stop_watching_library(self, mock_db, mock_library_service, temp_library):
        """Should stop watching a library."""
        # Set watch_mode to 'event' so watcher starts
        mock_db.library.update_library("libraries/lib1", watch_mode="event")

        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
            debounce_seconds=0.1,
        )

        with patch(
            "nomarr.services.infrastructure.file_watcher_svc.get_library_watch_config",
            side_effect=lambda _db, library_id: _mock_get_library_watch_config(mock_db, library_id),
        ):
            watcher.start_watching_library("libraries/lib1")
        watcher.stop_watching_library("libraries/lib1")

        # Should have no observers
        assert len(watcher.observers) == 0

    def test_stop_all_watchers(self, mock_db, mock_library_service, temp_library):
        """Should stop all watchers."""
        # Set watch_mode to 'event' so watcher starts
        mock_db.library.update_library("libraries/lib1", watch_mode="event")

        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
            debounce_seconds=0.1,
        )

        # Start multiple watchers (same library for testing)
        with patch(
            "nomarr.services.infrastructure.file_watcher_svc.get_library_watch_config",
            side_effect=lambda _db, library_id: _mock_get_library_watch_config(mock_db, library_id),
        ):
            watcher.start_watching_library("libraries/lib1")

        watcher.stop_all()

        # Should have no observers
        assert len(watcher.observers) == 0

    def test_raises_on_invalid_library(self, mock_library_service):
        """Should raise if library not found."""
        mock_db_invalid = MagicMock()

        watcher = FileWatcherService(
            db=mock_db_invalid,
            library_service=mock_library_service,
            debounce_seconds=0.1,
        )

        with (
            patch(
                "nomarr.services.infrastructure.file_watcher_svc.get_library_watch_config",
                return_value=None,
            ),
            pytest.raises(ValueError, match="not found"),
        ):
            watcher.start_watching_library("libraries/invalid")


class TestPerLibraryWatchMode:
    """Test per-library watch mode configuration (off, event, poll)."""

    @pytest.mark.asyncio
    async def test_default_watch_mode_off_no_watcher_started(self, mock_db, mock_library_service):
        """Libraries without watch_mode field should default to 'off' and not start watcher."""
        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
        )

        # Try to start watching - should return early due to watch_mode='off'
        with patch(
            "nomarr.services.infrastructure.file_watcher_svc.get_library_watch_config",
            side_effect=lambda _db, library_id: _mock_get_library_watch_config(mock_db, library_id),
        ):
            watcher.start_watching_library("libraries/lib1")

        # No observer/task should be created
        assert "libraries/lib1" not in watcher.observers

    @pytest.mark.asyncio
    async def test_watch_mode_off_no_watcher_started(self, mock_db, mock_library_service):
        """Libraries with watch_mode='off' should not start watcher."""
        # Set library watch_mode to 'off'
        mock_db.library.update_library("libraries/lib1", watch_mode="off")

        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
        )

        with patch(
            "nomarr.services.infrastructure.file_watcher_svc.get_library_watch_config",
            side_effect=lambda _db, library_id: _mock_get_library_watch_config(mock_db, library_id),
        ):
            watcher.start_watching_library("libraries/lib1")

        # No observer/task should be created
        assert "libraries/lib1" not in watcher.observers

    @pytest.mark.asyncio
    async def test_watch_mode_event_starts_observer(self, mock_db, mock_library_service, temp_library):
        """Libraries with watch_mode='event' should start watchdog Observer."""
        # Set library watch_mode to 'event'
        mock_db.library.update_library("libraries/lib1", watch_mode="event")

        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
        )

        with patch(
            "nomarr.services.infrastructure.file_watcher_svc.get_library_watch_config",
            side_effect=lambda _db, library_id: _mock_get_library_watch_config(mock_db, library_id),
        ):
            watcher.start_watching_library("libraries/lib1")

        # Observer should be created (not an asyncio.Task)
        assert "libraries/lib1" in watcher.observers
        assert not isinstance(watcher.observers["libraries/lib1"], asyncio.Task)

        # Cleanup
        watcher.stop_watching_library("libraries/lib1")

    @pytest.mark.asyncio
    async def test_watch_mode_poll_starts_task(self, mock_db, mock_library_service):
        """Libraries with watch_mode='poll' should start polling task."""
        # Set library watch_mode to 'poll'
        mock_db.library.update_library("libraries/lib1", watch_mode="poll")

        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
            polling_interval_seconds=0.1,  # Short interval for testing
        )

        with patch(
            "nomarr.services.infrastructure.file_watcher_svc.get_library_watch_config",
            side_effect=lambda _db, library_id: _mock_get_library_watch_config(mock_db, library_id),
        ):
            watcher.start_watching_library("libraries/lib1")

        # Polling task should be created
        assert "libraries/lib1" in watcher.observers
        assert isinstance(watcher.observers["libraries/lib1"], asyncio.Task)

        # Cleanup
        watcher.stop_watching_library("libraries/lib1")

    @pytest.mark.asyncio
    async def test_switch_watch_mode_off_to_event(self, mock_db, mock_library_service, temp_library):
        """switch_watch_mode should transition from 'off' to 'event'."""
        # Start with watch_mode='off'
        mock_db.library.update_library("libraries/lib1", watch_mode="off")

        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
        )

        # Verify no watcher initially
        with (
            patch(
                "nomarr.services.infrastructure.file_watcher_svc.get_library_watch_config",
                side_effect=lambda _db, library_id: _mock_get_library_watch_config(mock_db, library_id),
            ),
            patch(
                "nomarr.services.infrastructure.file_watcher_svc.UpdateLibraryMetadataComp",
            ) as update_library_metadata_comp,
        ):
            update_library_metadata_comp.return_value.update.side_effect = mock_db.library.update_library
            watcher.start_watching_library("libraries/lib1")
            assert "libraries/lib1" not in watcher.observers

            # Switch to 'event'
            watcher.switch_watch_mode("libraries/lib1", "event")

        # Observer should be created
        assert "libraries/lib1" in watcher.observers
        assert not isinstance(watcher.observers["libraries/lib1"], asyncio.Task)

        # Verify database was updated
        library = mock_db.library.get_library("libraries/lib1")
        assert library["watch_mode"] == "event"

        # Cleanup
        watcher.stop_watching_library("libraries/lib1")

    @pytest.mark.asyncio
    async def test_switch_watch_mode_event_to_poll(self, mock_db, mock_library_service, temp_library):
        """switch_watch_mode should transition from 'event' to 'poll'."""
        # Start with watch_mode='event'
        mock_db.library.update_library("libraries/lib1", watch_mode="event")

        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
            polling_interval_seconds=0.1,
        )

        with (
            patch(
                "nomarr.services.infrastructure.file_watcher_svc.get_library_watch_config",
                side_effect=lambda _db, library_id: _mock_get_library_watch_config(mock_db, library_id),
            ),
            patch(
                "nomarr.services.infrastructure.file_watcher_svc.UpdateLibraryMetadataComp",
            ) as update_library_metadata_comp,
        ):
            update_library_metadata_comp.return_value.update.side_effect = mock_db.library.update_library
            watcher.start_watching_library("libraries/lib1")

            # Verify observer exists
            assert "libraries/lib1" in watcher.observers
            assert not isinstance(watcher.observers["libraries/lib1"], asyncio.Task)

            # Switch to 'poll'
            watcher.switch_watch_mode("libraries/lib1", "poll")

        # Should now be a polling task
        assert "libraries/lib1" in watcher.observers
        assert isinstance(watcher.observers["libraries/lib1"], asyncio.Task)

        # Verify database was updated
        library = mock_db.library.get_library("libraries/lib1")
        assert library["watch_mode"] == "poll"

        # Cleanup
        watcher.stop_watching_library("libraries/lib1")

    @pytest.mark.asyncio
    async def test_switch_watch_mode_poll_to_off(self, mock_db, mock_library_service):
        """switch_watch_mode should transition from 'poll' to 'off'."""
        # Start with watch_mode='poll'
        mock_db.library.update_library("libraries/lib1", watch_mode="poll")

        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
            polling_interval_seconds=0.1,
        )

        with (
            patch(
                "nomarr.services.infrastructure.file_watcher_svc.get_library_watch_config",
                side_effect=lambda _db, library_id: _mock_get_library_watch_config(mock_db, library_id),
            ),
            patch(
                "nomarr.services.infrastructure.file_watcher_svc.UpdateLibraryMetadataComp",
            ) as update_library_metadata_comp,
        ):
            update_library_metadata_comp.return_value.update.side_effect = mock_db.library.update_library
            watcher.start_watching_library("libraries/lib1")

            # Verify polling task exists
            assert "libraries/lib1" in watcher.observers
            assert isinstance(watcher.observers["libraries/lib1"], asyncio.Task)

            # Switch to 'off'
            watcher.switch_watch_mode("libraries/lib1", "off")

        # Should no longer have watcher
        assert "libraries/lib1" not in watcher.observers

        # Verify database was updated
        library = mock_db.library.get_library("libraries/lib1")
        assert library["watch_mode"] == "off"

    @pytest.mark.asyncio
    async def test_switch_watch_mode_idempotent(self, mock_db, mock_library_service, temp_library):
        """Switching to same mode multiple times should be idempotent."""
        mock_db.library.update_library("libraries/lib1", watch_mode="event")

        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
        )

        # Switch to 'event' multiple times
        with (
            patch(
                "nomarr.services.infrastructure.file_watcher_svc.get_library_watch_config",
                side_effect=lambda _db, library_id: _mock_get_library_watch_config(mock_db, library_id),
            ),
            patch(
                "nomarr.services.infrastructure.file_watcher_svc.UpdateLibraryMetadataComp",
            ) as update_library_metadata_comp,
        ):
            update_library_metadata_comp.return_value.update.side_effect = mock_db.library.update_library
            watcher.switch_watch_mode("libraries/lib1", "event")
            watcher.switch_watch_mode("libraries/lib1", "event")
            watcher.switch_watch_mode("libraries/lib1", "event")

        # Should only have one observer
        assert "libraries/lib1" in watcher.observers
        assert not isinstance(watcher.observers["libraries/lib1"], asyncio.Task)

        # Cleanup
        watcher.stop_watching_library("libraries/lib1")

    @pytest.mark.asyncio
    async def test_switch_watch_mode_invalid_mode_raises(self, mock_db, mock_library_service):
        """switch_watch_mode should raise ValueError for invalid modes."""
        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
        )

        with pytest.raises(ValueError, match="Invalid watch_mode"):
            watcher.switch_watch_mode("libraries/lib1", "invalid")

        with pytest.raises(ValueError, match="Invalid watch_mode"):
            watcher.switch_watch_mode("libraries/lib1", "")

    @pytest.mark.asyncio
    async def test_polling_triggers_periodic_scans(self, mock_db, mock_library_service):
        """Polling mode should trigger full-library scans at intervals."""
        # Set library watch_mode to 'poll'
        mock_db.library.update_library("libraries/lib1", watch_mode="poll")

        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
            polling_interval_seconds=0.1,  # Short interval for testing
        )

        # Start watching
        with patch(
            "nomarr.services.infrastructure.file_watcher_svc.get_library_watch_config",
            side_effect=lambda _db, library_id: _mock_get_library_watch_config(mock_db, library_id),
        ):
            watcher.start_watching_library("libraries/lib1")

            # Verify polling task was created
            assert "libraries/lib1" in watcher.observers
            assert isinstance(watcher.observers["libraries/lib1"], asyncio.Task)

            # Wait for 2-3 poll cycles
            await asyncio.sleep(0.35)

        # Stop watching (cancels task)
        watcher.stop_watching_library("libraries/lib1")

        # Should have triggered 2-3 scans
        assert len(mock_library_service.scan_calls) >= 2
        assert len(mock_library_service.scan_calls) <= 3

        # Each call should be a quick scan for the correct library
        for call in mock_library_service.scan_calls:
            assert call["library_id"] == "libraries/lib1"
            assert call["scan_type"] == "quick"

    @pytest.mark.asyncio
    async def test_polling_stop_cancels_task(self, mock_db, mock_library_service):
        """Stopping polling mode should cancel the polling task."""
        mock_db.library.update_library("libraries/lib1", watch_mode="poll")

        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
            polling_interval_seconds=1.0,
        )

        with patch(
            "nomarr.services.infrastructure.file_watcher_svc.get_library_watch_config",
            side_effect=lambda _db, library_id: _mock_get_library_watch_config(mock_db, library_id),
        ):
            watcher.start_watching_library("libraries/lib1")

            # Get task
            task = watcher.observers["libraries/lib1"]
            assert isinstance(task, asyncio.Task)
            assert not task.done()  # type: ignore[union-attr]

        # Stop watching
        watcher.stop_watching_library("libraries/lib1")

        # Give task a moment to finish cancellation
        await asyncio.sleep(0.01)

        # Task should be cancelled or done
        assert task.cancelled() or task.done()  # type: ignore[union-attr]

        # Should no longer be in observers
        assert "libraries/lib1" not in watcher.observers

    @pytest.mark.asyncio
    async def test_polling_handles_scan_errors(self, mock_db, monkeypatch):
        """Polling should continue even if scan fails."""
        mock_db.library.update_library("libraries/lib1", watch_mode="poll")

        class FailingLibraryService:
            def __init__(self):
                self.scan_call_count = 0

            def start_quick_scan(self, library_id: str) -> None:
                self.scan_call_count += 1
                raise RuntimeError("Scan failed")

        failing_service = FailingLibraryService()

        watcher = FileWatcherService(
            db=mock_db,
            library_service=failing_service,  # type: ignore[arg-type]
            polling_interval_seconds=0.1,
        )

        with patch(
            "nomarr.services.infrastructure.file_watcher_svc.get_library_watch_config",
            side_effect=lambda _db, library_id: _mock_get_library_watch_config(mock_db, library_id),
        ):
            watcher.start_watching_library("libraries/lib1")

            # Wait for 2-3 poll cycles
            await asyncio.sleep(0.35)

        # Stop watching
        watcher.stop_watching_library("libraries/lib1")

        # Should have attempted multiple scans despite errors
        assert failing_service.scan_call_count >= 2

    @pytest.mark.asyncio
    async def test_stop_all_handles_mixed_modes(self, mock_db, mock_library_service, temp_library):
        """stop_all() should handle both event and polling modes gracefully."""
        # Create library with event mode
        mock_db.library.update_library("libraries/lib1", watch_mode="event")

        # Create library with poll mode
        mock_db.library.libraries["libraries/lib2"] = {
            "_id": "libraries/lib2",
            "_key": "lib2",
            "name": "Test Library 2",
            "root_path": str(temp_library),
            "is_enabled": True,
            "watch_mode": "poll",
        }

        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
            polling_interval_seconds=1.0,
        )

        with patch(
            "nomarr.services.infrastructure.file_watcher_svc.get_library_watch_config",
            side_effect=lambda _db, library_id: _mock_get_library_watch_config(mock_db, library_id),
        ):
            watcher.start_watching_library("libraries/lib1")
            watcher.start_watching_library("libraries/lib2")

        # Verify both exist
        assert "libraries/lib1" in watcher.observers
        assert "libraries/lib2" in watcher.observers

        # Stop all
        watcher.stop_all()

        # Should be empty
        assert len(watcher.observers) == 0


class TestSyncWatchers:
    """Tests for FileWatcherService.sync_watchers."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_sync_watchers_empty_list_no_watchers_started(self) -> None:
        """sync_watchers should not start watchers when no libraries are watchable."""
        db = MagicMock()

        watcher = FileWatcherService(
            db=db,
            library_service=MagicMock(),
        )

        with (
            patch(
                "nomarr.services.infrastructure.file_watcher_svc.list_watchable_libraries",
                return_value=[],
            ) as list_watchable_libraries_mock,
            patch.object(
                watcher,
                "start_watching_library",
                wraps=watcher.start_watching_library,
            ) as start_watching_library,
        ):
            watcher.sync_watchers()

        start_watching_library.assert_not_called()
        assert watcher.observers == {}
        list_watchable_libraries_mock.assert_called_once_with(db)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_sync_watchers_starts_watchers_for_watchable_libraries(self, tmp_path) -> None:
        """sync_watchers should attempt to start watchers for watchable libraries."""
        library = {
            "_id": "libraries/lib1",
            "_key": "lib1",
            "name": "Library 1",
            "root_path": str(tmp_path),
            "watch_mode": "off",
        }
        db = MagicMock()

        watcher = FileWatcherService(
            db=db,
            library_service=MagicMock(),
        )

        with (
            patch(
                "nomarr.services.infrastructure.file_watcher_svc.list_watchable_libraries",
                return_value=[library],
            ) as list_watchable_libraries_mock,
            patch(
                "nomarr.services.infrastructure.file_watcher_svc.get_library_watch_config",
                return_value=library,
            ) as get_library_watch_config_mock,
            patch.object(
                watcher,
                "start_watching_library",
                wraps=watcher.start_watching_library,
            ) as start_watching_library,
        ):
            watcher.sync_watchers()

        start_watching_library.assert_called_once_with("libraries/lib1")
        list_watchable_libraries_mock.assert_called_once_with(db)
        get_library_watch_config_mock.assert_called_once_with(db, "libraries/lib1")
        assert "libraries/lib1" not in watcher.observers

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_sync_watchers_stops_watcher_for_removed_library(self) -> None:
        """sync_watchers should stop watchers for libraries no longer returned as watchable."""
        db = MagicMock()
        observer = MagicMock()

        watcher = FileWatcherService(
            db=db,
            library_service=MagicMock(),
        )
        watcher.observers["libraries/lib1"] = observer

        with patch(
            "nomarr.services.infrastructure.file_watcher_svc.list_watchable_libraries",
            return_value=[],
        ) as list_watchable_libraries_mock:
            watcher.sync_watchers()

        observer.stop.assert_called_once_with()
        observer.join.assert_called_once_with(timeout=5.0)
        assert "libraries/lib1" not in watcher.observers
        list_watchable_libraries_mock.assert_called_once_with(db)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_sync_watchers_skips_already_watched_library(self) -> None:
        """sync_watchers should not restart a watcher that is already active."""
        library = {
            "_id": "libraries/lib1",
            "_key": "lib1",
            "name": "Library 1",
            "root_path": "ignored",
            "watch_mode": "event",
        }
        db = MagicMock()
        observer = MagicMock()

        watcher = FileWatcherService(
            db=db,
            library_service=MagicMock(),
        )
        watcher.observers["libraries/lib1"] = observer

        with (
            patch(
                "nomarr.services.infrastructure.file_watcher_svc.list_watchable_libraries",
                return_value=[library],
            ) as list_watchable_libraries_mock,
            patch.object(watcher, "start_watching_library") as start_watching_library,
        ):
            watcher.sync_watchers()

        start_watching_library.assert_not_called()
        assert watcher.observers["libraries/lib1"] is observer
        list_watchable_libraries_mock.assert_called_once_with(db)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_sync_watchers_handles_start_error_gracefully(self, tmp_path) -> None:
        """sync_watchers should swallow ValueError when a watcher cannot be started."""
        library = {
            "_id": "libraries/lib1",
            "_key": "lib1",
            "name": "Library 1",
            "root_path": str(tmp_path),
            "watch_mode": "event",
        }
        db = MagicMock()

        watcher = FileWatcherService(
            db=db,
            library_service=MagicMock(),
        )

        with (
            patch(
                "nomarr.services.infrastructure.file_watcher_svc.list_watchable_libraries",
                return_value=[library],
            ) as list_watchable_libraries_mock,
            patch.object(
                watcher,
                "start_watching_library",
                side_effect=ValueError("bad watcher config"),
            ) as start_watching_library,
        ):
            watcher.sync_watchers()

        start_watching_library.assert_called_once_with("libraries/lib1")
        assert watcher.observers == {}
        list_watchable_libraries_mock.assert_called_once_with(db)

    @pytest.mark.asyncio
    async def test_polling_loop_exits_when_library_deleted(self, mock_db, mock_library_service):
        """_polling_loop should stop when library no longer exists mid-poll."""
        mock_db.library.update_library("libraries/lib1", watch_mode="poll")
        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
            polling_interval_seconds=0.1,
        )
        get_call_count = [0]

        def _get_config(_db, library_id):
            get_call_count[0] += 1
            if get_call_count[0] > 1:
                return None
            return _mock_get_library_watch_config(mock_db, library_id)

        with patch(
            "nomarr.services.infrastructure.file_watcher_svc.get_library_watch_config",
            side_effect=_get_config,
        ):
            watcher.start_watching_library("libraries/lib1")
            task = watcher.observers["libraries/lib1"]
            await asyncio.sleep(0.25)
        assert task.done()

    @pytest.mark.asyncio
    async def test_polling_loop_exits_when_watch_mode_becomes_off(self, mock_db, mock_library_service):
        """_polling_loop should stop when watch_mode flips to off mid-poll."""
        mock_db.library.update_library("libraries/lib1", watch_mode="poll")
        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
            polling_interval_seconds=0.1,
        )
        get_call_count = [0]

        def _get_config(_db, library_id):
            get_call_count[0] += 1
            lib = _mock_get_library_watch_config(mock_db, library_id)
            if get_call_count[0] > 1:
                return {**lib, "watch_mode": "off"}
            return lib

        with patch(
            "nomarr.services.infrastructure.file_watcher_svc.get_library_watch_config",
            side_effect=_get_config,
        ):
            watcher.start_watching_library("libraries/lib1")
            task = watcher.observers["libraries/lib1"]
            await asyncio.sleep(0.25)
        assert task.done()

    @pytest.mark.asyncio
    async def test_polling_loop_continues_on_library_already_scanning_error(self, mock_db):
        """_polling_loop should continue (not exit) on LibraryAlreadyScanningError."""
        mock_db.library.update_library("libraries/lib1", watch_mode="poll")
        scan_calls = []

        class SelectiveLibraryService:
            def start_quick_scan(self, library_id: str) -> None:
                scan_calls.append(library_id)
                if len(scan_calls) == 1:
                    raise LibraryAlreadyScanningError("already scanning")

        watcher = FileWatcherService(
            db=mock_db,
            library_service=SelectiveLibraryService(),  # type: ignore[arg-type]
            polling_interval_seconds=0.1,
        )
        with patch(
            "nomarr.services.infrastructure.file_watcher_svc.get_library_watch_config",
            side_effect=lambda _db, library_id: _mock_get_library_watch_config(mock_db, library_id),
        ):
            watcher.start_watching_library("libraries/lib1")
            await asyncio.sleep(0.35)
        watcher.stop_watching_library("libraries/lib1")
        assert len(scan_calls) >= 2

    @pytest.mark.asyncio
    async def test_polling_loop_exits_on_library_not_found_error(self, mock_db):
        """_polling_loop should stop when LibraryNotFoundError is raised by scan."""
        mock_db.library.update_library("libraries/lib1", watch_mode="poll")

        class MissingLibraryService:
            def start_quick_scan(self, library_id: str) -> None:
                raise LibraryNotFoundError(library_id)

        watcher = FileWatcherService(
            db=mock_db,
            library_service=MissingLibraryService(),  # type: ignore[arg-type]
            polling_interval_seconds=0.1,
        )
        with patch(
            "nomarr.services.infrastructure.file_watcher_svc.get_library_watch_config",
            side_effect=lambda _db, library_id: _mock_get_library_watch_config(mock_db, library_id),
        ):
            watcher.start_watching_library("libraries/lib1")
            task = watcher.observers["libraries/lib1"]
            await asyncio.sleep(0.25)
        assert task.done()

    @pytest.mark.asyncio
    async def test_switch_watch_mode_raises_when_library_not_found(self, mock_db, mock_library_service):
        """switch_watch_mode should raise ValueError when library does not exist."""
        watcher = FileWatcherService(
            db=mock_db,
            library_service=mock_library_service,
        )
        with (
            patch(
                "nomarr.services.infrastructure.file_watcher_svc.get_library_watch_config",
                return_value=None,
            ),
            pytest.raises(ValueError, match="not found"),
        ):
            watcher.switch_watch_mode("libraries/nonexistent", "event")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
