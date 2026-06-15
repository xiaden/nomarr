from __future__ import annotations

import re
from typing import Any

Document = dict[str, Any]

_FIELD_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.]*$")
_ARANGO_SYSTEM_FIELDS = frozenset({"_from", "_to", "_key", "_id", "_rev"})


def _extract_key(document_id_or_key: str) -> str:
    return document_id_or_key.split("/", 1)[1] if "/" in document_id_or_key else document_id_or_key


def _as_document_id(collection: str, document_id_or_key: str) -> str:
    return document_id_or_key if "/" in document_id_or_key else f"{collection}/{document_id_or_key}"


def _validate_field_name(field_name: str) -> None:
    if field_name in _ARANGO_SYSTEM_FIELDS:
        return
    if not field_name or field_name.startswith(("_", ".")) or _FIELD_NAME_PATTERN.fullmatch(field_name) is None:
        msg = f"Invalid field name for AQL interpolation: {field_name!r}"
        raise ValueError(msg)
