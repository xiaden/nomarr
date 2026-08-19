"""Tag re-exports - canonical strict implementation lives in nomarr.helpers.dataclasses.tags_dataclass.

This module re-exports the canonical strict ``Tag`` / ``Tags`` value objects from
``nomarr.helpers.dataclasses.tags_dataclass`` so legacy importers keep resolving.

- ``Tag(name: str, values: tuple[TagValue, ...])`` - single tag entry
- ``Tags(items: tuple[Tag, ...])`` - non-empty collection, sorted by name (casefold),
  duplicate names merged, duplicate values removed per name

Strict invariants (from the canonical module):
- name must be non-empty and non-blank
- values must be a non-empty tuple of ``TagValue`` (``str | int | float | bool``)
- ``Tags`` must contain at least one ``Tag``; empty Tags/values raise ValueError.
- ``None`` represents the empty/unloaded/missing state, not an empty collection.

Conversion methods: ``from_dict``, ``from_db_rows``, ``to_dict``. Lookup methods:
``has_name`` and ``get_values`` (raises ``KeyError`` on a missing name).

``TagValue`` remains available here for backward compatibility.

Usage:
    from nomarr.helpers.dto.tags_dto import Tag, Tags, TagValue
"""

from nomarr.helpers.dataclasses.tags_dataclass import Tag, Tags, TagValue

__all__ = ["Tag", "TagValue", "Tags"]
