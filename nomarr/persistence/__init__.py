"""Persistence package."""

from __future__ import annotations

from typing import Any

__all__ = ["Database", "DuplicateKeyError"]


def __getattr__(name: str) -> Any:
    if name == "Database":
        from .db import Database

        return Database
    if name == "DuplicateKeyError":
        from .exceptions import DuplicateKeyError

        return DuplicateKeyError
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
