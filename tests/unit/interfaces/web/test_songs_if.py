from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dto.library_dto import (
    FileTag,
    FileTagsResult,
    LibrarySongWithTags,
    SearchFilesQuery,
    SearchFilesResult,
    UniqueTagKeysResult,
)
from nomarr.helpers.song_locator_codec import encode_song_locator
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_library_service, get_tagging_service
from nomarr.interfaces.api.web.songs_if import router as songs_router

if TYPE_CHECKING:
    from collections.abc import Iterator

_LIBRARY_UUID = "6313b0d3-d270-47a8-9e0d-21e8255107e3"
_LIBRARY = LibraryIdentity(library_uuid=_LIBRARY_UUID, name="Test Library", root_path="D:/Music/Test")
_SONG = SongIdentity(library=_LIBRARY, normalized_path="songs/song.flac")
_SONG_TOKEN = encode_song_locator(_SONG)
_REPLY_SONG = SongIdentity(library=_LIBRARY, normalized_path="songs/reply.flac")
_REPLY_TOKEN = encode_song_locator(_REPLY_SONG)


def make_library_file(file_id: str = _REPLY_TOKEN) -> LibrarySongWithTags:
    """Build a minimal library file DTO for interface tests (opaque locator + UUID)."""
    return LibrarySongWithTags(
        file_id=file_id,
        path="/music/song.flac",
        library_uuid=_LIBRARY_UUID,
        file_size=1234,
        modified_time=1710000000,
        duration_seconds=215.5,
        artist="Test Artist",
        album="Test Album",
        title="Test Song",
        calibration_version=None,
        scanned_at=1710000001,
        last_tagged_at=1710000002,
        tagged=True,
        tagged_version="v1",
        skip_auto_tag=False,
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


def make_library() -> Library:
    """Build a domain ``Library`` fixture for interface tests (natural identity)."""
    return Library(name="Test Library", root_path="D:/Music/Test")


def make_search_result() -> SearchFilesResult:
    """Build a minimal paginated search result DTO."""
    return SearchFilesResult(
        songs=[make_library_file()],
        total=1,
        limit=25,
        offset=5,
    )


@pytest.fixture
def mock_library_service() -> MagicMock:
    """Provide a mocked library service dependency that resolves opaque tokens."""
    service = MagicMock()
    service.build_song_locator.side_effect = lambda library_uuid, normalized_path: SongIdentity(
        library=LibraryIdentity(library_uuid=library_uuid),
        normalized_path=normalized_path,
    )
    return service


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
    test_app.include_router(songs_router, prefix="/api/web")

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

    def test_search_songs_returns_response_and_builds_query(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """GET file search should build SearchFilesQuery and serialize opaque locators."""
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
                    "file_id": _REPLY_TOKEN,
                    "path": "/music/song.flac",
                    "library_uuid": _LIBRARY_UUID,
                    "file_size": 1234,
                    "modified_time": 1710000000,
                    "duration_seconds": 215.5,
                    "artist": "Test Artist",
                    "album": "Test Album",
                    "title": "Test Song",
                    "calibration_version": None,
                    "scanned_at": 1710000001,
                    "last_tagged_at": 1710000002,
                    "tagged": True,
                    "tagged_version": "v1",
                    "skip_auto_tag": False,
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

    def test_get_files_by_ids_decodes_tokens_to_semantic_locators(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """POST by-ids should resolve every opaque token to a semantic locator before the service call."""
        first = SongIdentity(library=_LIBRARY, normalized_path="songs/one.flac")
        second = SongIdentity(library=_LIBRARY, normalized_path="songs/two.flac")
        mock_library_service.get_files_by_ids.return_value = SearchFilesResult(
            songs=[make_library_file(file_id=_REPLY_TOKEN)],
            total=1,
            limit=1,
            offset=0,
        )

        response = client.post(
            "/api/web/library/file/by-ids",
            json={"file_ids": [encode_song_locator(first), encode_song_locator(second)]},
        )

        assert response.status_code == 200
        assert response.json()["files"][0]["file_id"] == _REPLY_TOKEN
        mock_library_service.get_files_by_ids.assert_called_once_with([first, second])

    def test_get_files_by_ids_rejects_malformed_token(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """A malformed opaque token should surface as 400, not 500."""
        response = client.post(
            "/api/web/library/file/by-ids",
            json={"file_ids": ["not-a-locator"]},
        )

        assert response.status_code == 400
        mock_library_service.get_files_by_ids.assert_not_called()

    def test_get_files_by_ids_propagates_404_when_locator_unknown(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """A syntactically valid token whose song is unknown should propagate 404 and skip the service."""
        mock_library_service.build_song_locator.side_effect = ValueError("unknown song")

        response = client.post(
            "/api/web/library/file/by-ids",
            json={"file_ids": [_SONG_TOKEN]},
        )

        assert response.status_code == 404
        assert response.json() == {"detail": "Song not found"}
        mock_library_service.get_files_by_ids.assert_not_called()

    def test_search_files_by_tag_returns_response(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """POST by-tag should forward the body fields to the tagging service."""
        mock_tagging_service.search_songs_by_tag.return_value = make_search_result()

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
        mock_tagging_service.search_songs_by_tag.assert_called_once_with(
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
        mock_library_service: MagicMock,
    ) -> None:
        """GET file tags should resolve the opaque token and serialize the tag payload."""
        mock_library_service.get_song_tags.return_value = FileTagsResult(
            file_id=_SONG_TOKEN,
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

        response = client.get(f"/api/web/library/file/{_SONG_TOKEN}/tag")

        assert response.status_code == 200
        assert response.json() == {
            "file_id": _SONG_TOKEN,
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
        call = mock_library_service.get_song_tags.call_args
        assert call.kwargs["song"] == _SONG
        assert call.kwargs["nomarr_only"] is False

    def test_get_file_tags_returns_404_when_missing(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """Missing files should surface as HTTP 404."""
        mock_library_service.get_song_tags.side_effect = ValueError("missing")

        response = client.get(f"/api/web/library/file/{_SONG_TOKEN}/tag")

        assert response.status_code == 404
        assert response.json() == {"detail": "File not found"}

    def test_retry_errored_files_returns_response(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """POST retry-errored should scope to the resolved Library when no body is sent."""
        library = make_library()
        mock_library_service.get_library_by_name.return_value = library
        mock_library_service.retry_errored_songs.return_value = {"retried": 3}

        response = client.post("/api/web/library/Test%20Library/retry-errored")

        assert response.status_code == 200
        assert response.json() == {"retried": 3}
        mock_library_service.get_library_by_name.assert_called_once_with("Test Library")
        mock_library_service.retry_errored_songs.assert_called_once_with(
            library,
            songs=None,
        )

    def test_retry_errored_files_returns_404_when_missing(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
    ) -> None:
        """Missing libraries should surface as HTTP 404 for retry-errored."""
        mock_library_service.get_library_by_name.return_value = None

        response = client.post("/api/web/library/Test%20Library/retry-errored")

        assert response.status_code == 404
        assert response.json() == {"detail": "Library not found"}
        mock_library_service.get_library_by_name.assert_called_once_with("Test Library")
        mock_library_service.retry_errored_songs.assert_not_called()
