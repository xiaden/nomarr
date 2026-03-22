"""walker -- AST-based migration replay engine sub-package.

Re-exports the three public symbols used by callers:

- ``discover_migrations`` -- locate V004--V019 migration files.
- ``MutableSchemaShape`` -- mutable working copy of the schema.
- ``replay_migrations`` -- top-level entry point: replay migrations onto a base shape.
"""

from __future__ import annotations

from .discovery import discover_migrations
from .mutators import MutableSchemaShape
from .walker import replay_migrations

__all__ = ["MutableSchemaShape", "discover_migrations", "replay_migrations"]
