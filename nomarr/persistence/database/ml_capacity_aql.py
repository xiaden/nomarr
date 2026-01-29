"""ML Capacity operations for ArangoDB.

Manages ml_capacity_estimates and ml_capacity_probe_locks collections for
GPU/CPU adaptive resource management.

Per GPU_REFACTOR_PLAN.md Section 7:
- One-time probe per model_set_hash
- Protected by DB lock to prevent concurrent probes
- Results stored as measured_backbone_vram_mb and estimated_worker_ram_mb
"""

from typing import TYPE_CHECKING, Any, cast

from arango.exceptions import DocumentInsertError

from nomarr.helpers.time_helper import now_ms
from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor


class MLCapacityOperations:
    """Operations for ML capacity estimation collections."""

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db

    # ==================== Probe Lock Operations ====================

    def try_acquire_probe_lock(self, model_set_hash: str, worker_id: str) -> bool:
        """Attempt to acquire probe lock for a model_set_hash.

        Uses ArangoDB unique constraint on _key to prevent race conditions.
        Only one worker can acquire the lock at a time.

        Args:
            model_set_hash: Hash of the model set being probed
            worker_id: ID of the worker attempting to acquire lock

        Returns:
            True if lock acquired, False if another worker owns the lock

        """
        try:
            self.db.aql.execute(
                """
                INSERT {
                    _key: @model_set_hash,
                    status: "in_progress",
                    worker_id: @worker_id,
                    started_at: @started_at
                } INTO ml_capacity_probe_locks
                """,
                bind_vars=cast(
                    "dict[str, Any]",
                    {
                        "model_set_hash": model_set_hash,
                        "worker_id": worker_id,
                        "started_at": now_ms().value,
                    },
                ),
            )
            return True
        except DocumentInsertError:
            # Lock already exists - another worker owns it
            return False

    def get_probe_lock_status(self, model_set_hash: str) -> dict[str, Any] | None:
        """Get the status of a probe lock.

        Args:
            model_set_hash: Hash of the model set

        Returns:
            Lock document or None if not found

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                FOR lock IN ml_capacity_probe_locks
                    FILTER lock._key == @model_set_hash
                    RETURN lock
                """,
                bind_vars={"model_set_hash": model_set_hash},
            ),
        )
        return next(cursor, None)

    def complete_probe_lock(self, model_set_hash: str) -> None:
        """Mark a probe lock as complete.

        Args:
            model_set_hash: Hash of the model set

        """
        self.db.aql.execute(
            """
            UPDATE { _key: @model_set_hash }
            WITH { status: "complete", completed_at: @completed_at }
            IN ml_capacity_probe_locks
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "model_set_hash": model_set_hash,
                    "completed_at": now_ms().value,
                },
            ),
        )

    def release_probe_lock(self, model_set_hash: str) -> None:
        """Release (delete) a probe lock, typically on failure.

        Args:
            model_set_hash: Hash of the model set

        """
        self.db.aql.execute(
            """
            REMOVE { _key: @model_set_hash } IN ml_capacity_probe_locks
            OPTIONS { ignoreErrors: true }
            """,
            bind_vars={"model_set_hash": model_set_hash},
        )

    # ==================== Capacity Estimate Operations ====================

    def get_capacity_estimate(self, model_set_hash: str) -> dict[str, Any] | None:
        """Get capacity estimate for a model_set_hash.

        Args:
            model_set_hash: Hash of the model set

        Returns:
            Capacity estimate document or None if not found

        """
        cursor = cast(
            "Cursor",
            self.db.aql.execute(
                """
                FOR est IN ml_capacity_estimates
                    FILTER est._key == @model_set_hash
                    RETURN est
                """,
                bind_vars={"model_set_hash": model_set_hash},
            ),
        )
        return next(cursor, None)

    def save_capacity_estimate(
        self,
        model_set_hash: str,
        measured_backbone_vram_mb: int,
        estimated_worker_ram_mb: int,
        probe_duration_s: float,
        probed_by_worker: str,
    ) -> None:
        """Save capacity estimate after successful probe.

        Per GPU_REFACTOR_PLAN.md Section 7:
        - measured_backbone_vram_mb: Per-PID VRAM usage via nvidia-smi
        - estimated_worker_ram_mb: RSS via psutil (heads + overhead)

        Args:
            model_set_hash: Hash of the model set
            measured_backbone_vram_mb: Measured VRAM usage for backbone
            estimated_worker_ram_mb: Estimated RAM for worker (heads + overhead)
            probe_duration_s: How long the probe took
            probed_by_worker: Worker ID that performed the probe

        """
        self.db.aql.execute(
            """
            UPSERT { _key: @model_set_hash }
            INSERT {
                _key: @model_set_hash,
                measured_backbone_vram_mb: @backbone_vram,
                estimated_worker_ram_mb: @worker_ram,
                probe_duration_s: @duration,
                probed_by: @worker_id,
                created_at: @timestamp
            }
            UPDATE {
                measured_backbone_vram_mb: @backbone_vram,
                estimated_worker_ram_mb: @worker_ram,
                probe_duration_s: @duration,
                probed_by: @worker_id,
                updated_at: @timestamp
            }
            IN ml_capacity_estimates
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "model_set_hash": model_set_hash,
                    "backbone_vram": measured_backbone_vram_mb,
                    "worker_ram": estimated_worker_ram_mb,
                    "duration": probe_duration_s,
                    "worker_id": probed_by_worker,
                    "timestamp": now_ms().value,
                },
            ),
        )

    def delete_capacity_estimate(self, model_set_hash: str) -> None:
        """Delete a capacity estimate (for invalidation on model set change).

        Args:
            model_set_hash: Hash of the model set

        """
        self.db.aql.execute(
            """
            REMOVE { _key: @model_set_hash } IN ml_capacity_estimates
            OPTIONS { ignoreErrors: true }
            """,
            bind_vars={"model_set_hash": model_set_hash},
        )

        # Also remove the lock if present
        self.release_probe_lock(model_set_hash)
