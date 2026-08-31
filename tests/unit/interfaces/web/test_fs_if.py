"""Tests for the filesystem browser web interface (``nomarr.interfaces.api.web.fs_if``).

Focus: the clean-break wire contract for ``GET /api/web/file-system/list`` —
a ``{path, entries:[{name,is_dir}]}`` projection, traversal rejection (400),
a missing library root (503), and session-auth enforcement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.dependencies import get_config
from nomarr.interfaces.api.web.fs_if import router as fs_router

if TYPE_CHECKING:
    from collections.abc import Iterator

    from _pytest.tmpdir import TempPathFactory


@pytest.fixture
def config() -> dict[str, object]:
    """Shared mutable config store injected through the ``get_config`` dependency."""
    return {}


@pytest.fixture
def app(config: dict[str, object]) -> Iterator[FastAPI]:
    """Build a minimal FastAPI app whose library root is driven by the shared config."""

    async def allow_session() -> None:
        return None

    async def override_config() -> dict[str, object]:
        return config

    test_app = FastAPI()
    test_app.include_router(fs_router, prefix="/api/web")

    test_app.dependency_overrides[verify_session] = allow_session
    test_app.dependency_overrides[get_config] = override_config

    yield test_app

    test_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Create a TestClient for the minimal app."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.unit
@pytest.mark.mocked
class TestFileSystemList:
    """Tests for ``GET /file-system/list``."""

    def test_lists_root_directory_entries(
        self,
        client: TestClient,
        config: dict[str, object],
        tmp_path_factory: TempPathFactory,
    ) -> None:
        """The root listing projects ``{path, entries:[{name,is_dir}]}`` sorted dir-first."""
        library_root = tmp_path_factory.mktemp("fs-root-entries")
        (library_root / "Album A").mkdir()
        (library_root / "song.flac").touch()
        (library_root / "album-b").mkdir()
        config["library_root"] = str(library_root)

        response = client.get("/api/web/file-system/list")

        assert response.status_code == 200
        payload = response.json()
        assert payload["path"] == ""
        # Dirs sort before files, each by lowercase name.
        assert payload["entries"] == [
            {"name": "Album A", "is_dir": True},
            {"name": "album-b", "is_dir": True},
            {"name": "song.flac", "is_dir": False},
        ]

    def test_lists_subdirectory_entries_with_relative_path(
        self,
        client: TestClient,
        config: dict[str, object],
        tmp_path_factory: TempPathFactory,
    ) -> None:
        """A subdirectory listing returns the child entries and its relative path."""
        library_root = tmp_path_factory.mktemp("fs-root-sub")
        album = library_root / "album"
        album.mkdir()
        (album / "track.flac").touch()
        (album / "artwork.jpg").touch()
        config["library_root"] = str(library_root)

        response = client.get("/api/web/file-system/list", params={"path": "album"})

        assert response.status_code == 200
        payload = response.json()
        assert payload["path"] == "album"
        assert {entry["name"] for entry in payload["entries"]} == {"track.flac", "artwork.jpg"}

    def test_returns_503_when_library_root_not_configured(self, client: TestClient) -> None:
        """A missing ``library_root`` should surface as HTTP 503."""
        response = client.get("/api/web/file-system/list")

        assert response.status_code == 503
        assert "not configured" in response.json()["detail"]

    def test_rejects_path_traversal(
        self,
        client: TestClient,
        config: dict[str, object],
        tmp_path_factory: TempPathFactory,
    ) -> None:
        """A traversal path should be rejected with HTTP 400."""
        config["library_root"] = str(tmp_path_factory.mktemp("fs-root-traversal"))

        response = client.get("/api/web/file-system/list", params={"path": "../outside"})

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid path: directory traversal not allowed"

    def test_requires_session_auth_without_override(self, tmp_path_factory: TempPathFactory) -> None:
        """The endpoint must reject an unauthenticated request with 401."""
        library_root = tmp_path_factory.mktemp("fs-root-auth")

        async def override_config() -> dict[str, object]:
            return {"library_root": str(library_root)}

        test_app = FastAPI()
        test_app.include_router(fs_router, prefix="/api/web")
        test_app.dependency_overrides[get_config] = override_config

        with TestClient(test_app) as test_client:
            response = test_client.get("/api/web/file-system/list")

        assert response.status_code == 401
        assert response.json() == {"detail": "Missing Authorization header"}
