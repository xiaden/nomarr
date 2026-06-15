from __future__ import annotations

from typing import Any

Document = dict[str, Any]
_NO_LIMIT_COUNT = 2_147_483_647


def _extract_key(document_id_or_key: str) -> str:
    return document_id_or_key.split("/", 1)[1] if "/" in document_id_or_key else document_id_or_key


def _as_document_id(collection: str, document_id_or_key: str) -> str:
    return document_id_or_key if "/" in document_id_or_key else f"{collection}/{document_id_or_key}"
