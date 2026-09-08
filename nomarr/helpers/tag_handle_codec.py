"""Opaque complete-``TagRef`` wire-handle codec for tag curation.

Wire-handle contract (``artifacts/designs/parts/tag-curation-identity-mismatch/CONTRACTS.md``):

- A public tag identity handle is a versioned, canonical, URL-safe base64url
  encoding of a canonical JSON object containing exactly the semantic ``name``,
  ``value``, and ``namespace`` fields. It is deterministic and unambiguous.
- It contains **no storage primary key** and never reuses the integer
  ``id_codec`` functions (PostgreSQL tag PKs are persistence-private and never
  cross the service/interface/frontend boundary).
- The handle preserves JSON value types: a numeric-looking value such as
  ``120`` stays a number or string exactly as given and is never parsed into a
  storage-ID selector; a string value such as ``Electronic`` is likewise never
  parsed as an integer.
- Ordinary tags use the literal namespace ``default``; ``nom`` remains distinct
  and is preserved verbatim.

This module lives in the ``helpers`` layer, strictly below the HTTP boundary: it
imports no FastAPI/Pydantic and raises :class:`TagHandleError` (a ``ValueError``)
so the interface layer can map malformed handles onto its existing 400/404
policy without leaking persistence errors. It is importable by the interface
(``tag_curation_if``) and the DTO layer without importing either.

Canonical form
--------------
The payload is produced by :func:`json.dumps` with ``sort_keys=True``,
``separators=(",", ":")``, ``ensure_ascii=True`` and ``allow_nan=False``, then
UTF-8 bytes URL-safe base64 encoded (RFC 4648 §5, with padding). Decoding
re-serialises the parsed, ``TagRef``-normalised object canonically and requires
it to byte-equal the original payload, which deterministically rejects
non-canonical key order, extra/missing/duplicate keys, non-minimal whitespace,
non-ASCII escaping, and non-canonical numeric spellings.

Value typing
------------
``name`` and ``namespace`` are JSON strings; ``value`` is a native JSON value
(preserving JSON types). ``TagRef.value`` is ``object | None`` restricted in
practice to scalar tag values. Number semantics follow Python's ``json``:
integer spellings decode to ``int`` and float spellings (decimal point or
exponent) decode to ``float``. Because our encoder distinguishes ``120``
(int), ``120.0`` (float), ``"120"`` (string), ``true`` (bool) and ``null``
(None) textually, every supported scalar round-trips exactly and
unambiguously.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from typing import Any

from nomarr.helpers.dataclasses.song_tag_dataclass import TagRef

__all__ = ["TagHandleError", "decode_tag_handle", "encode_tag_handle"]

# Versioned handle prefix. Bump the trailing integer for any future incompatible
# wire-format change; decode rejects handles whose prefix is not the supported one.
_TAG_HANDLE_PREFIX = "t1."

# URL-safe base64url alphabet (RFC 4648 §5) plus canonical ``=`` padding. Reject
# ``+``/``/`` (standard-base64) and any whitespace so only the canonical alphabet
# reaches the decoder; byte-equality then guarantees the exact canonical form.
_BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")

# Upper bound on the decoded canonical JSON payload (bytes). Tag identities are
# short; anything larger is treated as an oversized/malformed handle rather than
# a legitimate tag. Guards against base64/JSON blowups at the HTTP boundary.
_MAX_PAYLOAD_BYTES = 2048


class TagHandleError(ValueError):
    """Raised when a tag wire handle cannot be encoded or decoded.

    Subclasses ``ValueError`` so the interface layer can map it onto the
    endpoint-specific 400 policy without importing this module's internals.
    """


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    """Deterministic canonical JSON bytes (sorted keys, minimal, ASCII-only)."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _object_from_handle(handle: str) -> tuple[bytes, dict[str, Any]]:
    """Split/validate the version prefix and return ``(payload_bytes, obj)``.

    Raises :class:`TagHandleError` on any structural malformation (version,
    base64, JSON, missing/extra identity fields, oversized payload) *before* the
    ``TagRef``-level canonicality check runs.
    """
    if not isinstance(handle, str):
        raise TagHandleError("tag handle must be a string")
    if not handle.startswith(_TAG_HANDLE_PREFIX):
        raise TagHandleError(f"unsupported or missing tag handle version; expected prefix {_TAG_HANDLE_PREFIX!r}")
    encoded = handle[len(_TAG_HANDLE_PREFIX) :]
    if not encoded:
        raise TagHandleError("tag handle payload is empty")
    if not _BASE64URL_RE.fullmatch(encoded):
        raise TagHandleError("tag handle payload is not valid URL-safe base64")
    try:
        payload = base64.b64decode(encoded.encode("ascii"), altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise TagHandleError("tag handle payload is not valid base64") from exc
    if len(payload) > _MAX_PAYLOAD_BYTES:
        raise TagHandleError("tag handle payload is oversized")
    try:
        obj = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise TagHandleError("tag handle payload is not valid JSON") from exc
    if not isinstance(obj, dict):
        raise TagHandleError("tag handle payload must be a JSON object")
    if set(obj) != {"name", "namespace", "value"}:
        missing = {"name", "namespace", "value"} - set(obj)
        extra = set(obj) - {"name", "namespace", "value"}
        details: list[str] = []
        if missing:
            details.append(f"missing field(s): {', '.join(sorted(missing))}")
        if extra:
            details.append(f"unexpected field(s): {', '.join(sorted(extra))}")
        raise TagHandleError("tag handle must carry exactly name, value, namespace — " + "; ".join(details))
    return payload, obj


def decode_tag_handle(handle: str) -> TagRef:
    """Decode an opaque ``t1.`` tag wire handle into its complete ``TagRef``.

    Rejects unsupported versions, missing/extra identity fields, invalid
    base64/JSON, blank names, invalid/blank namespaces, oversized payloads, and
    non-canonical encodings. Never returns a storage primary key.
    """
    payload, obj = _object_from_handle(handle)
    name = obj["name"]
    namespace = obj["namespace"]
    value = obj["value"]
    if not isinstance(name, str):
        raise TagHandleError("tag handle 'name' must be a string")
    if not isinstance(namespace, str):
        raise TagHandleError("tag handle 'namespace' must be a string")
    try:
        identity = TagRef(name=name, value=value, namespace=namespace)
    except (TypeError, ValueError) as exc:
        # Blank name or invalid namespace surfaced through the value object's
        # own validation, mapped to the codec's contract error.
        raise TagHandleError(f"invalid tag identity in handle: {exc}") from exc
    # Canonicality gate: re-serialise the TagRef-normalised identity canonically
    # and require byte equality with the original payload. This rejects blank
    # namespaces (normalised to 'default'), non-canonical key order/whitespace,
    # duplicate keys, and non-canonical numeric/string spellings in one step.
    canonical = _canonical_bytes(
        {
            "name": identity.name,
            "namespace": identity.namespace,
            "value": identity.value,
        }
    )
    if canonical != payload:
        raise TagHandleError("tag handle is not in canonical form")
    return identity


def encode_tag_handle(identity: TagRef) -> str:
    """Encode a complete ``TagRef`` into an opaque, canonical ``t1.`` handle.

    Round-trips ``name``, ``value`` and ``namespace`` exactly, preserves JSON
    value types, and contains no storage primary key.
    """
    if not isinstance(identity, TagRef):
        raise TagHandleError("encode_tag_handle requires a TagRef")
    try:
        payload = _canonical_bytes(
            {
                "name": identity.name,
                "namespace": identity.namespace,
                "value": identity.value,
            }
        )
    except (TypeError, ValueError) as exc:
        raise TagHandleError(
            f"tag value for {identity.name!r} is not JSON-serialisable or is non-finite: {exc}"
        ) from exc
    if len(payload) > _MAX_PAYLOAD_BYTES:
        raise TagHandleError("tag handle payload is oversized")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii")
    return f"{_TAG_HANDLE_PREFIX}{encoded}"
