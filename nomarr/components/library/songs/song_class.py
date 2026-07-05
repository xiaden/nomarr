from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Tag:
    """Base tag dataclass."""

    name: str
    value: str


@dataclass
class Vector:
    """Singular Vector dataclass."""

    self: list[float]


@dataclass
class Song:
    """Base song dataclass."""

    name: str | None = None
    DBkey: str | None = None
    DBid: str | None = None
    path: str | None = None
    tags: list[Tag] | None = None
    embeddings: list[Vector] | None = None
