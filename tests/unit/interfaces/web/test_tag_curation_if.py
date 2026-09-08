"""Tests for tag curation interface endpoints.

The tag-curation interface owns HTTP handle encode/decode. Every ``tag_id`` /
``source_tag_ids`` / ``canonical_tag_id`` / ``source_tag_id`` that a client
sends is an opaque complete-``TagRef`` handle decoded to a ``TagRef`` before
the service call, and every listed ``id`` is an opaque handle encoded from the
complete natural identity. These tests exercise that boundary through the real
HTTP layer (TestClient) with the service mocked below the boundary.
"""

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_tag_dataclass import TagRef
from nomarr.helpers.tag_handle_codec import decode_tag_handle, encode_tag_handle
from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web import tag_curation_if
from nomarr.interfaces.api.web.dependencies import get_library_service, get_tagging_service


def _handle(name: str, value: object, namespace: str = "default") -> str:
    """Encode a complete natural identity into an opaque wire handle."""
    return encode_tag_handle(TagRef(name=name, value=value, namespace=namespace))


@pytest.fixture
def mock_library_service() -> MagicMock:
    """Create a mock library service."""
    return MagicMock()


@pytest.fixture
def mock_tagging_service() -> MagicMock:
    """Create a mock tagging service."""
    return MagicMock()


