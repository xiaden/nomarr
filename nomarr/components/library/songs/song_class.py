"""Persistence-agnostic song domain dataclasses (Q6).

This module holds the `Song` dataclass and its supporting `Tag`/`Vector`
value objects. Per Q6 resolution, the dataclass carries **no** persistence-
owned fields: the legacy ArangoDB-era `DBkey` and `DBid` fields were removed.
`Song` exposes only domain-level attributes (`name`, `path`, `tags`,
`embeddings`); storage identity (database primary key, ArangoDB doc-id/key)
is an implementation detail owned by the persistence layer and does not
leak into the domain dataclass.

Note: this module has zero consumers in active runtime code. Whether it
survives as the canonical Song domain dataclass or is removed entirely is a
Plan F decision (it is a documented deletion candidate if it stays dead).
"""

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
    """Base song dataclass (persistence-agnostic).

    Carries only domain-level song attributes. The legacy persistence-owned
    `DBkey`/`DBid` fields were removed (Q6) — storage identity is owned by
    the persistence layer, not this dataclass.
    """

    name: str | None = None
    path: str | None = None
    tags: list[Tag] | None = None
    embeddings: list[Vector] | None = None
