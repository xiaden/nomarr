"""
CalibrationService - Generate calibrations with drift tracking.

Wraps ml.calibration module to add:
- Drift metrics calculation between runs
- Database tracking of calibration history
- Versioned calibration file management
- Stability detection and reference version tracking
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any

import numpy as np

from nomarr.ml.calibration import generate_minmax_calibration, save_calibration_sidecars
from nomarr.services.calibration_metrics import compare_calibrations

if TYPE_CHECKING:
    from nomarr.data.db import Database


logger = logging.getLogger(__name__)


class CalibrationService:
    """
    Service for generating and tracking calibration with drift metrics.

    Coordinates calibration generation, drift calculation, and database tracking.
    Ensures each head's calibration stability is monitored independently.
    """

    def __init__(
        self,
        db: Database,
        models_dir: str,
        namespace: str = "nom",
        thresholds: dict[str, float] | None = None,
    ):
        """
        Initialize calibration service.

        Args:
            db: Database instance
            models_dir: Path to models directory
            namespace: Tag namespace (default "nom")
            thresholds: Optional custom drift thresholds
        """
        self.db = db
        self.models_dir = models_dir
        self.namespace = namespace
        self.thresholds = thresholds or {}

    def generate_calibration_with_tracking(self) -> dict[str, Any]:
        """
        Generate calibrations for all heads and track drift metrics.

        This is the main entry point for calibration generation. It:
        1. Generates calibration from library tags
        2. Determines next version number (max version + 1 across all heads)
        3. For each head: compares to reference, calculates drift, stores metadata
        4. Saves versioned calibration files
        5. Returns summary with drift metrics per head

        Returns:
            Dict with:
                - version: New calibration version number
                - library_size: Number of files analyzed
                - heads: Dict of head results with drift metrics
                - saved_files: Paths to saved calibration files
                - summary: Overall statistics
        """
        logger.info("[CalibrationService] Generating calibration with drift tracking")

        # Generate calibration data from library
        calibration_data = generate_minmax_calibration(db=self.db, namespace=self.namespace)

        library_size = calibration_data.get("library_size", 0)
        calibrations = calibration_data.get("calibrations", {})

        if not calibrations:
            logger.warning("[CalibrationService] No calibrations generated (empty library or insufficient samples)")
            return {
                "version": None,
                "library_size": library_size,
                "heads": {},
                "saved_files": {},
                "summary": {"total_heads": 0, "stable_heads": 0, "unstable_heads": 0},
            }

        # Determine next version number (global across all heads for this run)
        # Version = run number (all heads increment together per Option A)
        next_version = self._get_next_version()

        logger.info(f"[CalibrationService] Generating calibration version {next_version} from {library_size} files")

        # Parse calibrations by head and track drift
        head_results = {}

        for tag_key, calib_stats in calibrations.items():
            # Parse tag key to extract model_name and head_name
            # Format: label_framework_embedder{date}_label{date}_calib_version
            parsed = self._parse_tag_key(tag_key)
            if not parsed:
                logger.warning(f"[CalibrationService] Cannot parse tag key: {tag_key}")
                continue

            model_name, head_name, label = parsed

            # Create unique key for this head
            head_key = f"{model_name}/{head_name}"

            # Track this head's calibration (one entry per head, aggregate all labels)
            if head_key not in head_results:
                head_results[head_key] = {
                    "model_name": model_name,
                    "head_name": head_name,
                    "labels": {},
                    "drift_metrics": None,
                    "is_stable": None,
                    "reference_version": None,
                }

            # Store label calibration data
            head_results[head_key]["labels"][label] = calib_stats

        # For each head, calculate drift and store in DB
        for head_key, head_data in head_results.items():
            model_name = head_data["model_name"]
            head_name = head_data["head_name"]
            labels = head_data["labels"]

            # Get reference calibration (most recent stable version)
            reference = self.db.get_reference_calibration_run(model_name, head_name)

            # Calculate drift if reference exists
            drift_result = None
            if reference:
                drift_result = self._calculate_head_drift(labels, reference, model_name, head_name)
                head_data["drift_metrics"] = drift_result
                head_data["is_stable"] = drift_result["is_stable"]
                head_data["reference_version"] = reference["version"]
            else:
                # First calibration - always stable (no comparison)
                head_data["is_stable"] = True
                head_data["reference_version"] = None
                logger.info(f"[CalibrationService] {head_key}: First calibration (v{next_version})")

            # Calculate aggregate p5/p95/range across all labels for this head
            all_p5 = [calib["p5"] for calib in labels.values()]
            all_p95 = [calib["p95"] for calib in labels.values()]
            avg_p5 = float(np.mean(all_p5))
            avg_p95 = float(np.mean(all_p95))
            avg_range = avg_p95 - avg_p5

            # Store calibration run in database
            self.db.insert_calibration_run(
                model_name=model_name,
                head_name=head_name,
                version=next_version,
                file_count=library_size,
                p5=avg_p5,
                p95=avg_p95,
                range_val=avg_range,
                reference_version=head_data["reference_version"],
                apd_p5=drift_result["apd_p5"] if drift_result else None,
                apd_p95=drift_result["apd_p95"] if drift_result else None,
                srd=drift_result["srd"] if drift_result else None,
                jsd=drift_result["jsd"] if drift_result else None,
                median_drift=drift_result["median_drift"] if drift_result else None,
                iqr_drift=drift_result["iqr_drift"] if drift_result else None,
                is_stable=head_data["is_stable"],
            )

            # Log result
            if drift_result:
                stability_str = "STABLE" if drift_result["is_stable"] else "UNSTABLE"
                failed_metrics = drift_result.get("failed_metrics", [])
                logger.info(
                    f"[CalibrationService] {head_key} v{next_version}: {stability_str} "
                    f"(ref=v{head_data['reference_version']}, "
                    f"failed={failed_metrics if failed_metrics else 'none'})"
                )

        # Save calibration sidecars (versioned files)
        saved_files = save_calibration_sidecars(
            calibration_data=calibration_data, models_dir=self.models_dir, version=next_version
        )

        # Update reference calibration files for unstable heads
        # When a head becomes unstable, its new calibration becomes the reference
        reference_updates = self._update_reference_files(head_results, next_version)

        # Generate summary
        stable_count = sum(1 for h in head_results.values() if h["is_stable"])
        unstable_count = len(head_results) - stable_count

        summary = {
            "version": next_version,
            "library_size": library_size,
            "heads": head_results,
            "saved_files": saved_files,
            "reference_updates": reference_updates,
            "summary": {
                "total_heads": len(head_results),
                "stable_heads": stable_count,
                "unstable_heads": unstable_count,
            },
        }

        logger.info(
            f"[CalibrationService] Calibration v{next_version} complete: "
            f"{stable_count} stable, {unstable_count} unstable (total {len(head_results)} heads)"
        )

        return summary

    def _get_next_version(self) -> int:
        """
        Get next calibration version number.

        Version is global across all heads for a given run (Option A).
        Finds the maximum version across all heads and adds 1.

        Returns:
            Next version number (starts at 1)
        """
        # Get all calibration runs
        all_runs = self.db.list_calibration_runs(limit=10000)

        if not all_runs:
            return 1

        # Find max version
        max_version = max(run["version"] for run in all_runs)
        return max_version + 1

    def _parse_tag_key(self, tag_key: str) -> tuple[str, str, str] | None:
        """
        Parse tag key to extract model_name, head_name, and label.

        Tag format: label_framework_embedder{date}_label{date}_calib_version
        Example: happy_essentia21b6dev1389_yamnet20210604_happy20220825_none_0

        Returns:
            Tuple of (model_name, head_name, label) or None if parse fails
        """
        parts = tag_key.split("_")
        if len(parts) < 5:
            return None

        # Extract embedder (backbone) - at index -4
        embedder_part = parts[-4]  # e.g., "yamnet20210604"

        # Extract head part - at index -3
        head_part = parts[-3]  # e.g., "happy20220825"

        # Extract label from head part (everything before the 8-digit date)
        if len(head_part) < 8 or not head_part[-8:].isdigit():
            return None
        head_name = head_part[:-8] if len(head_part) > 8 else parts[0]

        # Extract backbone from embedder part
        model_name = None
        for i in range(len(embedder_part) - 7):
            if embedder_part[i : i + 2] == "20" and embedder_part[i : i + 8].isdigit():
                model_name = embedder_part[:i]
                break

        if not model_name:
            return None

        # Label is the first part of the tag key
        label = parts[0]

        return (model_name, head_name, label)

    def _calculate_head_drift(
        self, new_labels: dict[str, dict], reference_run: dict, model_name: str, head_name: str
    ) -> dict:
        """
        Calculate drift metrics for a head by comparing to reference calibration.

        Args:
            new_labels: Dict of label -> calibration stats for new run
            reference_run: Reference calibration run from DB
            model_name: Model identifier
            head_name: Head identifier

        Returns:
            Drift metrics dict from compare_calibrations()
        """
        # Load reference calibration file to get old scores
        reference_version = reference_run["version"]
        reference_file = self._find_calibration_file(model_name, head_name, reference_version)

        if not reference_file or not os.path.exists(reference_file):
            logger.warning(
                f"[CalibrationService] Reference calibration file not found: {reference_file}. "
                f"Treating as first run."
            )
            # No reference file - treat as first calibration
            return {
                "apd_p5": 0.0,
                "apd_p95": 0.0,
                "srd": 0.0,
                "jsd": 0.0,
                "median_drift": 0.0,
                "iqr_drift": 0.0,
                "is_stable": True,
                "failed_metrics": [],
            }

        # Load old calibration data
        with open(reference_file, encoding="utf-8") as f:
            old_calib_data = json.load(f)

        old_labels = old_calib_data.get("labels", {})

        # Aggregate p5/p95 across all labels
        old_p5_values = [calib["p5"] for calib in old_labels.values()]
        old_p95_values = [calib["p95"] for calib in old_labels.values()]
        new_p5_values = [calib["p5"] for calib in new_labels.values()]
        new_p95_values = [calib["p95"] for calib in new_labels.values()]

        # Create synthetic "old" and "new" calibration dicts for comparison
        old_calibration = {"p5": float(np.mean(old_p5_values)), "p95": float(np.mean(old_p95_values))}

        new_calibration = {"p5": float(np.mean(new_p5_values)), "p95": float(np.mean(new_p95_values))}

        # For JSD calculation, we need score distributions
        # Use the raw scores from library (stored in calibration stats)
        # For now, synthesize distributions from p5/p95 (approximation)
        old_scores = self._synthesize_distribution(old_labels)
        new_scores = self._synthesize_distribution(new_labels)

        # Calculate drift metrics
        drift_result = compare_calibrations(
            old_calibration=old_calibration,
            new_calibration=new_calibration,
            old_scores=old_scores,
            new_scores=new_scores,
            thresholds=self.thresholds,
        )

        return drift_result

    def _find_calibration_file(self, model_name: str, head_name: str, version: int) -> str | None:
        """
        Find calibration file path for a specific model/head/version.

        Args:
            model_name: Model identifier (e.g., "effnet")
            head_name: Head identifier (e.g., "mood_happy")
            version: Calibration version number

        Returns:
            Path to calibration file or None if not found
        """
        # Search for calibration file in models directory
        # Format: models/{backbone}/heads/{head_name}-calibration-v{version}.json
        search_path = os.path.join(self.models_dir, model_name, "heads")
        if not os.path.exists(search_path):
            return None

        # Find matching calibration file
        for filename in os.listdir(search_path):
            if filename.startswith(head_name) and filename.endswith(f"-calibration-v{version}.json"):
                return os.path.join(search_path, filename)

        return None

    def _synthesize_distribution(self, labels: dict[str, dict]) -> np.ndarray:
        """
        Synthesize score distribution from label calibration stats.

        Uses mean/std to generate approximate distribution for JSD calculation.
        This is an approximation - ideally we'd store raw scores in DB.

        Args:
            labels: Dict of label -> calibration stats

        Returns:
            Numpy array of synthesized scores
        """
        all_scores = []
        for calib in labels.values():
            mean = calib.get("mean", 0.5)
            std = calib.get("std", 0.1)
            samples = calib.get("samples", 1000)

            # Generate normal distribution centered at mean with given std
            scores = np.random.normal(mean, std, min(samples, 1000))
            # Clamp to [0, 1]
            scores = np.clip(scores, 0.0, 1.0)
            all_scores.extend(scores)

        return np.array(all_scores)

    def _update_reference_files(self, head_results: dict, version: int) -> dict[str, str]:
        """
        Update reference calibration files (calibration.json) for unstable heads.

        When a head becomes unstable, its new calibration version becomes the reference.
        This copies the versioned file to calibration.json (the default file used by inference).

        For stable heads, reference file is unchanged (keeps using older stable version).

        Args:
            head_results: Dict of head results with stability info
            version: New calibration version number

        Returns:
            Dict of head_key -> action taken ("updated", "unchanged", "error")
        """
        import shutil

        updates = {}

        for head_key, head_data in head_results.items():
            model_name = head_data["model_name"]
            head_name = head_data["head_name"]
            is_stable = head_data["is_stable"]

            # Find versioned calibration file for this head
            versioned_file = self._find_calibration_file(model_name, head_name, version)

            if not versioned_file or not os.path.exists(versioned_file):
                logger.warning(f"[CalibrationService] Versioned file not found for {head_key} v{version}")
                updates[head_key] = "error"
                continue

            # Determine reference file path (same directory, but "calibration.json" name)
            ref_file = versioned_file.replace(f"-calibration-v{version}.json", "-calibration.json")

            # Update reference file if head is unstable OR if no reference exists yet
            should_update = not is_stable or not os.path.exists(ref_file)

            if should_update:
                try:
                    shutil.copy2(versioned_file, ref_file)
                    logger.info(
                        f"[CalibrationService] Updated reference calibration: {head_key} -> v{version} "
                        f"({'first' if not os.path.exists(ref_file) else 'unstable'})"
                    )
                    updates[head_key] = "updated"
                except Exception as e:
                    logger.error(f"[CalibrationService] Failed to update reference for {head_key}: {e}")
                    updates[head_key] = "error"
            else:
                # Stable - keep existing reference
                logger.debug(f"[CalibrationService] {head_key} stable, keeping existing reference")
                updates[head_key] = "unchanged"

        return updates
