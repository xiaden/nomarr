"""
Calibration module - generates and applies calibrations from library data.

Min-max calibration normalizes raw model outputs to a common scale [0, 1] based on
the empirical distribution of predictions across the user's library. This ensures
all models use comparable score ranges without forcing specific tag prevalence.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import numpy as np

from nomarr.persistence.db import Database


def generate_minmax_calibration(
    db: Database,
    namespace: str = "nom",
) -> dict[str, Any]:
    """
    Generate min-max scale calibration from library tags.

    Analyzes raw model outputs to determine scaling parameters (5th/95th percentiles)
    for normalizing each model to a common [0, 1] scale. This makes model outputs
    comparable while preserving the semantic meaning of scores.

    Requires minimum 1000 samples per tag (industry standard for reliable calibration).

    Args:
        db: Database instance
        namespace: Tag namespace (default "nom")

    Returns:
        Calibration manifest with min-max scaling parameters per tag
    """
    min_samples = 1000  # Industry standard - do not modify
    logging.info("[calibration] Analyzing library tags for min-max calibration")

    # Fetch all library files with tags (fetch in batches to handle large libraries)
    all_files = []
    limit = 1000
    offset = 0

    while True:
        files, _total_count = db.library_files.list_library_files(limit=limit, offset=offset)
        all_files.extend(files)
        offset += limit
        if len(files) < limit:
            break

    if not all_files:
        # Empty library - return empty calibration result (not error)
        logging.info("[calibration] No library files found")
        return {
            "method": "percentile",
            "library_size": 0,
            "min_samples": min_samples,
            "calibrations": {},
            "skipped_tags": 0,
        }

    logging.info(f"[calibration] Found {len(all_files)} library files")

    # Collect raw probabilities for each tag
    tag_values: dict[str, list[float]] = {}

    for file in all_files:
        # Get nom_tags column (framework-agnostic Nomarr-generated tags)
        # Tags stored without namespace prefix in DB
        tags_json = file.get("nom_tags")
        if not tags_json:
            continue

        try:
            tags = json.loads(tags_json)
        except json.JSONDecodeError:
            continue

        # Extract versioned tags (skip mood-strict/regular/loose and tier tags)
        for key, value in tags.items():
            # Tags in nom_tags are stored without namespace prefix
            tag_key = key

            # Skip aggregated mood tags and tier suffixes
            if tag_key.startswith("mood-") or tag_key.endswith("_tier"):
                continue

            # Extract numeric probability
            try:
                prob = float(value)
                if 0.0 <= prob <= 1.0:  # Valid probability range
                    if tag_key not in tag_values:
                        tag_values[tag_key] = []
                    tag_values[tag_key].append(prob)
            except (ValueError, TypeError):
                continue

    logging.info(f"[calibration] Collected distributions for {len(tag_values)} unique tags")

    # Generate min-max scaling parameters for each tag
    calibrations = {}
    skipped_tags = []

    for tag_key, values in tag_values.items():
        if len(values) < min_samples:
            skipped_tags.append((tag_key, len(values)))
            continue

        values_arr = np.array(values)

        # Compute min-max scaling parameters (5th and 95th percentiles)
        # Using percentiles instead of absolute min/max to avoid outliers
        p5 = float(np.percentile(values_arr, 5))
        p95 = float(np.percentile(values_arr, 95))

        calibrations[tag_key] = {
            "method": "minmax",
            "samples": len(values),
            "p5": p5,  # Lower bound (5th percentile)
            "p95": p95,  # Upper bound (95th percentile)
            "mean": float(np.mean(values_arr)),
            "std": float(np.std(values_arr)),
            "min": float(np.min(values_arr)),
            "max": float(np.max(values_arr)),
        }

    if skipped_tags:
        logging.warning(
            f"[calibration] Skipped {len(skipped_tags)} tags with < {min_samples} samples: "
            f"{skipped_tags[:5]}{'...' if len(skipped_tags) > 5 else ''}"
        )

    logging.info(f"[calibration] Generated calibrations for {len(calibrations)} tags")

    return {
        "method": "minmax",
        "library_size": len(all_files),
        "min_samples": min_samples,
        "calibrations": calibrations,
        "skipped_tags": len(skipped_tags),
    }


def save_calibration_sidecars(
    calibration_data: dict[str, Any],
    models_dir: str,
    version: int = 1,
) -> dict[str, Any]:
    """
    Save calibration data as JSON sidecars next to model files.

    Parses versioned tag keys to determine which model (embedder + head) generated each tag,
    then saves calibration data as <model>-calibration-v{version}.json sidecars.

    Args:
        calibration_data: Output from generate_minmax_calibration()
        models_dir: Path to models directory
        version: Calibration version number

    Returns:
        Summary of saved files with paths and tag counts
    """
    from nomarr.components.ml.models.discovery import discover_heads

    logging.info("[calibration] Saving calibration sidecars")

    # Discover all heads to map tag keys to model paths
    heads = discover_heads(models_dir)
    if not heads:
        raise ValueError(f"No heads found in {models_dir}")

    # Build lookup: (backbone, head_date, label) -> head_info
    head_lookup = {}
    for h in heads:
        head_date = h.sidecar.data.get("release_date", "").replace("-", "")
        # Extract all labels from this head
        for label in h.sidecar.labels:
            # Normalize label (non_happy -> not_happy)
            from nomarr.components.tagging.aggregation import normalize_tag_label

            norm_label = normalize_tag_label(label)
            key = (h.backbone, head_date, norm_label)
            head_lookup[key] = h

    # Group calibrations by model
    model_calibrations: dict[str, dict[str, Any]] = {}

    calibrations = calibration_data.get("calibrations", {})
    for tag_key, calib_stats in calibrations.items():
        # Parse tag key (NEW FORMAT - no calibration suffix):
        # Format: label_framework_embedder{date}_head{date}
        # Example: happy_essentia21b6dev1389_yamnet20210604_happy20220825
        parts = tag_key.split("_")
        if len(parts) < 4:
            logging.warning(f"[calibration] Cannot parse tag key: {tag_key}")
            continue

        # Extract components (work backwards from end)
        # NEW FORMAT: label_framework_embedder{date}_head{date}
        # head_part is at index -1 (last component)
        head_part = parts[-1]  # label{date} like "happy20220825"

        # Extract head date (last 8 digits)
        if len(head_part) < 8 or not head_part[-8:].isdigit():
            logging.warning(f"[calibration] Cannot find head date in tag key: {tag_key}")
            continue

        head_date = head_part[-8:]

        # Extract label from head part (everything before the date)
        label = head_part[:-8] if len(head_part) > 8 else parts[0]

        # Embedder part is at index -2
        if len(parts) < 4:
            logging.warning(f"[calibration] Cannot find embedder in tag key: {tag_key}")
            continue

        embedder_part = parts[-2]  # backbone{date} like "yamnet20210604"

        # Extract backbone name (everything before the date)
        # Find where the date starts (first occurrence of "20" followed by 6 more digits)
        backbone = None
        for i in range(len(embedder_part) - 7):
            if embedder_part[i : i + 2] == "20" and embedder_part[i : i + 8].isdigit():
                backbone = embedder_part[:i]
                break

        if not backbone:
            logging.warning(f"[calibration] Cannot extract backbone from: {embedder_part}")
            continue

        # Look up head
        lookup_key = (backbone, head_date, label)
        head_info = head_lookup.get(lookup_key)

        if not head_info:
            logging.debug(
                f"[calibration] No head found for {tag_key} (backbone={backbone}, date={head_date}, label={label})"
            )
            continue

        # Get model path
        model_path = head_info.sidecar.path
        model_dir = os.path.dirname(model_path)
        model_base = os.path.basename(model_path).rsplit(".", 1)[0]  # Remove .json

        # Group calibrations by model file
        if model_path not in model_calibrations:
            model_calibrations[model_path] = {
                "model": model_base,
                "head_type": head_info.head_type,
                "backbone": head_info.backbone,
                "labels": {},
            }

        model_calibrations[model_path]["labels"][label] = calib_stats

    # Save calibration sidecars
    saved_files = {}

    for model_path, calib_data in model_calibrations.items():
        model_dir = os.path.dirname(model_path)
        model_base = os.path.basename(model_path).rsplit(".", 1)[0]

        calibration_filename = f"{model_base}-calibration-v{version}.json"
        calibration_path = os.path.join(model_dir, calibration_filename)

        # Build calibration sidecar
        sidecar = {
            "calibration_version": version,
            "calibration_method": "minmax",
            "library_size": calibration_data["library_size"],
            "min_samples": calibration_data["min_samples"],
            "model": calib_data["model"],
            "head_type": calib_data["head_type"],
            "backbone": calib_data["backbone"],
            "labels": calib_data["labels"],
        }

        # Write sidecar
        try:
            with open(calibration_path, "w", encoding="utf-8") as f:
                json.dump(sidecar, f, indent=2, ensure_ascii=False)

            saved_files[calibration_path] = {
                "labels": list(calib_data["labels"].keys()),
                "label_count": len(calib_data["labels"]),
            }

            logging.info(f"[calibration] Saved {calibration_path} ({len(calib_data['labels'])} labels)")

        except Exception as e:
            logging.error(f"[calibration] Failed to save {calibration_path}: {e}")

    logging.info(f"[calibration] Saved {len(saved_files)} calibration sidecars")

    return {
        "saved_files": saved_files,
        "total_files": len(saved_files),
        "total_labels": sum(f["label_count"] for f in saved_files.values()),
    }


def apply_minmax_calibration(raw_score: float, calibration: dict[str, Any]) -> float:
    """
    Apply min-max scale calibration to a raw model score.

    Normalizes raw score to [0, 1] range based on the model's empirical output distribution
    (5th and 95th percentiles). This makes scores from different models comparable without
    changing the semantic meaning or prevalence of tags.

    Formula: (raw - p5) / (p95 - p5), clamped to [0, 1]

    Args:
        raw_score: Raw model output score
        calibration: Calibration data with 'p5' and 'p95' parameters

    Returns:
        Calibrated score in [0, 1] range
    """
    if calibration.get("method") != "minmax":
        return raw_score

    p5 = calibration.get("p5")
    p95 = calibration.get("p95")

    if p5 is None or p95 is None:
        return raw_score

    # Avoid division by zero
    if p95 <= p5:
        return raw_score

    # Apply min-max scaling
    scaled = (raw_score - p5) / (p95 - p5)

    # Clamp to [0, 1] range
    clamped: float = max(0.0, min(1.0, scaled))
    return clamped
