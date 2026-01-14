"""Calibration runs operations for ArangoDB."""

from typing import Any, cast

from arango.cursor import Cursor
from arango.database import StandardDatabase

from nomarr.helpers.time_helper import now_ms


class CalibrationRunsOperations:
    """Operations for the calibration_runs collection."""

    def __init__(self, db: StandardDatabase) -> None:
        self.db = db
        self.collection = db.collection("calibration_runs")

    def create_run(self, run_id: str, model_key: str, config: dict[str, Any]) -> str:
        """Create a new calibration run.

        Args:
            run_id: Unique run ID
            model_key: Model key being calibrated
            config: Calibration configuration

        Returns:
            Run _id
        """
        ts = now_ms()
        result = cast(
            dict[str, Any],
            self.collection.insert(
                {
                    "run_id": run_id,
                    "model_key": model_key,
                    "config": config,
                    "status": "pending",
                    "created_at": ts,
                    "started_at": None,
                    "finished_at": None,
                    "results": None,
                    "error_message": None,
                }
            ),
        )
        return str(result["_id"])

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Get calibration run by run_id.

        Args:
            run_id: Run ID

        Returns:
            Run dict or None if not found
        """
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR run IN calibration_runs
                FILTER run.run_id == @run_id
                LIMIT 1
                RETURN run
            """,
                bind_vars={"run_id": run_id},
            ),
        )
        return next(cursor, None)

    def update_run(
        self, run_id: str, status: str, results: dict[str, Any] | None = None, error_message: str | None = None
    ) -> None:
        """Update run status.

        Args:
            run_id: Run ID
            status: New status ('pending', 'running', 'complete', 'error')
            results: Calibration results dict
            error_message: Error message if status is 'error'
        """
        ts = now_ms()
        update_fields: dict[str, Any] = {"status": status}

        if status == "running":
            update_fields["started_at"] = ts
        elif status in ("complete", "error"):
            update_fields["finished_at"] = ts
            update_fields["results"] = results
            update_fields["error_message"] = error_message

        self.db.aql.execute(
            """
            FOR run IN calibration_runs
                FILTER run.run_id == @run_id
                UPDATE run WITH @fields IN calibration_runs
            """,
            bind_vars={"run_id": run_id, "fields": update_fields},
        )

    def list_runs(self, model_key: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """List calibration runs.

        Args:
            model_key: Filter by model key (optional)
            limit: Maximum number of runs to return

        Returns:
            List of run dicts
        """
        filter_clause = "FILTER run.model_key == @model_key" if model_key else ""
        bind_vars: dict[str, Any] = {"limit": limit}
        if model_key:
            bind_vars["model_key"] = model_key

        cursor = cast(
            Cursor,
            self.db.aql.execute(
                f"""
            FOR run IN calibration_runs
                {filter_clause}
                SORT run.created_at DESC
                LIMIT @limit
                RETURN run
            """,
                bind_vars=bind_vars,
            ),
        )
        return list(cursor)

    def delete_run(self, run_id: str) -> None:
        """Delete a calibration run.

        Args:
            run_id: Run ID to delete
        """
        self.db.aql.execute(
            """
            FOR run IN calibration_runs
                FILTER run.run_id == @run_id
                REMOVE run IN calibration_runs
            """,
            bind_vars={"run_id": run_id},
        )

    def get_reference_calibration_run(self, model_key: str) -> dict[str, Any] | None:
        """Get the most recent successful calibration run for a model."""
        cursor = cast(
            Cursor,
            self.db.aql.execute(
                """
            FOR run IN calibration_runs
                FILTER run.model_key == @model_key AND run.status == 'completed'
                SORT run.created_at DESC
                LIMIT 1
                RETURN run
            """,
                bind_vars=cast(dict[str, Any], {"model_key": model_key}),
            ),
        )
        runs = list(cursor)
        return runs[0] if runs else None

    def insert_calibration_run(
        self,
        model_name: str,
        head_name: str,
        version: int,
        file_count: int,
        p5: float,
        p95: float,
        range_val: float,
        reference_version: int | None,
        apd_p5: float | None = None,
        apd_p95: float | None = None,
        srd: float | None = None,
        jsd: float | None = None,
        median_drift: float | None = None,
        iqr_drift: float | None = None,
        is_stable: bool | None = None,
    ) -> str:
        """Insert a new calibration run record.

        Args:
            model_name: Model name
            head_name: Head name
            version: Calibration version number
            file_count: Number of files in calibration
            p5: 5th percentile
            p95: 95th percentile
            range_val: Range (p95 - p5)
            reference_version: Reference version for drift calculation
            apd_p5: Absolute percentage drift for p5
            apd_p95: Absolute percentage drift for p95
            srd: Symmetric range drift
            jsd: Jensen-Shannon divergence
            median_drift: Median drift
            iqr_drift: IQR drift
            is_stable: Whether calibration is stable

        Returns:
            Calibration run _id
        """
        model_key = f"{model_name}_{head_name}"

        doc = {
            "model_key": model_key,
            "model_name": model_name,
            "head_name": head_name,
            "version": version,
            "file_count": file_count,
            "p5": p5,
            "p95": p95,
            "range_val": range_val,
            "reference_version": reference_version,
            "apd_p5": apd_p5,
            "apd_p95": apd_p95,
            "srd": srd,
            "jsd": jsd,
            "median_drift": median_drift,
            "iqr_drift": iqr_drift,
            "is_stable": is_stable,
            "status": "completed",
            "created_at": now_ms(),
        }

        result = cast(dict[str, Any], self.collection.insert(doc))
        return str(result["_id"])

    def list_calibration_runs(
        self,
        model_key: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List calibration runs with optional filtering."""
        filters = []
        bind_vars: dict[str, Any] = {"limit": limit}

        if model_key:
            filters.append("run.model_key == @model_key")
            bind_vars["model_key"] = model_key
        if status:
            filters.append("run.status == @status")
            bind_vars["status"] = status

        filter_clause = f"FILTER {' AND '.join(filters)}" if filters else ""

        cursor = cast(
            Cursor,
            self.db.aql.execute(
                f"""
            FOR run IN calibration_runs
                {filter_clause}
                SORT run.created_at DESC
                LIMIT @limit
                RETURN run
            """,
                bind_vars=cast(dict[str, Any], bind_vars),
            ),
        )
        return list(cursor)