@pytest.fixture
def app(
    mock_library_service: MagicMock,
    mock_tagging_service: MagicMock,
) -> FastAPI:
    """Create a test FastAPI app with mocked dependencies."""
    test_app = FastAPI()
    test_app.include_router(tag_curation_if.router)

    async def mock_verify_session() -> None:
        return None

    test_app.dependency_overrides[verify_session] = mock_verify_session
    test_app.dependency_overrides[get_library_service] = lambda: mock_library_service
    test_app.dependency_overrides[get_tagging_service] = lambda: mock_tagging_service

    return test_app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Create a test client."""
    with TestClient(app) as c:
        yield c


def _unauthed_app(mock_tagging_service: MagicMock) -> FastAPI:
    """App whose verify_session always rejects the request (auth preservation)."""
    test_app = FastAPI()
    test_app.include_router(tag_curation_if.router)

    async def reject_session() -> None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    test_app.dependency_overrides[verify_session] = reject_session
    test_app.dependency_overrides[get_tagging_service] = lambda: mock_tagging_service
    return test_app


@pytest.mark.unit
class TestRenameTag:
    """Tests for POST /tag-curation/rename endpoint."""

    def test_rename_tag_success(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should decode the opaque handle and pass a complete TagRef to the service."""
        mock_tagging_service.rename_tag.return_value = {
            "moved": 5,
            "merged_into_existing": False,
        }

        response = client.post(
            "/tag-curation/rename",
            json={"tag_id": _handle("genre", "Electronic"), "new_value": "Synthwave"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["moved"] == 5
        assert data["merged_into_existing"] is False
        mock_tagging_service.rename_tag.assert_called_once_with(
            source_tag=TagRef(name="genre", value="Electronic", namespace="default"),
            new_value="Synthwave",
        )

    def test_rename_tag_malformed_handle_returns_400(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """A non-handle id is malformed input -> 400; the service is never called."""
        response = client.post(
            "/tag-curation/rename",
            json={"tag_id": "tag1", "new_value": "new_name"},
        )

        assert response.status_code == 400
        mock_tagging_service.rename_tag.assert_not_called()

    def test_rename_tag_value_error(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should return 400 when the service raises ValueError (e.g. nom / not found)."""
        mock_tagging_service.rename_tag.side_effect = ValueError("Tag not found: genre=Electronic")

        response = client.post(
            "/tag-curation/rename",
            json={"tag_id": _handle("genre", "Electronic"), "new_value": "new_name"},
        )

        assert response.status_code == 400
        assert "Tag not found: genre=Electronic" in response.json()["detail"]

    def test_rename_tag_exception(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should return 500 when a non-ValueError exception is raised."""
        mock_tagging_service.rename_tag.side_effect = RuntimeError("Database error")

        response = client.post(
            "/tag-curation/rename",
            json={"tag_id": _handle("genre", "Electronic"), "new_value": "new_name"},
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
        """Should decode each source + canonical handle into complete TagRefs."""
        mock_tagging_service.merge_tags.return_value = {
            "total_moved": 10,
            "sources_removed": 2,
        }

        response = client.post(
            "/tag-curation/merge",
            json={
                "source_tag_ids": [_handle("genre", "Electronic"), _handle("genre", "EDM")],
                "canonical_tag_id": _handle("genre", "Electronic"),
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total_moved"] == 10
        assert data["sources_removed"] == 2
        mock_tagging_service.merge_tags.assert_called_once_with(
            source_tags=[
                TagRef(name="genre", value="Electronic", namespace="default"),
                TagRef(name="genre", value="EDM", namespace="default"),
            ],
            canonical_tag=TagRef(name="genre", value="Electronic", namespace="default"),
        )

    def test_merge_tags_malformed_handle_returns_400(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Any malformed source/canonical handle -> 400; service never called."""
        response = client.post(
            "/tag-curation/merge",
            json={
                "source_tag_ids": [_handle("genre", "Electronic"), "not-a-handle"],
                "canonical_tag_id": _handle("genre", "Electronic"),
            },
        )

        assert response.status_code == 400
        mock_tagging_service.merge_tags.assert_not_called()

    def test_merge_tags_value_error(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should return 400 when the service raises ValueError."""
        mock_tagging_service.merge_tags.side_effect = ValueError("Invalid tag IDs")

        response = client.post(
            "/tag-curation/merge",
            json={
                "source_tag_ids": [_handle("genre", "Electronic")],
                "canonical_tag_id": _handle("genre", "EDM"),
            },
        )

        assert response.status_code == 400
        assert "Invalid tag IDs" in response.json()["detail"]

    def test_merge_tags_exception(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should return 500 when a non-ValueError exception is raised."""
        mock_tagging_service.merge_tags.side_effect = RuntimeError("Database error")

        response = client.post(
            "/tag-curation/merge",
            json={
                "source_tag_ids": [_handle("genre", "Electronic")],
                "canonical_tag_id": _handle("genre", "EDM"),
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
        """Should decode the source handle and pass complete TagRef + song ids."""
        mock_tagging_service.split_tag.return_value = {
            "moved": 3,
            "new_tag_created": True,
        }

        response = client.post(
            "/tag-curation/split",
            json={
                "source_tag_id": _handle("genre", "Electronic"),
                "song_ids": ["1", "2", "3"],
                "new_value": "Synthwave",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["moved"] == 3
        assert data["new_tag_created"] is True
        mock_tagging_service.split_tag.assert_called_once_with(
            source_tag=TagRef(name="genre", value="Electronic", namespace="default"),
            song_ids=["1", "2", "3"],
            new_value="Synthwave",
        )

    def test_split_tag_malformed_handle_returns_400(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """A malformed source handle -> 400; service never called."""
        response = client.post(
            "/tag-curation/split",
            json={"source_tag_id": "tag1", "song_ids": ["1"], "new_value": "Synthwave"},
        )

        assert response.status_code == 400
        mock_tagging_service.split_tag.assert_not_called()

    def test_split_tag_value_error(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should return 400 when the service raises ValueError."""
        mock_tagging_service.split_tag.side_effect = ValueError("Invalid song IDs")

        response = client.post(
            "/tag-curation/split",
            json={
                "source_tag_id": _handle("genre", "Electronic"),
                "song_ids": ["invalid"],
                "new_value": "Synthwave",
            },
        )

        assert response.status_code == 400
        assert "Invalid song IDs" in response.json()["detail"]

    def test_split_tag_exception(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should return 500 when a non-ValueError exception is raised."""
        mock_tagging_service.split_tag.side_effect = RuntimeError("Database error")

        response = client.post(
            "/tag-curation/split",
            json={
                "source_tag_id": _handle("genre", "Electronic"),
                "song_ids": ["1"],
                "new_value": "Synthwave",
            },
        )

        assert response.status_code == 500
        assert "Failed to split tag" in response.json()["detail"]


@pytest.mark.unit
class TestListTagValues:
    """Tests for GET /tag-curation/value endpoint."""

    def test_list_tag_values_emits_opaque_handles(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Listed ids are complete-TagRef handles; public field set is unchanged."""
        mock_tagging_service.list_tag_values.return_value = {
            "tags": [
                {
                    "id": "rock",
                    "name": "genre",
                    "value": "rock",
                    "namespace": "default",
                    "song_count": 10,
                },
                {
                    "id": "Electronic",
                    "name": "genre",
                    "value": "Electronic",
                    "namespace": "default",
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
        # Public field set unchanged (no namespace leak).
        assert set(data["tags"][0].keys()) == {"id", "name", "value", "song_count"}
        assert data["tags"][0]["name"] == "genre"
        assert data["tags"][0]["value"] == "rock"
        # The opaque id decodes back to the complete natural identity.
        assert decode_tag_handle(data["tags"][0]["id"]) == TagRef(name="genre", value="rock", namespace="default")
        assert decode_tag_handle(data["tags"][1]["id"]) == TagRef(name="genre", value="Electronic", namespace="default")
        mock_tagging_service.list_tag_values.assert_called_once_with(name="genre", prefix=None, limit=100, offset=0)

    def test_listing_is_namespace_distinct(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Identical (name, value) in default vs nom namespaces yield distinct handles."""
        mock_tagging_service.list_tag_values.return_value = {
            "tags": [
                {"id": "happy", "name": "mood", "value": "happy", "namespace": "default", "song_count": 4},
                {"id": "happy", "name": "mood", "value": "happy", "namespace": "nom", "song_count": 7},
            ],
            "total": 2,
        }

        response = client.get("/tag-curation/value", params={"name": "mood"})

        assert response.status_code == 200
        data = response.json()
        assert len(data["tags"]) == 2
        default_id, nom_id = data["tags"][0]["id"], data["tags"][1]["id"]
        assert default_id != nom_id
        assert decode_tag_handle(default_id) == TagRef(name="mood", value="happy", namespace="default")
        assert decode_tag_handle(nom_id) == TagRef(name="mood", value="happy", namespace="nom")

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
        """Should return 500 when the service raises."""
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
        """Should decode the path handle and pass a complete TagRef identity."""
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

        handle = _handle("genre", "Electronic")
        response = client.get(
            f"/tag-curation/{handle}/song",
            params={"limit": 50, "offset": 0},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["songs"][0]["title"] == "Song 1"
        mock_tagging_service.get_tag_songs.assert_called_once_with(
            identity=TagRef(name="genre", value="Electronic", namespace="default"),
            limit=50,
            offset=0,
        )

    def test_get_tag_songs_malformed_handle_returns_400(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """A malformed (non-handle) path id is malformed input -> 400, not 404."""
        response = client.get("/tag-curation/not-a-handle/song")

        assert response.status_code == 400
        mock_tagging_service.get_tag_songs.assert_not_called()

    def test_get_tag_songs_missing_identity_returns_404(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """A valid handle for a missing identity keeps the route's 404 behavior."""
        mock_tagging_service.get_tag_songs.side_effect = ValueError("Tag not found: genre=Electronic")

        response = client.get(
            f"/tag-curation/{_handle('genre', 'Electronic')}/song",
        )

        assert response.status_code == 404
        assert "Tag not found" in response.json()["detail"]

    def test_get_tag_songs_exception(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should return 500 when a non-ValueError exception is raised."""
        mock_tagging_service.get_tag_songs.side_effect = RuntimeError("Database error")

        response = client.get(f"/tag-curation/{_handle('genre', 'Electronic')}/song")

        assert response.status_code == 500
        assert "Failed to get tag songs" in response.json()["detail"]


@pytest.mark.unit
class TestIdentityRoundTrips:
    """Codec round trips through the real HTTP layer (list -> lookup continuity)."""

    def test_listing_to_lookup_continuity(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """A listed handle drives the subsequent song lookup with the same identity."""
        mock_tagging_service.list_tag_values.return_value = {
            "tags": [
                {"id": "Electronic", "name": "genre", "value": "Electronic", "namespace": "default", "song_count": 5},
            ],
            "total": 1,
        }
        mock_tagging_service.get_tag_songs.return_value = {"songs": [], "total": 0}

        listed = client.get("/tag-curation/value", params={"name": "genre"})
        assert listed.status_code == 200
        handle = listed.json()["tags"][0]["id"]

        # The listed opaque handle is a complete identity; feeding it to the song
        # lookup reaches the service with that exact TagRef (never a value-only id).
        looked_up = client.get(f"/tag-curation/{handle}/song")
        assert looked_up.status_code == 200
        mock_tagging_service.get_tag_songs.assert_called_once_with(
            identity=TagRef(name="genre", value="Electronic", namespace="default"),
            limit=50,
            offset=0,
        )

    def test_electronic_string_value(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """'Electronic' is data (string), never parsed as anything else."""
        mock_tagging_service.get_tag_songs.return_value = {"songs": [], "total": 0}
        client.get(f"/tag-curation/{_handle('genre', 'Electronic')}/song")
        mock_tagging_service.get_tag_songs.assert_called_once_with(
            identity=TagRef(name="genre", value="Electronic", namespace="default"),
            limit=50,
            offset=0,
        )

    @pytest.mark.parametrize("natural_value", ["120", 120])
    def test_numeric_natural_value(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
        natural_value: object,
    ) -> None:
        """Numeric 120 is data: the string and int natural forms stay distinct."""
        mock_tagging_service.get_tag_songs.return_value = {"songs": [], "total": 0}
        handle = _handle("bpm", natural_value)
        client.get(f"/tag-curation/{handle}/song")
        decoded = decode_tag_handle(handle)
        # Value-type-preserving: '120' string vs 120 int round-trip distinctly.
        assert isinstance(decoded.value, type(natural_value))
        assert decoded.value == natural_value
        assert decoded == TagRef(name="bpm", value=natural_value, namespace="default")
        mock_tagging_service.get_tag_songs.assert_called_once_with(
            identity=decoded,
            limit=50,
            offset=0,
        )

    def test_unicode_value_round_trip(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Unicode and reserved characters survive a full HTTP round trip."""
        value = "Électronique/ロック 😀"
        mock_tagging_service.get_tag_songs.return_value = {"songs": [], "total": 0}
        handle = _handle("genre", value)
        client.get(f"/tag-curation/{handle}/song")
        mock_tagging_service.get_tag_songs.assert_called_once_with(
            identity=TagRef(name="genre", value=value, namespace="default"),
            limit=50,
            offset=0,
        )

    def test_default_vs_nom_namespace_distinct(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """default and nom namespaces address different natural identities."""
        mock_tagging_service.get_tag_songs.return_value = {"songs": [], "total": 0}
        default_handle = _handle("mood", "happy", namespace="default")
        nom_handle = _handle("mood", "happy", namespace="nom")
        assert default_handle != nom_handle
        assert decode_tag_handle(default_handle).namespace == "default"
        assert decode_tag_handle(nom_handle).namespace == "nom"

        client.get(f"/tag-curation/{nom_handle}/song")
        mock_tagging_service.get_tag_songs.assert_called_once_with(
            identity=TagRef(name="mood", value="happy", namespace="nom"),
            limit=50,
            offset=0,
        )

    def test_stale_handle_after_rename_returns_404(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """After a rename the old identity's handle no longer resolves (404)."""
        old_handle = _handle("genre", "Electronic")

        def _renamed_not_found(identity, limit, offset):
            raise ValueError(f"Tag not found: {identity.name}={identity.value}")

        mock_tagging_service.get_tag_songs.side_effect = _renamed_not_found
        response = client.get(f"/tag-curation/{old_handle}/song")
        assert response.status_code == 404
        assert "Tag not found" in response.json()["detail"]

    def test_refreshed_listing_emits_new_handle_after_rename(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """A refreshed listing reflects the target identity's new handle."""
        mock_tagging_service.list_tag_values.return_value = {
            "tags": [
                {"id": "Synthwave", "name": "genre", "value": "Synthwave", "namespace": "default", "song_count": 5},
            ],
            "total": 1,
        }
        response = client.get("/tag-curation/value", params={"name": "genre"})
        assert response.status_code == 200
        new_handle = response.json()["tags"][0]["id"]
        assert decode_tag_handle(new_handle) == TagRef(name="genre", value="Synthwave", namespace="default")


@pytest.mark.unit
class TestRoutesAndAuth:
    """Route names, field names, and auth behavior are preserved."""

    def test_unchanged_route_names(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Route paths and request/response field names are unchanged."""
        mock_tagging_service.list_tag_values.return_value = {"tags": [], "total": 0}
        for path in (
            "/tag-curation/value",
            f"/tag-curation/{_handle('genre', 'Electronic')}/song",
        ):
            assert client.get(path).status_code in (200, 404, 500)
        # The body-driven curation routes still accept their historical field names.
        assert client.post("/tag-curation/rename", json={"tag_id": "x", "new_value": "y"}).status_code == 400
        assert (
            client.post(
                "/tag-curation/merge",
                json={"source_tag_ids": ["x"], "canonical_tag_id": "y"},
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/tag-curation/split",
                json={"source_tag_id": "x", "song_ids": ["1"], "new_value": "y"},
            ).status_code
            == 400
        )
        assert client.get("/tag-curation/pending-count").status_code == 200

    def test_auth_error_preserved(
        self,
        mock_tagging_service: MagicMock,
    ) -> None:
        """An unauthenticated request still 401s at the auth dependency."""
        mock_tagging_service.list_tag_values.return_value = {"tags": [], "total": 0}
        unauthed = _unauthed_app(mock_tagging_service)
        with TestClient(unauthed) as c:
            response = c.get("/tag-curation/value")
        assert response.status_code == 401
        assert "Not authenticated" in response.json()["detail"]
        mock_tagging_service.list_tag_values.assert_not_called()


@pytest.mark.unit
class TestCommitPendingTags:
    """Tests for POST /tag-curation/commit endpoint."""

    def test_commit_pending_tags_success(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should commit pending tags and return result."""
        library = Library(name="lib1", root_path="/music")
        mock_library_service.get_library_by_name.return_value = library
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
        mock_library_service.get_library_by_name.assert_called_once_with("lib1")
        mock_tagging_service.commit_pending_tags.assert_called_once_with(library=library)

    def test_commit_pending_tags_no_library(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should commit without library_id."""
        mock_library_service.get_library_by_name.return_value = None
        mock_tagging_service.commit_pending_tags.return_value = {
            "started": True,
            "pending_files": 0,
        }

        response = client.post("/tag-curation/commit", json={})

        assert response.status_code == 200
        mock_library_service.get_library_by_name.assert_not_called()
        mock_tagging_service.commit_pending_tags.assert_called_once_with(library=None)

    def test_commit_pending_tags_exception(
        self,
        client: TestClient,
        mock_library_service: MagicMock,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should return 500 when exception raised."""
        mock_library_service.get_library_by_name.return_value = None
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
    """Tests for PATCH /tag-curation/file/{file_id}/tag endpoint.

    ``file_id`` is the separate song/file boundary and is untouched by the
    tag-handle change (it stays a numeric path id, decoded via ``decode_path_id``).
    """

    def test_update_file_tags_success(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should update file tags and return result."""
        mock_tagging_service.update_song_tags.return_value = {
            "file_id": "123",
            "name": "genre",
            "tags": [
                {
                    "key": "genre",
                    "value": "rock",
                    "tag_type": "string",
                    "is_nomarr": False,
                },
                {
                    "key": "genre",
                    "value": "alternative",
                    "tag_type": "string",
                    "is_nomarr": False,
                },
            ],
        }

        response = client.patch(
            "/tag-curation/file/123/tag",
            json={"name": "genre", "values": ["rock", "alternative"]},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["file_id"] == "123"
        assert data["name"] == "genre"
        assert data["tags"] == [
            {
                "key": "genre",
                "value": "rock",
                "tag_type": "string",
                "is_nomarr": False,
            },
            {
                "key": "genre",
                "value": "alternative",
                "tag_type": "string",
                "is_nomarr": False,
            },
        ]
        mock_tagging_service.update_song_tags.assert_called_once_with(
            song_id="123", name="genre", values=["rock", "alternative"]
        )

    def test_update_file_tags_value_error(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should return 400 when ValueError raised."""
        mock_tagging_service.update_song_tags.side_effect = ValueError("Invalid file ID")

        response = client.patch(
            "/tag-curation/file/999/tag",
            json={"name": "genre", "values": ["rock"]},
        )

        assert response.status_code == 400
        assert "Invalid file ID" in response.json()["detail"]
        mock_tagging_service.update_song_tags.assert_called_once_with(song_id="999", name="genre", values=["rock"])

    def test_update_file_tags_exception(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Should return 500 when exception raised."""
        mock_tagging_service.update_song_tags.side_effect = RuntimeError("Database error")

        response = client.patch(
            "/tag-curation/file/123/tag",
            json={"name": "genre", "values": ["rock"]},
        )

        assert response.status_code == 500
        assert "Failed to update file tags" in response.json()["detail"]

    def test_update_file_tags_decodes_numeric_id_and_rejects_non_numeric(
        self,
        client: TestClient,
        mock_tagging_service: MagicMock,
    ) -> None:
        """Regression: the route validates the path ID at the boundary like songs_if."""
        mock_tagging_service.update_song_tags.return_value = {
            "file_id": "456",
            "name": "genre",
            "tags": [],
        }

        # Non-numeric → 400 at the boundary, service not called.
        response = client.patch(
            "/tag-curation/file/not-a-number/tag",
            json={"name": "genre", "values": ["rock"]},
        )

        assert response.status_code == 400
        assert "Invalid ID format" in response.json()["detail"]
        mock_tagging_service.update_song_tags.assert_not_called()

        # Numeric → passes the boundary gate and is forwarded to the service.
        response = client.patch(
            "/tag-curation/file/456/tag",
            json={"name": "genre", "values": ["rock"]},
        )

        assert response.status_code == 200
        mock_tagging_service.update_song_tags.assert_called_once_with(song_id="456", name="genre", values=["rock"])
