"""HTTP-facing codec adapters for the opaque SongLocator token.

The pre-production hard cut removed ordinary integer ``file_id``/``song_id`` wire
values. A song/file is addressed on the wire only by the opaque ``nom1``
SongLocator token defined in :mod:`nomarr.helpers.song_locator_codec`:

    ``nom1`` + unpadded URL-safe base64 of canonical compact JSON
    ``{"library_uuid": <concrete libraries.library_uuid>, "path": <relative>}``

This module re-exports those pure primitives (so interfaces, services, and
components all share one canonical implementation) and adds the FastAPI-route
adapter :func:`decode_song_locator_or_400`, which maps a malformed/non-canonical
token to HTTP 400. Route layers then resolve the decoded ``library_uuid`` to a
complete ``LibraryIdentity`` through the owning service/facade (a valid token
whose library/song does not exist is HTTP 404, not 400).

Library natural-name identity (mechanism A): the sole wire identity for a
library *entity route* is the URL-encoded natural ``Library.name``.
``encode_library_name``/``decode_library_name`` quote/unquote it with no safe
characters. This deliberate library-route split is independent of the SongLocator
token, which always carries ``library_uuid``; a natural name is never a Song
identity.
"""

from __future__ import annotations

from urllib.parse import quote, unquote

from fastapi import HTTPException

from nomarr.helpers.song_locator_codec import (
    CANONICAL_UUID4_RE,
    SONG_LOCATOR_MAX_LENGTH,
    SONG_LOCATOR_PREFIX,
    SongLocatorFormatError,
    SongLocatorPayload,
    decode_song_locator,
    encode_song_locator,
)

# Backwards-compatible alias for callers/tests that imported the old error name.
InvalidIdFormatError = SongLocatorFormatError

__all__ = [
    "CANONICAL_UUID4_RE",
    "SONG_LOCATOR_MAX_LENGTH",
    "SONG_LOCATOR_PREFIX",
    "InvalidIdFormatError",
    "SongLocatorFormatError",
    "SongLocatorPayload",
    "decode_library_name",
    "decode_song_locator",
    "decode_song_locator_or_400",
    "encode_library_name",
    "encode_song_locator",
]


def decode_song_locator_or_400(token: str | int) -> SongLocatorPayload:
    """Decode a token, mapping :class:`SongLocatorFormatError` to HTTP 400."""
    try:
        return decode_song_locator(token)
    except SongLocatorFormatError as exc:
        raise HTTPException(status_code=400, detail="Invalid SongLocator token") from exc


def encode_library_name(name: str) -> str:
    """Encode a natural library name for HTTP transport (URL path/query segment).

    Mechanism A (CONTRACTS.md): the sole *library-route* wire identity is the
    URL-encoded natural ``Library.name``. The name is percent-quoted with no safe
    characters (``quote(name, safe="")``) so spaces, slashes, Unicode, percent
    signs, and reserved characters round-trip unambiguously and cannot collide with
    a route separator. This is independent of the SongLocator token, which carries
    ``library_uuid`` and never a natural name.

    Args:
        name: Natural library name.

    Returns:
        URL-encoded natural name.
    """
    return quote(name, safe="")


def decode_library_name(value: str) -> str:
    """Decode a URL-encoded natural library name to its plain-text form.

    Inverse of :func:`encode_library_name`. Pure percent-decoding; it does not
    validate that the library exists. Callers resolve the decoded name to a
    ``Library`` via ``LibraryService.get_library_by_name`` and map a missing
    value to the route's 404/validation error.

    Args:
        value: URL-encoded library name from a path/query/request field.

    Returns:
        The decoded natural library name.
    """
    return unquote(value)
