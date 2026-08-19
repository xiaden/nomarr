"""Tag dataclasses used across Nomarr.

This module defines:
- TagValue: Type alias for scalar tag values (str | int | float | bool)
- Tag: Single tag entry (one name, tuple of values)
- Tags: Collection of Tag objects, sorted by name

Usage:
    from nomarr.helpers.dataclasses.tags_dataclass import Tag, Tags, TagValue
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from typing import Any

TagValue = str | int | float | bool


@dataclass(frozen=True, slots=True)
class Tag:
    """Single music-file tag entry.

    A tag has one name and one or more values.

    Nomarr always stores values as a non-empty tuple, even when the source file
    provided only one value. This removes scalar/list branching while preserving
    the fact that many music tags are naturally multi-valued.
    """

    name: str
    values: tuple[TagValue, ...]

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Tag.name must not be empty")
        if not self.name.strip():
            raise ValueError("Tag.name must not be blank")
        if self.values is None or isinstance(self.values, str | int | float | bool | bytes | bytearray):
            raise TypeError("Tag.values must be a non-scalar iterable of TagValue")
        values = tuple(self.values)
        if not values:
            raise ValueError("Tag.values must contain at least one value")
        for value in values:
            if not isinstance(value, str | int | float | bool):
                raise TypeError(f"Invalid TagValue type: {type(value).__name__}")
        object.__setattr__(self, "values", values)


@dataclass(frozen=True, slots=True)
class Tags:
    """Canonical non-empty collection of Tag objects.

    Input tags are canonicalized during construction:
    - duplicate tag names are merged
    - duplicate values are removed per name
    - tags are sorted by name for deterministic behavior
    An empty tag collection is invalid in Nomarr. Use None to represent unloaded,
    unreadable, or missing tags.
    Frozen for immutability - create new Tags instead of mutating.
    """

    items: tuple[Tag, ...]

    def __post_init__(self) -> None:
        """Validate, merge duplicate names, dedupe values, then sort by name."""
        items = tuple(self.items)
        if not items:
            raise ValueError("Tags.items must contain at least one tag")

        grouped: dict[str, list[TagValue]] = {}
        seen_by_name: dict[str, set[tuple[type, TagValue]]] = {}

        for tag in items:
            if not isinstance(tag, Tag):
                raise TypeError(f"Tags.items must contain Tag objects, got {type(tag).__name__}")
            grouped.setdefault(tag.name, [])
            seen_by_name.setdefault(tag.name, set())

            for value in tag.values:
                # Include type so True, 1, and 1.0 do not collapse through Python equality.
                dedupe_key = (type(value), value)
                if dedupe_key not in seen_by_name[tag.name]:
                    grouped[tag.name].append(value)
                    seen_by_name[tag.name].add(dedupe_key)

        canonical_items = tuple(
            Tag(name=name, values=tuple(values))
            for name, values in sorted(grouped.items(), key=lambda item: (item[0].casefold(), item[0]))
        )

        object.__setattr__(self, "items", canonical_items)

    def __len__(self) -> int:
        """Return number of tags."""
        return len(self.items)

    def __iter__(self) -> Iterator[Tag]:
        """Allow iteration over tags."""
        return iter(self.items)

    def __getitem__(self, index: int) -> Tag:
        """Allow indexing."""
        return self.items[index]

    def has_name(self, name: str) -> bool:
        """Check if a name exists in tags."""
        return any(tag.name == name for tag in self.items)

    def get_values(self, name: str) -> tuple[TagValue, ...]:
        """Get values for a name, raises KeyError if name not found."""
        for tag in self.items:
            if tag.name == name:
                return tag.values
        raise KeyError(f"Tag name not found: {name}")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Tags:
        """Create Tags from a dict of ``name -> value(s)`` mappings.

        Scalar values are normalized to single-element tuples; list/tuple values
        are converted to tuples as-is. Non-TagValue elements are rejected by the
        per-value type check in ``Tag.__post_init__``. An empty dict raises
        ValueError because an empty Tags collection is invalid.
        """
        items: list[Tag] = []
        for name, value in data.items():
            if isinstance(value, list | tuple):
                items.append(Tag(name=name, values=tuple(value)))
            else:
                items.append(Tag(name=name, values=(value,)))
        return cls(items=tuple(items))

    def to_dict(self) -> dict[str, tuple[TagValue, ...]]:
        """Convert to dict, mapping each tag name to its values tuple."""
        return {tag.name: tag.values for tag in self.items}
