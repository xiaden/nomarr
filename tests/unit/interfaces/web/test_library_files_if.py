from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.helpers.dto.library_dto import (
    FileTag,
    FileTagsResult,
    LibraryFileWithTags,
    SearchFilesQuery,
    SearchFilesResult,
    UniqueTagKeysResult,
)
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_library_service, get_tagging_service
from nomarr.interfaces.api.web.library_files_if import router as library_files_router


def make_library_file(file_id: str = "library_files/abc") -> LibraryFileWithTags:
    """Build a minimal library file DTO for interface tests."""
    return LibraryFileWithTags(
        _id=file_id,
        path="/music/song.flac",
        library_id="libraries/test-lib",
        file_size=1234,
        modified_time=1710000000,
        duration_seconds=215.5,
        artist="Test Artist",
        album="Test Album",
        title="Test Song",
        calibration=None,
        scanned_at=1710000001,
        last_tagged_at=1710000002,
        tagged=1,
        tagged_version="v1",
        skip_auto_tag=0,
        created_at="2026-04-06T00:00:00+00:00",
        updated_at="2026-04-06T00:00:00+00:00",
        tags=[
            FileTag(
                key="genre",
                value="rock",
                tag_type="string",
                is_nomarr=False,
            )
        ],
    )


def make_search_result() -> SearchFilesResult:
    """Build a minimal paginated search result DTO."""
    return SearchFilesResult(
        files=[make_library_file()],
        total=1,
        limit=25,
        offset=5,
    )


@pytest.fixture
def mock_library_service() -> MagicMock:
    """Provide a mocked library service dependency."""
    return MagicMock()


@pytest.fixture
def mock_tagging_service() -> MagicMock:
    """Provide a mocked tagging service dependency."""
    return MagicMock()


@pytest.fixture
def app(
    mock_library_service: MagicMock,
    mock_tagging_service: MagicMock,
) -> Iterator[FastAPI]:
    """Build a minimal FastAPI app for library file endpoints."""
    test_app = FastAPI()
    test_app.include_router(library_files_router, prefix="/api/web")

    async def allow_session() -> None:
        return None

    test_app.dependency_overrides[verify_session] = allow_session
    test_app.dependency_overrides[get_library_service] = lambda: mock_library_service
    test_app.dependency_overrides[get_tagging_service] = lambda: mock_tagging_service

    yield test_app

    test_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Create a TestClient for the minimal app."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.unit
