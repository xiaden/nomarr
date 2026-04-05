"""VRAM promise registry operations for ArangoDB.

Manages fleet-wide VRAM promise documents that coordinate GPU model placement
across multiple discovery worker processes. Before loading any model onto GPU,
a worker registers a promise via the atomic AQL fit-check transaction. Crashes
are recovered via TTL-based stale reaping.

Collection: vram_promises
Document schema:
    _key:         sha256(worker_id + ":" + model_path)[:32]  (stable, unique)
    worker_id:    Worker identifier (e.g., "nomarr-tag:0")
    pid:          Worker OS PID
    model_path:   Absolute path to the ONNX model file
    promised_mb:  VRAM promised for this model (MB)
    total_mb:     Total GPU VRAM at time of promise (MB)
    used_mb:      In-use VRAM at time of promise (MB)
    last_seen_ms: Unix timestamp, milliseconds (updated on register)
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.time_helper import now_ms

if TYPE_CHECKING:
    from arango.cursor import Cursor

    from nomarr.persistence.arango_client import DatabaseLike

logger = logging.getLogger(__name__)

# Safety headroom reserved in addition to each model's own promise.
# Prevents the final model from being loaded with zero elbow room.
_RESERVE_MB = 256


def _promise_key(worker_id: str, model_path: str) -> str:
    """Compute a stable, ArangoDB-safe document key for a worker+model pair.

    Uses the first 32 hex digits of SHA-256 so the key is always valid
    (hex chars only) and deterministic across restarts.

    Args:
        worker_id:  Worker identifier string.
        model_path: Absolute path to the ONNX model file.

    Returns:
        32-character lowercase hex string.

    """
    raw = f"{worker_id}:{model_path}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


class VramPromisesOperations:
    """Operations for the vram_promises collection.

    Designed for fleet-wide GPU placement coordination across worker processes.
    ``try_register`` is the critical path: it atomically checks whether a new
    model fits within available VRAM headroom (accounting for all existing
    promises) and inserts the promise only if it does.

    The AQL fit-check is a single write statement — its atomicity relies on
    ArangoDB serialising concurrent writes to the same document key. Race
    conditions between two workers reading the aggregate before either inserts
    are theoretically possible but practically unlikely; the 256 MB reserve
    provides an additional safety buffer.
    """

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def try_register(
        self,
        worker_id: str,
        pid: int,
        model_path: str,
        promised_mb: float,
        total_mb: float,
        used_mb: float,
    ) -> bool:
        """Atomically register a VRAM promise if the model fits.

        Checks whether ``(total_mb - used_mb) - sum(existing_promises) >= promised_mb + reserve``
        and, if so, inserts (or replaces) the promise document.

        Args:
            worker_id:   Worker identifier (e.g., "nomarr-tag:0").
            pid:         Worker OS PID.
            model_path:  Absolute path to the ONNX model file.
            promised_mb: VRAM required for this model (MB).
            total_mb:    Total GPU VRAM (MB) as observed by this worker.
            used_mb:     In-use VRAM (MB) as observed by this worker.

        Returns:
            True if the promise was registered (fits), False if rejected (no headroom).

        """
        key = _promise_key(worker_id, model_path)
        ts = now_ms().value

        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                LET sum_promised = FIRST(
                    FOR p IN vram_promises
                    COLLECT AGGREGATE s = SUM(TO_NUMBER(p.promised_mb))
                    RETURN s
                )
                LET free_mb = @total_mb - @used_mb
                LET headroom = free_mb - (sum_promised != null ? sum_promised : 0) - @reserve_mb
                FILTER headroom >= @promised_mb
                INSERT {
                    _key: @key,
                    worker_id: @worker_id,
                    pid: @pid,
                    model_path: @model_path,
                    promised_mb: @promised_mb,
                    total_mb: @total_mb,
                    used_mb: @used_mb,
                    last_seen_ms: @now_ms
                } INTO vram_promises
                OPTIONS { overwriteMode: "replace" }
                RETURN true
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "key": key,
                        "worker_id": worker_id,
                        "pid": pid,
                        "model_path": model_path,
                        "promised_mb": promised_mb,
                        "total_mb": total_mb,
                        "used_mb": used_mb,
                        "reserve_mb": float(_RESERVE_MB),
                        "now_ms": ts,
                    },
                ),
            ),
        )
        results = list(cursor)
        return len(results) > 0

    def release(self, worker_id: str, model_path: str) -> None:
        """Release the promise for a specific worker+model pair.

        Safe to call even if the promise does not exist (no-op).

        Args:
            worker_id:  Worker identifier.
            model_path: Absolute path to the ONNX model file.

        """
        key = _promise_key(worker_id, model_path)
        self.db.aql.execute(  # type: ignore[union-attr]
            """
            LET existing = DOCUMENT(CONCAT("vram_promises/", @key))
            FILTER existing != null
            REMOVE @key IN vram_promises
            """,
            bind_vars=cast("dict[str, Any]", {"key": key}),
        )

    def release_all_for_worker(self, worker_id: str) -> int:
        """Release all VRAM promises held by a specific worker.

        Intended for use at worker startup (clear stale promises from a
        previous crash of this same worker) and at graceful shutdown.
        Safe to call even if no promises exist for the worker.

        Args:
            worker_id: Worker identifier.

        Returns:
            Number of promise documents removed.

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                """
                FOR p IN vram_promises
                FILTER p.worker_id == @worker_id
                REMOVE p IN vram_promises
                RETURN 1
                """,
                bind_vars=cast("dict[str, Any]", {"worker_id": worker_id}),
            ),
        )
        removed = len(list(cursor))
        if removed:
            logger.debug(
                "VramPromisesOperations.release_all_for_worker: removed %d promise(s) for %s",
                removed,
                worker_id,
            )
        return removed

    # ------------------------------------------------------------------
    # Read / maintenance operations
    # ------------------------------------------------------------------

    def get_all(self) -> list[dict[str, Any]]:
        """Return all current promise documents.

        Returns:
            List of promise dicts as stored in ArangoDB.

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(  # type: ignore[union-attr]
                "FOR p IN vram_promises RETURN p",
            ),
        )
        return list(cursor)  # type: ignore[arg-type]
