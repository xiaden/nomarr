from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable, Coroutine, Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nomarr.interfaces.api.auth import verify_session
from nomarr.interfaces.api.web.admin_if import router as admin_router


@pytest.fixture
def app() -> Iterator[FastAPI]:
    test_app = FastAPI()
    test_app.include_router(admin_router, prefix="/api")

    async def allow_session() -> None:
        return None

    test_app.dependency_overrides[verify_session] = allow_session

    yield test_app

    test_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.integration
@pytest.mark.mocked
class TestWebAdminRestartEndpoint:
    def test_returns_success_response(self, client: TestClient) -> None:
        class FakeTask:
            def __init__(self) -> None:
                self.callbacks: list[Callable[[FakeTask], object]] = []

            def add_done_callback(self, callback: Callable[[FakeTask], object]) -> None:
                self.callbacks.append(callback)

        def fake_create_task(coro: Coroutine[Any, Any, None]) -> FakeTask:
            coro.close()
            return FakeTask()

        with (
            patch(
                "nomarr.interfaces.api.web.admin_if.asyncio.create_task",
                side_effect=fake_create_task,
            ) as mock_create_task,
            patch("nomarr.interfaces.api.web.admin_if.os.execv") as mock_execv,
        ):
            response = client.post("/api/admin/restart")

        assert response.status_code == 200
        assert response.json() == {
            "status": "success",
            "message": "API server is restarting... Please refresh the page in a few seconds.",
        }
        mock_create_task.assert_called_once()
        mock_execv.assert_not_called()

    def test_do_restart_calls_stop_before_execv(self, client: TestClient) -> None:
        class FakeTask:
            def __init__(self) -> None:
                self.callbacks: list[Callable[[FakeTask], object]] = []

            def add_done_callback(self, callback: Callable[[FakeTask], object]) -> None:
                self.callbacks.append(callback)

        captured_coro: Coroutine[Any, Any, None] | None = None
        call_order: list[str] = []

        def fake_create_task(coro: Coroutine[Any, Any, None]) -> FakeTask:
            nonlocal captured_coro
            captured_coro = coro
            return FakeTask()

        def fake_execv(*_args: object) -> None:
            call_order.append("execv")
            raise SystemExit(0)

        with (
            patch(
                "nomarr.interfaces.api.web.admin_if.asyncio.create_task",
                side_effect=fake_create_task,
            ) as mock_create_task,
            patch(
                "nomarr.interfaces.api.web.admin_if.asyncio.sleep",
                new_callable=AsyncMock,
            ) as mock_sleep,
            patch("nomarr.app.application") as mock_application,
            patch(
                "nomarr.interfaces.api.web.admin_if.os.execv",
                side_effect=SystemExit(0),
            ) as mock_execv,
        ):
            mock_application.stop.side_effect = lambda: call_order.append("stop")
            mock_execv.side_effect = fake_execv

            response = client.post("/api/admin/restart")

            assert captured_coro is not None
            with pytest.raises(SystemExit):
                asyncio.run(captured_coro)

        assert response.status_code == 200
        assert response.json() == {
            "status": "success",
            "message": "API server is restarting... Please refresh the page in a few seconds.",
        }
        mock_create_task.assert_called_once()
        mock_sleep.assert_awaited_once_with(1)
        mock_application.stop.assert_called_once()
        mock_execv.assert_called_once_with(sys.executable, [sys.executable, *sys.argv])
        assert call_order == ["stop", "execv"]

    def test_requires_session_auth_without_override(self) -> None:
        test_app = FastAPI()
        test_app.include_router(admin_router, prefix="/api")

        with TestClient(test_app) as test_client:
            response = test_client.post("/api/admin/restart")

        assert response.status_code == 401
        assert response.json() == {"detail": "Missing Authorization header"}