@pytest.mark.mocked
class TestLibraryFilesEndpoints:
    """Tests for library file and tag routes."""

    def test_search_library_files_returns_response_and_builds_query(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """GET file search should build SearchFilesQuery and serialize the result."""
        mock_library_service.search_files.return_value = make_search_result()

        response = client.get(
            "/api/web/library/file/search",
            params={
                "q": "beatles",
                "artist": "The Beatles",
                "album": "Abbey Road",
                "tag_key": "genre",
                "tag_value": "rock",
                "tagged_only": True,
                "limit": 25,
                "offset": 5,
            },
        )

        assert response.status_code == 200
        assert response.json() == {
            "files": [
                {
                    "file_id": "library_files:abc",
                    "path": "/music/song.flac",
                    "library_id": "libraries:test-lib",
                    "file_size": 1234,
                    "modified_time": 1710000000,
                    "duration_seconds": 215.5,
                    "artist": "Test Artist",
                    "album": "Test Album",
                    "title": "Test Song",
                    "calibration": None,
                    "scanned_at": 1710000001,
                    "last_tagged_at": 1710000002,
                    "tagged": 1,
                    "tagged_version": "v1",
                    "skip_auto_tag": 0,
                    "created_at": "2026-04-06T00:00:00+00:00",
                    "updated_at": "2026-04-06T00:00:00+00:00",
                    "tags": [
                        {
                            "key": "genre",
                            "value": "rock",
                            "tag_type": "string",
                            "is_nomarr": False,
                        }
                    ],
                }
            ],
            "total": 1,
            "limit": 25,
            "offset": 5,
        }
        query = mock_library_service.search_files.call_args.args[0]
        assert isinstance(query, SearchFilesQuery)
        assert query == SearchFilesQuery(
            query_text="beatles",
            artist="The Beatles",
            album="Abbey Road",
            tag_key="genre",
            tag_value="rock",
            tagged_only=True,
            limit=25,
            offset=5,
        )

    def test_get_files_by_ids_decodes_ids_before_service_call(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """POST by-ids should decode every file ID before invoking the service."""
        mock_library_service.get_files_by_ids.return_value = SearchFilesResult(
            files=[make_library_file(file_id="library_files/xyz")],
            total=1,
            limit=1,
            offset=0,
        )

        response = client.post(
            "/api/web/library/file/by-ids",
            json={"file_ids": ["library_files:abc", "library_files:def"]},
        )

        assert response.status_code == 200
        assert response.json()["files"][0]["file_id"] == "library_files:xyz"
        mock_library_service.get_files_by_ids.assert_called_once_with(
            ["library_files/abc", "library_files/def"],
        )

    def test_search_files_by_tag_returns_response(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """POST by-tag should forward the body fields to the tagging service."""
        mock_tagging_service.search_files_by_tag.return_value = make_search_result()

        response = client.post(
            "/api/web/library/file/by-tag",
            json={
                "tag_key": "nom:bpm",
                "target_value": 120.0,
                "limit": 10,
                "offset": 0,
            },
        )

        assert response.status_code == 200
        assert response.json()["total"] == 1
        mock_tagging_service.search_files_by_tag.assert_called_once_with(
            tag_key="nom:bpm",
            target_value=120.0,
            limit=10,
            offset=0,
        )

    def test_get_unique_tag_keys_returns_response(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """GET unique-keys should serialize the unique tag keys response."""
        mock_tagging_service.get_unique_tag_keys.return_value = UniqueTagKeysResult(
            tag_keys=["genre", "nom:bpm"],
            count=2,
            calibration=None,
            library_id=None,
        )

        response = client.get("/api/web/library/file/tag/unique-keys")

        assert response.status_code == 200
        assert response.json() == {"tag_keys": ["genre", "nom:bpm"], "count": 2}
        mock_tagging_service.get_unique_tag_keys.assert_called_once_with(nomarr_only=False)

    def test_get_unique_tag_values_returns_response(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """GET tag values should pass the query params through unchanged."""
        mock_tagging_service.get_unique_tag_values.return_value = UniqueTagKeysResult(
            tag_keys=["rock", "pop"],
            count=2,
            calibration=None,
            library_id=None,
        )

        response = client.get(
            "/api/web/library/file/tag/values",
            params={"tag_key": "genre"},
        )

        assert response.status_code == 200
        assert response.json() == {"tag_keys": ["rock", "pop"], "count": 2}
        mock_tagging_service.get_unique_tag_values.assert_called_once_with(
            tag_key="genre",
            nomarr_only=True,
        )

    def test_get_unique_mood_values_returns_response(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """GET mood-values should use the default tier and limit when omitted."""
        mock_tagging_service.get_unique_mood_values.return_value = UniqueTagKeysResult(
            tag_keys=["aggressive", "party-like"],
            count=2,
            calibration=None,
            library_id=None,
        )

        response = client.get("/api/web/library/file/tag/mood-values")

        assert response.status_code == 200
        assert response.json() == {
            "tag_keys": ["aggressive", "party-like"],
            "count": 2,
        }
        mock_tagging_service.get_unique_mood_values.assert_called_once_with(
            mood_tier="mood-strict",
            limit=100,
        )

    def test_get_file_tags_returns_response(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """GET file tags should decode the path ID and serialize the tag payload."""
        mock_tagging_service.get_file_tags.return_value = FileTagsResult(
            file_id="library_files/abc",
            path="/music/song.flac",
            tags=[
                FileTag(
                    key="genre",
                    value="rock",
                    tag_type="string",
                    is_nomarr=False,
                )
            ],
        )

        response = client.get("/api/web/library/file/library_files:abc/tag")

        assert response.status_code == 200
        assert response.json() == {
            "file_id": "library_files/abc",
            "path": "/music/song.flac",
            "tags": [
                {
                    "key": "genre",
                    "value": "rock",
                    "tag_type": "string",
                    "is_nomarr": False,
                }
            ],
        }
        mock_tagging_service.get_file_tags.assert_called_once_with(
            file_id="library_files/abc",
            nomarr_only=False,
        )

    def test_get_file_tags_returns_404_when_missing(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Missing files should surface as HTTP 404."""
        mock_tagging_service.get_file_tags.side_effect = ValueError("missing")

        response = client.get("/api/web/library/file/library_files:abc/tag")

        assert response.status_code == 404
        assert response.json() == {"detail": "File not found"}
        mock_tagging_service.get_file_tags.assert_called_once_with(
            file_id="library_files/abc",
            nomarr_only=False,
        )

    def test_retry_errored_files_returns_response(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """POST retry-errored should default to retrying the entire library when no body is sent."""
        mock_library_service.retry_errored_files.return_value = {"retried": 3}

        response = client.post("/api/web/library/libraries:test-lib/retry-errored")

        assert response.status_code == 200
        assert response.json() == {"retried": 3}
        mock_library_service.retry_errored_files.assert_called_once_with(
            library_id="libraries/test-lib",
            file_ids=None,
        )

    def test_retry_errored_files_returns_404_when_missing(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """Missing libraries should surface as HTTP 404 for retry-errored."""
        mock_library_service.retry_errored_files.side_effect = ValueError("missing")

        response = client.post("/api/web/library/libraries:test-lib/retry-errored")

        assert response.status_code == 404
        assert response.json() == {"detail": "Library not found"}
        mock_library_service.retry_errored_files.assert_called_once_with(
            library_id="libraries/test-lib",
            file_ids=None,
        )
