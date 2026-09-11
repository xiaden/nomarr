"""Opaque SongLocator wire-token codec (``nom1``).

Wire contract (DD-songlocator-migration.md §4.2, ratified in plan P2-S1):

- Prefix ``nom1`` immediately followed by the **unpadded URL-safe base64**
  (RFC 4648 §5) of the UTF-8 bytes of the **canonical compact JSON** object with
  exactly two keys ``{"library_uuid": <str>, "path": <str>}``.
- ``library_uuid`` is the concrete immutable ``libraries.library_uuid`` value
  (RFC 4122 canonical lowercase hyphenated version-4 textual form) — never the
  generated integer ``libraries.id``, and never a natural library name.
- ``path`` is the library-relative normalized path (canonical POSIX form: no
  leading slash, no backslashes, no ``.``/``..`` segments, no duplicate or
  trailing separators, no ``./`` prefix).

Canonical form is enforced on decode by re-serializing and byte-comparing:
deterministic key ordering, no insignificant whitespace, no alternate JSON
spellings, no base64 padding. Decoding is strict and has no integer fallback.

This module lives in the ``helpers`` layer, strictly below the HTTP boundary: it
imports no FastAPI/Pydantic and raises :class:`SongLocatorFormatError` (a
``ValueError``) so the interface layer can map malformed tokens onto its 400
policy. It is importable by components, services, DTOs, and the interface layer.
The interface-facing :mod:`nomarr.interfaces.api.id_codec` re-exports these
primitives and adds the HTTP-400 adapter.

The ``nom1`` token is the only accepted wire spelling; ordinary integer
``file_id``/``song_id``/``library_id`` values are rejected. A syntactically valid
token whose ``library_uuid`` does not exist is a not-found (HTTP 404) resolved
through the owning service/facade, not a format error.
"""

from __future__ import annotations

import base64
import binascii
import json
import posixpath
import re
import string
from dataclasses import dataclass

# Canonical RFC 4122 version-4 lowercase hyphenated textual UUID, exactly as
# minted by ``str(uuid.uuid4())``. The sole accepted spelling.
CANONICAL_UUID4_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")

SONG_LOCATOR_PREFIX = "nom1"
SONG_LOCATOR_MAX_LENGTH = 8192

_BASE64URL_ALPHABET = frozenset(string.ascii_letters + string.digits + "-_")


class SongLocatorFormatError(ValueError):
    """Raised when a SongLocator token has an invalid or non-canonical format."""


@dataclass(frozen=True, slots=True)
class SongLocatorPayload:
    """Pure decoded SongLocator: concrete ``library_uuid`` plus relative ``path``."""

    library_uuid: str
    path: str


def canonical_song_locator_json(library_uuid: str, path: str) -> str:
    """Serialize the canonical compact JSON payload with deterministic key order."""
    return json.dumps(
        {"library_uuid": library_uuid, "path": path},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def is_canonical_relative_path(path: str) -> bool:
    """Whether ``path`` is the canonical normalized library-relative POSIX path."""
    if not path or path != path.strip():
        return False
    if path.startswith("/") or "\\" in path:
        return False
    if path in {".", ".."}:
        return False
    if posixpath.normpath(path) != path:
        return False
    return not path.startswith("./")


def encode_song_locator(locator: object) -> str:
    """Encode a semantic ``SongIdentity`` locator as an opaque ``nom1`` token.

    Args:
        locator: A ``SongIdentity`` (``SongIdentity(LibraryIdentity, normalized_path)``).

    Returns:
        The opaque ``nom1`` token.

    Raises:
        SongLocatorFormatError: If the locator lacks a canonical UUID or canonical
            relative path, or the token exceeds the acceptance ceiling.

    """
    library = getattr(locator, "library", None)
    library_uuid = getattr(library, "library_uuid", None)
    path = getattr(locator, "normalized_path", None)
    if not isinstance(library_uuid, str) or not CANONICAL_UUID4_RE.match(library_uuid):
        msg = "SongLocator.library_uuid must be a canonical lowercase version-4 UUID"
        raise SongLocatorFormatError(msg)
    if not isinstance(path, str) or not is_canonical_relative_path(path):
        msg = "SongLocator.normalized_path must be a canonical library-relative path"
        raise SongLocatorFormatError(msg)

    encoded = base64.urlsafe_b64encode(canonical_song_locator_json(library_uuid, path).encode("utf-8")).decode("ascii")
    token = SONG_LOCATOR_PREFIX + encoded.rstrip("=")
    if len(token) > SONG_LOCATOR_MAX_LENGTH:
        msg = f"SongLocator token exceeds the {SONG_LOCATOR_MAX_LENGTH}-character acceptance ceiling"
        raise SongLocatorFormatError(msg)
    return token


def decode_song_locator(token: str | int) -> SongLocatorPayload:
    """Strictly decode an opaque ``nom1`` SongLocator token.

    Syntax/canonical validation only — no database access. Existence of the
    ``library_uuid`` is resolved by the owning service/facade.

    Args:
        token: Opaque token from the wire.

    Returns:
        The decoded ``SongLocatorPayload``.

    Raises:
        SongLocatorFormatError: If the token is an integer, an alternate format, a
            malformed/non-canonical/unknown-version token, an invalid UUID
            spelling, a non-normalized path, or over the acceptance ceiling.

    """
    if not isinstance(token, str):
        msg = "SongLocator token must be a string"
        raise SongLocatorFormatError(msg)
    if len(token) > SONG_LOCATOR_MAX_LENGTH:
        msg = f"SongLocator token exceeds the {SONG_LOCATOR_MAX_LENGTH}-character acceptance ceiling"
        raise SongLocatorFormatError(msg)
    if not token.startswith(SONG_LOCATOR_PREFIX):
        msg = "SongLocator token must use the 'nom1' version prefix"
        raise SongLocatorFormatError(msg)

    body = token[len(SONG_LOCATOR_PREFIX) :]
    if not body or any(char not in _BASE64URL_ALPHABET for char in body):
        msg = "SongLocator token has a non-canonical base64url body"
        raise SongLocatorFormatError(msg)
    if "=" in body:
        msg = "SongLocator token must be unpadded"
        raise SongLocatorFormatError(msg)

    try:
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except (binascii.Error, ValueError):
        msg = "SongLocator token has invalid base64url encoding"
        raise SongLocatorFormatError(msg) from None

    if base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != body:
        msg = "SongLocator token has non-canonical base64url encoding"
        raise SongLocatorFormatError(msg)

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        msg = "SongLocator token payload is not valid UTF-8"
        raise SongLocatorFormatError(msg) from None

    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        msg = "SongLocator token payload is not valid JSON"
        raise SongLocatorFormatError(msg) from None

    if not isinstance(obj, dict) or set(obj.keys()) != {"library_uuid", "path"}:
        msg = "SongLocator payload must be an object with exactly {library_uuid, path}"
        raise SongLocatorFormatError(msg)

    library_uuid = obj["library_uuid"]
    path = obj["path"]
    if not isinstance(library_uuid, str) or not CANONICAL_UUID4_RE.match(library_uuid):
        msg = "SongLocator payload library_uuid is not a canonical lowercase version-4 UUID"
        raise SongLocatorFormatError(msg)
    if not isinstance(path, str) or not is_canonical_relative_path(path):
        msg = "SongLocator payload path is not a canonical library-relative path"
        raise SongLocatorFormatError(msg)

    if canonical_song_locator_json(library_uuid, path) != text:
        msg = "SongLocator payload is not canonical compact JSON"
        raise SongLocatorFormatError(msg)

    return SongLocatorPayload(library_uuid=library_uuid, path=path)
