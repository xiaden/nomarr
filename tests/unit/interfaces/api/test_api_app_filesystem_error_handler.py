"""RED tests for the minimal central ``FilesystemError`` app handler (D-B10).

The handler is the only place a structured ``FsFact`` crosses the HTTP boundary. It must
map each kind to a safe status, and its response body must be generic — the exception
message, path, errno, and fact detail are never echoed to the client.
"""

from __future__ import annotations

import asyncio
import errno
import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from nomarr.helpers.exceptions import FilesystemError
from nomarr.helpers.fs_contract import FsErrorKind, FsFact
from nomarr.interfaces.api.api_app import api_app

pytestmark = [pytest.mark.unit]


def _handler() -> Any:
    """Return the registered ``FilesystemError`` handler or fail RED."""
    handler = api_app.exception_handlers.get(FilesystemError)
    if handler is None:
        pytest.fail("api_app has no registered FilesystemError exception handler")
    return handler


def _fact(kind: FsErrorKind) -> FsFact:
    if kind == "resource_missing":
        return FsFact(presence="absent", kind="resource_missing", errno=None)
    return FsFact(presence="unknown", kind=kind, errno=None)


_KIND_STATUS: list[tuple[FsErrorKind, int]] = [
    ("resource_missing", 404),
    ("unconfirmed_missing", 503),
    ("permission_denied", 403),
    ("storage_unavailable", 503),
    ("transient_io", 503),
    ("storage_full", 507),
    ("read_only_fs", 403),
    ("invalid_path", 400),
    ("wrong_resource_type", 400),
    ("unknown", 500),
]


def test_filesystem_error_handler_is_registered_for_filesystem_error() -> None:
    """The app must register a handler for the typed contract error."""
    assert _handler() is not None


@pytest.mark.parametrize(
    ("kind", "expected_status"),
    _KIND_STATUS,
    ids=[kind for kind, _ in _KIND_STATUS],
)
def test_filesystem_error_handler_maps_each_kind_to_safe_status(kind: FsErrorKind, expected_status: int) -> None:
    """Every taxonomy kind maps to its documented safe HTTP status."""
    handler = _handler()
    exc = FilesystemError("generic message", fact=_fact(kind))

    response = asyncio.run(handler(MagicMock(), exc))

    assert response.status_code == expected_status
    body = json.loads(response.body)
    assert isinstance(body, dict)
    assert str(exc) not in response.body.decode()


def test_filesystem_error_handler_message_is_generic_and_omits_fact_details() -> None:
    """The client body never carries the message, path, errno, or fact detail."""
    handler = _handler()
    fact = FsFact(
        presence="unknown",
        kind="permission_denied",
        errno=errno.EACCES,
        detail="/secret/library/root: denied",
    )
    exc = FilesystemError("boom /secret/library/root", fact=fact)

    response = asyncio.run(handler(MagicMock(), exc))
    body = response.body.decode()

    assert "/secret/library/root" not in body
    assert "denied" not in body
    assert "boom" not in body
    assert str(errno.EACCES) not in body
