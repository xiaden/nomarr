"""Library-layer mapper: row-shaped tag inputs to the library ``FileTag`` contract.

Ownership (per artifacts/designs/parts/tag-boundary/CONTRACTS.md):
- The library owns ``FileTag`` (key/value/tag_type/is_nomarr). It is a
  library/API contract, NOT a domain or persistence representation — it carries
  no persistence identifiers, namespace provenance beyond the ``is_nomarr``
  flag, confidence, or storage timestamps.
- This module is the single place that maps row-shaped ``TagRow``-like inputs
  from the persistence facade into the library ``FileTag`` contract. Both song
  tag query paths (``song_tags_comp`` and ``library_song_query_comp``) use it so
  their projections cannot drift.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.library_dto import FileTag

if TYPE_CHECKING:
    from collections.abc import Mapping


def is_numeric_tag_value(value: Any) -> bool:
    """Return True for numeric (int/float, non-bool) tag values.

    Booleans are treated as strings, matching the existing numeric/string type
    classification used across the library tag projection paths.
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def file_tag_from_tag_row(row: Mapping[str, Any]) -> FileTag:
    """Map a row-shaped tag input into a library ``FileTag``.

    Args:
        row: A ``TagRow``-like mapping with a string ``name`` key and a
            ``value`` key; ``namespace`` is optional and ``== "nom"`` marks a
            Nomarr-namespaced tag.

    Raises:
        ValueError: If the row has no string ``name`` key.

    Returns:
        A ``FileTag`` with ``value`` coerced to ``str`` and ``tag_type`` set to
        ``"float"`` for numeric non-bool values and ``"string"`` otherwise.
    """
    name = row.get("name")
    if not isinstance(name, str):
        raise ValueError(f"tag row missing a string 'name' key: {row!r}")
    value = row.get("value")
    return FileTag(
        key=name,
        value=str(value),
        tag_type="float" if is_numeric_tag_value(value) else "string",
        is_nomarr=row.get("namespace") == "nom",
    )
