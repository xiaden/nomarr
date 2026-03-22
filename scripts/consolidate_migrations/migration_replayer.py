"""Compatibility shim -- implementation moved to walker/ sub-package."""

from __future__ import annotations

from .walker import MutableSchemaShape, discover_migrations, replay_migrations

__all__ = ["MutableSchemaShape", "discover_migrations", "replay_migrations"]
