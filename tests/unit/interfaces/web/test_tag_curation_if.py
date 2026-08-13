"""Tests for tag curation interface endpoints."""

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web import tag_curation_if
from nomarr.interfaces.api.web.dependencies import get_tagging_service


@pytest.fixture
def mock_tagging_service() -> MagicMock:
    """Create a mock tagging service."""
    return MagicMock()


@pytest.fixture
def app(mock_tagging_service: MagicMock) -> FastAPI:
    """Create a test FastAPI app with mocked dependencies."""
    test_app = FastAPI()
    test_app.include_router(tag_curation_if.router)

    async def mock_verify_session() -> None:
        return None

    test_app.dependency_overrides[verify_session] = mock_verify_session
    test_app.dependency_overrides[get_tagging_service] = lambda: mock_tagging_service

    return test_app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Create a test client."""
    with TestClient(app) as c:
        yield c


@pytest.mark.unit
class TestRenameTag:
    """Tests for POST /tag-curation/rename endpoint."""

    def test_rename_tag_success(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should rename tag and return result."""
        mock_tagging_service.rename_tag.return_value = {
            "moved": 5,
            "merged_into_existing": False,
        }

        response = client.post(
            "/tag-curation/rename",
            json={"tag_id": "tag1", "new_value": "new_name"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["moved"] == 5
        assert data["merged_into_existing"] is False
        mock_tagging_service.rename_tag.assert_called_once_with(tag_id="tag1", new_value="new_name")

    def test_rename_tag_value_error(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should return 400 when ValueError raised."""
        mock_tagging_service.rename_tag.side_effect = ValueError("Invalid tag ID")

        response = client.post(
            "/tag-curation/rename",
            json={"tag_id": "invalid", "new_value": "new_name"},
        )

        assert response.status_code == 400
        assert "Invalid tag ID" in response.json()["detail"]

    def test_rename_tag_exception(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should return 500 when exception raised."""
        mock_tagging_service.rename_tag.side_effect = RuntimeError("Database error")

        response = client.post(
            "/tag-curation/rename",
            json={"tag_id": "tag1", "new_value": "new_name"},
        )

        assert response.status_code == 500
        assert "Failed to rename tag" in response.json()["detail"]


@pytest.mark.unit
class TestMergeTags:
    """Tests for POST /tag-curation/merge endpoint."""

    def test_merge_tags_success(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should merge tags and return result."""
        mock_tagging_service.merge_tags.return_value = {
            "total_moved": 10,
            "sources_removed": 2,
        }

        response = client.post(
            "/tag-curation/merge",
            json={
                "source_tag_ids": ["tag1", "tag2"],
                "canonical_tag_id": "tag3",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_moved"] == 10
        assert data["sources_removed"] == 2
        mock_tagging_service.merge_tags.assert_called_once_with(
            source_tag_ids=["tag1", "tag2"], canonical_tag_id="tag3"
        )

    def test_merge_tags_value_error(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should return 400 when ValueError raised."""
        mock_tagging_service.merge_tags.side_effect = ValueError("Invalid tag IDs")

        response = client.post(
            "/tag-curation/merge",
            json={
                "source_tag_ids": ["invalid"],
                "canonical_tag_id": "tag1",
            },
        )

        assert response.status_code == 400
        assert "Invalid tag IDs" in response.json()["detail"]

    def test_merge_tags_exception(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should return 500 when exception raised."""
        mock_tagging_service.merge_tags.side_effect = RuntimeError("Database error")

        response = client.post(
            "/tag-curation/merge",
            json={
                "source_tag_ids": ["tag1", "tag2"],
                "canonical_tag_id": "tag3",
            },
        )

        assert response.status_code == 500
        assert "Failed to merge tags" in response.json()["detail"]


@pytest.mark.unit
class TestSplitTag:
    """Tests for POST /tag-curation/split endpoint."""

    def test_split_tag_success(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should split tag and return result."""
        mock_tagging_service.split_tag.return_value = {
            "moved": 3,
            "new_tag_created": True,
        }

        response = client.post(
            "/tag-curation/split",
            json={
                "source_tag_id": "tag1",
                "song_ids": ["song1", "song2", "song3"],
                "new_value": "new_genre",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["moved"] == 3
        assert data["new_tag_created"] is True
        mock_tagging_service.split_tag.assert_called_once_with(
            source_tag_id="tag1",
            song_ids=["song1", "song2", "song3"],
            new_value="new_genre",
        )

    def test_split_tag_value_error(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should return 400 when ValueError raised."""
        mock_tagging_service.split_tag.side_effect = ValueError("Invalid song IDs")

        response = client.post(
            "/tag-curation/split",
            json={
                "source_tag_id": "tag1",
                "song_ids": ["invalid"],
                "new_value": "new_genre",
            },
        )

        assert response.status_code == 400
        assert "Invalid song IDs" in response.json()["detail"]

    def test_split_tag_exception(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should return 500 when exception raised."""
        mock_tagging_service.split_tag.side_effect = RuntimeError("Database error")

        response = client.post(
            "/tag-curation/split",
            json={
                "source_tag_id": "tag1",
                "song_ids": ["song1"],
                "new_value": "new_genre",
            },
        )

        assert response.status_code == 500
        assert "Failed to split tag" in response.json()["detail"]


@pytest.mark.unit
class TestListTagValues:
    """Tests for GET /tag-curation/value endpoint."""

    def test_list_tag_values_success(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should list tag values with filtering."""
        mock_tagging_service.list_tag_values.return_value = {
            "tags": [
                {
                    "id": "tag1",
                    "name": "genre",
                    "value": "rock",
                    "song_count": 10,
                },
                {
                    "id": "tag2",
                    "name": "genre",
                    "value": "jazz",
                    "song_count": 5,
                },
            ],
            "total": 2,
        }

        response = client.get(
            "/tag-curation/value",
            params={"name": "genre", "limit": 100, "offset": 0},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert len(data["tags"]) == 2
        assert data["tags"][0]["value"] == "rock"
        mock_tagging_service.list_tag_values.assert_called_once_with(name="genre", prefix=None, limit=100, offset=0)

    def test_list_tag_values_with_prefix(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should filter by prefix."""
        mock_tagging_service.list_tag_values.return_value = {
            "tags": [],
            "total": 0,
        }

        response = client.get(
            "/tag-curation/value",
            params={"prefix": "ro", "limit": 50, "offset": 10},
        )

        assert response.status_code == 200
        mock_tagging_service.list_tag_values.assert_called_once_with(name=None, prefix="ro", limit=50, offset=10)

    def test_list_tag_values_exception(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should return 500 when exception raised."""
        mock_tagging_service.list_tag_values.side_effect = RuntimeError("Database error")

        response = client.get("/tag-curation/value")

        assert response.status_code == 500
        assert "Failed to list tag values" in response.json()["detail"]


@pytest.mark.unit
class TestGetTagSongs:
    """Tests for GET /tag-curation/{tag_id}/song endpoint."""

    def test_get_tag_songs_success(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should get songs for a tag."""
        mock_tagging_service.get_tag_songs.return_value = {
            "songs": [
                {
                    "file_id": "file1",
                    "title": "Song 1",
                    "artist": "Artist 1",
                    "album": "Album 1",
                    "path": "/music/song1.mp3",
                },
            ],
            "total": 1,
        }

        response = client.get(
            "/tag-curation/tag1/song",
            params={"limit": 50, "offset": 0},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["songs"]) == 1
        assert data["songs"][0]["title"] == "Song 1"
        mock_tagging_service.get_tag_songs.assert_called_once_with(tag_id="tag1", limit=50, offset=0)

    def test_get_tag_songs_not_found(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should return 404 when tag not found."""
        mock_tagging_service.get_tag_songs.side_effect = ValueError("Tag not found")

        response = client.get("/tag-curation/invalid/song")

        assert response.status_code == 404
        assert "Tag not found" in response.json()["detail"]

    def test_get_tag_songs_exception(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should return 500 when exception raised."""
        mock_tagging_service.get_tag_songs.side_effect = RuntimeError("Database error")

        response = client.get("/tag-curation/tag1/song")

        assert response.status_code == 500
        assert "Failed to get tag songs" in response.json()["detail"]


@pytest.mark.unit
class TestCommitPendingTags:
    """Tests for POST /tag-curation/commit endpoint."""

    def test_commit_pending_tags_success(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should commit pending tags and return result."""
        mock_tagging_service.commit_pending_tags.return_value = {
            "started": True,
            "pending_files": 5,
        }

        response = client.post(
            "/tag-curation/commit",
            json={"library_id": "lib1"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["started"] is True
        assert data["pending_files"] == 5
        mock_tagging_service.commit_pending_tags.assert_called_once_with(library_id="lib1")

    def test_commit_pending_tags_no_library(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should commit without library_id."""
        mock_tagging_service.commit_pending_tags.return_value = {
            "started": True,
            "pending_files": 0,
        }

        response = client.post("/tag-curation/commit", json={})

        assert response.status_code == 200
        mock_tagging_service.commit_pending_tags.assert_called_once_with(library_id=None)

    def test_commit_pending_tags_exception(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should return 500 when exception raised."""
        mock_tagging_service.commit_pending_tags.side_effect = RuntimeError("Database error")

        response = client.post("/tag-curation/commit", json={})

        assert response.status_code == 500
        assert "Failed to commit tags" in response.json()["detail"]


@pytest.mark.unit
class TestGetPendingCommitCount:
    """Tests for GET /tag-curation/pending-count endpoint."""

    def test_get_pending_count_success(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should get pending commit count."""
        mock_tagging_service.get_pending_commit_count.return_value = 10

        response = client.get("/tag-curation/pending-count")

        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 10
        mock_tagging_service.get_pending_commit_count.assert_called_once()

    def test_get_pending_count_exception(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should return 500 when exception raised."""
        mock_tagging_service.get_pending_commit_count.side_effect = RuntimeError("Database error")

        response = client.get("/tag-curation/pending-count")

        assert response.status_code == 500
        assert "Failed to get pending count" in response.json()["detail"]


@pytest.mark.unit
class TestUpdateFileTags:
    """Tests for PATCH /tag-curation/file/{file_id}/tag endpoint."""

    def test_update_file_tags_success(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should update file tags and return result."""
        mock_tagging_service.update_song_tags.return_value = {
            "file_id": "file1",
            "name": "genre",
            "tags": {"genre": ["rock", "alternative"]},
        }

        response = client.patch(
            "/tag-curation/file/file1/tag",
            json={"name": "genre", "values": ["rock", "alternative"]},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["file_id"] == "file1"
        assert data["name"] == "genre"
        assert data["tags"]["genre"] == ["rock", "alternative"]
        mock_tagging_service.update_song_tags.assert_called_once_with(
            song_id="file1", name="genre", values=["rock", "alternative"]
        )

    def test_update_file_tags_value_error(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should return 400 when ValueError raised."""
        mock_tagging_service.update_song_tags.side_effect = ValueError("Invalid file ID")

        response = client.patch(
            "/tag-curation/file/invalid/tag",
            json={"name": "genre", "values": ["rock"]},
        )

        assert response.status_code == 400
        assert "Invalid file ID" in response.json()["detail"]

    def test_update_file_tags_exception(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should return 500 when exception raised."""
        mock_tagging_service.update_song_tags.side_effect = RuntimeError("Database error")

        response = client.patch(
            "/tag-curation/file/file1/tag",
            json={"name": "genre", "values": ["rock"]},
        )

        assert response.status_code == 500
        assert "Failed to update file tags" in response.json()["detail"]
