"""Process-local worker context registry for ML model loading.

This module holds a per-process registry of the worker database handle and
worker identity.  It is populated once at worker startup and read by
:class:`~nomarr.components.ml.ml_onnx_base.BaseONNXModel` during
``load()`` and ``unload()`` to drive VRAM promise coordination.

This pattern is intentional and by design for this layer.  Workers are
long-running single-process entities with a single database connection;
passing ``db`` and ``worker_id`` through every call chain into model
objects would contaminate signatures throughout the ML component stack.
The registry solves that without global singletons in the main process:
it is only populated inside the spawned worker process and is never set
in the parent or API process, so there is no cross-process ambiguity.

Note: retrieving from a module-level variable is unconventional in this
codebase and was chosen deliberately for the worker subprocess context.
Do not use this pattern in other layers.
"""

from __future__ import annotations

from typing import Any

# Process-local context: set once at worker startup, never in parent process.
_worker_db: Any = None
_worker_id: str | None = None


def register_worker_context(db: Any, worker_id: str) -> None:
    """Register the database handle and worker identity for this process.

    Must be called once at worker startup before any model ``load()`` calls.
    Calling again overwrites the previous registration (e.g. on reconnect).

    Args:
        db:        Application database handle for this worker process.
        worker_id: Stable worker identifier (e.g. ``"nomarr-tag:0"``).
    """
    global _worker_db, _worker_id
    _worker_db = db
    _worker_id = worker_id


def get_worker_context() -> tuple[Any, str] | None:
    """Return ``(db, worker_id)`` if registered, or ``None``.

    Returns ``None`` in any process where :func:`register_worker_context`
    has not been called — probe processes, tests, the API process, etc.
    Callers treat ``None`` as "coordinator not available; skip the check".
    """
    if _worker_db is None or _worker_id is None:
        return None
    return (_worker_db, _worker_id)


def clear_worker_context() -> None:
    """Clear the registered context (used in tests and on worker shutdown)."""
    global _worker_db, _worker_id
    _worker_db = None
    _worker_id = None
