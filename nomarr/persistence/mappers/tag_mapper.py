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

    This is the **documented namespace-free physical-file projection boundary**:
    it maps only ``name``/``value`` into the namespace-free ``Tags`` value
    object (for physical-file/analytics/wire projections) and deliberately drops
    namespace, provenance, confidence, tier, and timestamps. It MUST NOT be used
    to resolve or persist assignments — namespace-bearing identity paths use
    ``TagRef(name, value, namespace)`` via ``song_tag_mapper``, never ``Tags``.

    Each input row is either a ``TagRow``-shaped dict (name/value, possibly
    with persistence-only keys) or a minimal ``{name, value}`` dict. Only the
    ``name`` and ``value`` keys are mapped into the domain.

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
) -> list[dict[str, Any]]:
    """Convert canonical domain ``Tags`` into identity-only persistence payload rows.

    Returns one row per tag value, shaped exactly ``{"name", "value",
    "namespace"}`` — the complete ``(namespace, name, value)`` identity consumed
    by the ``get_or_create_tags_batch`` writer. ``namespace`` is a persistence
    concern supplied by the caller and is normalized: blank/missing ordinary
    input becomes the literal ``default`` while an explicit ``nom`` is
    preserved. This helper NEVER emits ``source`` or any removed tag metadata:
    the storage writer ``get_or_create_tags_batch`` rejects removed-metadata
    keys (see the identity-only storage contract), and assignment confidence /
    source live only on ``song_tags`` edges, never on tag identity rows.
    """
    ns = "default" if not namespace or not namespace.strip() else namespace
    return [{"name": tag.name, "value": value, "namespace": ns} for tag in tags.items for value in tag.values]
