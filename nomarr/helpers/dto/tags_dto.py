"""Tag DTOs - generic tag containers with one invariant: values are always lists.

This module defines:
- TagValue: Type alias for scalar tag values (str | int | float | bool)
- Tag: Single tag entry (one key, list of values)
- Tags: Collection of Tag objects, sorted by key

Usage:
    from nomarr.helpers.dto.tags_dto import Tag, Tags, TagValue

    # Create from dict
    tags = Tags.from_dict({"artist": "Beatles", "genre": ["rock", "pop"]})

    # Create from DB rows
    tags = Tags.from_db_rows(db.tags.get_song_tags(file_id))

    # Convert back
    tag_dict = tags.to_dict()
    for key, values in tags.to_db_rows():
        db.tags.set_song_tags(file_id, key, values)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Scalar tag value types (matches DB and file layer)
# This is the canonical definition - persistence layer should import from here
TagValue = str | int | float | bool


@dataclass(frozen=True)
class Tag:
    """Single tag entry: one key, N values (N >= 0).

    Invariant: value is ALWAYS a tuple, even for single values.
    This eliminates scalar/list branching throughout the codebase.
    Frozen for immutability.
    """

    key: str  # e.g., "artist", "nom:mood-tier-1", "album"
    value: tuple[TagValue, ...]  # Always tuple, never scalar


@dataclass(frozen=True)
class Tags:
    """Collection of tags, sorted by key for deterministic output.

    One class, one invariant, one affordance (key sort).
    No filtering, no grouping, no business logic.
    Frozen for immutability - create new Tags instead of mutating.

    Same shape everywhere:
    - DB → Tags
    - Files → Tags
    - Workflows → Tags
    - API → Tags
    """

    items: tuple[Tag, ...]

    def __post_init__(self) -> None:
        """Sort by key for deterministic output."""
        sorted_items = tuple(sorted(self.items, key=lambda tag: tag.key))
        object.__setattr__(self, "items", sorted_items)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Tags:
        """Create Tags from dict (common workflow format).

        Normalizes scalars to tuples automatically.
        """
        items: list[Tag] = []
        for key, value in data.items():
            # Normalize to tuple
            if isinstance(value, list | tuple):
                items.append(Tag(key=key, value=tuple(value)))
            else:
                items.append(Tag(key=key, value=(value,)))
        return cls(items=tuple(items))

    @classmethod
    def from_db_rows(cls, db_rows: list[dict[str, Any]]) -> Tags:
        """Create Tags from DB query results.

        Aggregates multiple rows with same key into single Tag.

        Args:
            db_rows: List of {rel, value} dicts from get_song_tags()

        """
        # Group by key
        aggregated: dict[str, list[TagValue]] = {}
        for row in db_rows:
            key = row["rel"]
            value = row["value"]
            if key not in aggregated:
                aggregated[key] = []
            aggregated[key].append(value)

        # Convert to Tag objects with tuple values
        items = [Tag(key=key, value=tuple(values)) for key, values in aggregated.items()]
        return cls(items=tuple(items))

    def to_dict(self) -> dict[str, tuple[TagValue, ...]]:
        """Convert to dict.

        Returns always-tuple format (consumers handle single-value ergonomics).
        """
        return {tag.key: tag.value for tag in self.items}

    def to_db_rows(self) -> list[tuple[str, tuple[TagValue, ...]]]:
        """Convert to DB write format.

        Returns:
            List of (key, values) tuples for db.tags.set_song_tags()

        """
        return [(tag.key, tag.value) for tag in self.items]

    def __len__(self) -> int:
        """Return number of tags."""
        return len(self.items)

    def __iter__(self):
        """Allow iteration over tags."""
        return iter(self.items)

    def __getitem__(self, index: int) -> Tag:
        """Allow indexing."""
        return self.items[index]

    def has_key(self, key: str) -> bool:
        """Check if a key exists in tags."""
        return any(tag.key == key for tag in self.items)

    def get_values(self, key: str) -> tuple[TagValue, ...]:
        """Get values for a key, or empty tuple if key not found."""
        for tag in self.items:
            if tag.key == key:
                return tag.value
        return ()

    def has_value(self, value: TagValue) -> bool:
        """Check if a value exists in any tag."""
        return any(value in tag.value for tag in self.items)
