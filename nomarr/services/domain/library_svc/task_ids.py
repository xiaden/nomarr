"""Deterministic natural-name task keys for library managed tasks.

Mechanism-A (CONTRACTS.md): the sole library wire identity is the URL-encoded
natural ``Library.name``. Managed scan/write tasks use one shared key operation
so start/cancel/status/workflow all resolve the same task id from the same
``Library`` value, and task lookup/cancellation never parses or reconstructs a
generated library id.

This module is a leaf (it imports no sibling ``library_svc`` modules) so the
workflow and interface layers (P4-S6 / P4-S8) can import ``library_task_id``
without triggering the ``library_svc`` package ``__init__``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import quote

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_dataclass import Library

__all__ = ["library_task_id"]

_PREFIX = "library"
_DELIMITER = "-"


def library_task_id(library: Library, operation: str) -> str:
    """Return a deterministic, collision-safe task key for a library operation.

    The natural ``Library.name`` is UTF-8 URL-quoted with no safe characters
    (``quote(name, safe="")``) so names containing spaces, slashes, Unicode, or
    percent signs round-trip unambiguously. The same ``(library, operation)``
    always yields the same key across start/cancel/status and workflow
    propagation.

    Args:
        library: Domain ``Library`` (natural identity) the task operates on.
        operation: Stable operation token shared by the matching
            start/cancel/status calls and the workflow's own task key
            (e.g. ``"scan"``).

    Returns:
        The task key string.
    """
    encoded_name = quote(library.name, safe="")
    return f"{_PREFIX}{_DELIMITER}{operation}{_DELIMITER}{encoded_name}"
