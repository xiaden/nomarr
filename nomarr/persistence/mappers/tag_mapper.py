"""Persistence-layer mappers that convert storage rows to domain value objects.

Ownership (per artifacts/designs/parts/tag-boundary/CONTRACTS.md):
- ``nomarr/helpers/dataclasses/tags_dataclass.py`` is the canonical domain
  ``Tag``/``Tags``; it carries no database-row API or persistence fields.
- This module lives in the persistence layer and owns the row-to-domain and
  domain-to-write-payload conversions. It imports helpers DTOs/dataclasses
  only — never components, services, workflows, or interfaces.

See ADR-041 (domain dataclasses as the persistence-component contract):
persistence-owned fields stay inside persistence; components work with
natural-key value objects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.helpers.dataclasses.tags_dataclass import Tag, Tags, TagValue

if TYPE_CHECKING:
    from collections.abc import Iterable


def tags_from_tag_rows(rows: Iterable[dict[str, Any]]) -> Tags:
    """Group row-shaped tag inputs into a canonical domain ``Tags`` value object.

    Each input row is either a ``TagRow``-shaped dict (name/value, possibly
    with persistence-only keys) or a minimal ``{name, value}`` dict. Only the
    ``name`` and ``value`` keys are mapped into the domain — identifiers,
    namespace, provenance, confidence, tier, and timestamps are left out.

    Rows are grouped by ``name`` preserving per-name value order. An empty
    ``rows`` iterable yields an empty ``Tags``, which raises the canonical
    ``ValueError`` (empty ``Tags`` is invalid).
    """
    aggregated: dict[str, list[TagValue]] = {}
    for row in rows:
        name = row["name"]
        aggregated.setdefault(name, []).append(row["value"])
    items = tuple(Tag(name=name, values=tuple(values)) for name, values in aggregated.items())
    return Tags(items=items)


def tag_rows_from_tags(
    tags: Tags,
    *,
    namespace: str,
    source: str,
) -> list[dict[str, Any]]:
    """Convert canonical domain ``Tags`` into persistence write-payload rows.

    Returns one row per tag value, shaped ``{"name", "value", "namespace",
    "source"}`` — the shape consumed by ``get_or_create_tags_batch`` writers.
    ``namespace`` and ``source`` are supplied by the caller because they are
    persistence concerns, not carried on the domain object.
    """
    return [
        {"name": tag.name, "value": value, "namespace": namespace, "source": source}
        for tag in tags.items
        for value in tag.values
    ]
