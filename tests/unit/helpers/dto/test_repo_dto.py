"""Unit tests for repo_dto TypedDict definitions."""

from __future__ import annotations

import pytest

from nomarr.helpers.dto.repo_dto import (
    HealthRow,
    LibraryFolderRow,
    LibraryRow,
    LibraryScanRow,
    LockRow,
    MetaRow,
    PipelineStateRow,
    SessionRow,
    SongRow,
    SongStateAssignmentRow,
    SongStateRow,
    SongTagRow,
    TagRow,
    WorkerClaimRow,
)


@pytest.mark.unit
class TestLibraryRow:
    """Tests for LibraryRow TypedDict."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """LibraryRow should be creatable with all required fields."""
        row = LibraryRow(
            id=1,
            name="Test Library",
            path="/music/test",
            library_type="music",
            auto_tag=1,
            auto_curate=0,
            created_at=1000,
            updated_at=1000,
        )
        assert row["id"] == 1
        assert row["name"] == "Test Library"
        assert row["path"] == "/music/test"
        assert row["library_type"] == "music"
        assert row["auto_tag"] == 1
        assert row["auto_curate"] == 0


@pytest.mark.unit
class TestSongRow:
    """Tests for SongRow TypedDict."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """SongRow should be creatable with all required fields."""
        row = SongRow(
            id=1,
            library_id=1,
            folder_id=None,
            path="/music/test.mp3",
            normalized_path="/music/test.mp3",
            file_size=1024,
            modified_time=2000,
            duration_seconds=180.5,
            chromaprint=None,
            needs_tagging=1,
            is_valid=1,
            tagged=0,
            calibration_hash=None,
            write_claimed_by=None,
            last_tagged_at=None,
            scanned_at=None,
            created_at=1000,
        )
        assert row["id"] == 1
        assert row["library_id"] == 1
        assert row["path"] == "/music/test.mp3"
        assert row["file_size"] == 1024
        assert row["duration_seconds"] == 180.5


@pytest.mark.unit
class TestLibraryFolderRow:
    """Tests for LibraryFolderRow TypedDict."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """LibraryFolderRow should be creatable with all required fields."""
        row = LibraryFolderRow(
            id=1,
            library_id=1,
            parent_id=None,
            path="/music/root",
            name="root",
        )
        assert row["id"] == 1
        assert row["library_id"] == 1
        assert row["parent_id"] is None
        assert row["path"] == "/music/root"


@pytest.mark.unit
class TestLibraryScanRow:
    """Tests for LibraryScanRow TypedDict."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """LibraryScanRow should be creatable with all required fields."""
        row = LibraryScanRow(
            id=1,
            library_id=1,
            scan_type="full",
            status="completed",
            started_at=1000,
            heartbeat_at=1500,
            finished_at=2000,
            files_found=100,
            files_processed=100,
            error=None,
        )
        assert row["id"] == 1
        assert row["scan_type"] == "full"
        assert row["status"] == "completed"
        assert row["files_found"] == 100


@pytest.mark.unit
class TestTagRow:
    """Tests for TagRow TypedDict."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """TagRow should be creatable with all required fields."""
        row = TagRow(
            id=1,
            name="rock",
            value="rock",
            namespace="genre",
            parent_tag_id=None,
            source="ml",
            confidence=0.95,
            tier="hot",
            created_at=1000,
        )
        assert row["id"] == 1
        assert row["name"] == "rock"
        assert row["namespace"] == "genre"
        assert row["confidence"] == 0.95


@pytest.mark.unit
class TestSongTagRow:
    """Tests for SongTagRow TypedDict."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """SongTagRow should be creatable with all required fields."""
        row = SongTagRow(
            id=1,
            song_id=1,
            tag_id=2,
            confidence=0.95,
            source="ml",
            created_at=1000,
        )
        assert row["id"] == 1
        assert row["song_id"] == 1
        assert row["tag_id"] == 2
        assert row["confidence"] == 0.95
        assert row["source"] == "ml"


@pytest.mark.unit
class TestSongStateRow:
    """Tests for SongStateRow TypedDict."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """SongStateRow should be creatable with all required fields."""
        row = SongStateRow(
            id=1,
            name="processed",
            description="Awaiting processing",
        )
        assert row["id"] == 1
        assert row["name"] == "processed"
        assert row["description"] == "Awaiting processing"


@pytest.mark.unit
class TestSongStateAssignmentRow:
    """Tests for SongStateAssignmentRow TypedDict."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """SongStateAssignmentRow should be creatable with all required fields."""
        row = SongStateAssignmentRow(
            id=1,
            song_id=1,
            state_id=1,
            created_at=1000,
        )
        assert row["id"] == 1
        assert row["song_id"] == 1
        assert row["state_id"] == 1


@pytest.mark.unit
class TestPipelineStateRow:
    """Tests for PipelineStateRow TypedDict."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """PipelineStateRow should be creatable with all required fields."""
        row = PipelineStateRow(
            id=1,
            library_id=1,
            state_key="scan",
            state_data={"status": "completed"},
            updated_at=1000,
        )
        assert row["id"] == 1
        assert row["state_key"] == "scan"
        assert row["state_data"]["status"] == "completed"


@pytest.mark.unit
class TestLockRow:
    """Tests for LockRow TypedDict."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """LockRow should be creatable with all required fields."""
        row = LockRow(
            key="test_lock",
            value={"holder": "worker1"},
        )
        assert row["key"] == "test_lock"
        assert row["value"]["holder"] == "worker1"


@pytest.mark.unit
class TestHealthRow:
    """Tests for HealthRow TypedDict."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """HealthRow should be creatable with all required fields."""
        row = HealthRow(
            id=1,
            worker_id="worker1",
            status="healthy",
            last_seen=1000,
        )
        assert row["id"] == 1
        assert row["worker_id"] == "worker1"
        assert row["status"] == "healthy"


@pytest.mark.unit
class TestMetaRow:
    """Tests for MetaRow TypedDict."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """MetaRow should be creatable with all required fields."""
        row = MetaRow(
            key="version",
            value={"major": 1, "minor": 0},
        )
        assert row["key"] == "version"
        assert row["value"]["major"] == 1


@pytest.mark.unit
class TestSessionRow:
    """Tests for SessionRow TypedDict."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """SessionRow should be creatable with all required fields."""
        row = SessionRow(
            id="session123",
            data={"user": "admin"},
            expires_at=2000,
        )
        assert row["id"] == "session123"
        assert row["data"]["user"] == "admin"
        assert row["expires_at"] == 2000


@pytest.mark.unit
class TestWorkerClaimRow:
    """Tests for WorkerClaimRow TypedDict."""

    @pytest.mark.unit
    def test_can_create_with_all_fields(self) -> None:
        """WorkerClaimRow should be creatable with all required fields."""
        row = WorkerClaimRow(
            id=1,
            worker_id="worker1",
            key="task1",
            value={"status": "processing"},
            claimed_at=1000,
        )
        assert row["id"] == 1
        assert row["worker_id"] == "worker1"
        assert row["key"] == "task1"
