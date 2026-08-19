"""App-state domain dataclasses.

This module defines ADR-041 domain objects for the ``meta`` and ``locks``
KV tables, produced by the ``AppDb`` persistence facade:

- ConfigOption: A single ``meta`` row (keyed by ``key``).
- LockEntry: A single ``locks`` row (keyed by ``key``).

These are domain-shaped: they carry a natural ``key`` and the JSONB payload as
``value``, and have no knowledge of storage shapes, column names, or the DB
row. The persistence facade owns the DB-row → domain-object mapping per
ADR-041 ("Repos or persistence mapper modules own the DB row → domain
dataclass mapping, facade mediates").

``value`` is intentionally typed ``Any`` because meta/lock payloads are
heterogeneous by design (dicts for config/calibration keys, bare strings for
``ml_model_vram:*`` keys, ints/Nones in test fixtures). No ``__post_init__``
validation: the DB boundary guarantees ``key: str`` and payload heterogeneity
is a first-class contract.

Usage:
    from nomarr.helpers.dataclasses.app_dataclasses import ConfigOption, LockEntry
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


@dataclass(frozen=True, slots=True)
class ConfigOption:
    """Single ``meta`` KV entry, keyed by ``key``.

    ADR-041 domain object mapped by the ``AppDb`` persistence facade from the
    storage ``MetaRow`` shape. Natural key is ``key``; ``value`` is the JSONB
    payload.
    """

    key: str
    value: Any


@dataclass(frozen=True, slots=True)
class LockEntry:
    """Single ``locks`` KV entry, keyed by ``key``.

    ADR-041 domain object mapped by the ``AppDb`` persistence facade from the
    storage ``LockRow`` shape. Natural key is ``key``; ``value`` is the JSONB
    payload.
    """

    key: str
    value: Any


__all__ = ["ConfigOption", "LockEntry"]
