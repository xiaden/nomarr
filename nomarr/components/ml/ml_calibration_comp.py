"""Calibration module - generates and applies calibrations from library data.

Min-max calibration normalizes raw model outputs to a common scale [0, 1] based on
the empirical distribution of predictions across the user's library. This ensures
all models use comparable score ranges without forcing specific tag prevalence.
"""
from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any, cast

from nomarr.helpers.dto.ml_dto import SaveCalibrationSidecarsResult

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.persistence.db import Database

def _parse_tag_key_components(tag_key: str) -> tuple[str, str, str] | None:
    """Parse a tag key into (backbone, head_date, label).

    Tag format: label_framework_embedder{date}_head{date}
    Returns None if parsing fails.
    """
    parts = tag_key.split("_")
    if len(parts) < 4:
        logger.warning(f"[calibration] Cannot parse tag key: {tag_key}")
        return None
    head_part = parts[-1]
    if len(head_part) < 8 or not head_part[-8:].isdigit():
        logger.warning(f"[calibration] Cannot find head date in tag key: {tag_key}")
        return None
    head_date = head_part[-8:]
    label = head_part[:-8] if len(head_part) > 8 else parts[0]
    embedder_part = parts[-2]
    backbone = None
    for i in range(len(embedder_part) - 7):
        if embedder_part[i:i + 2] == "20" and embedder_part[i:i + 8].isdigit():
            backbone = embedder_part[:i]
            break
    if not backbone:
        logger.warning(f"[calibration] Cannot extract backbone from: {embedder_part}")
        return None
    return (backbone, head_date, label)

def save_calibration_sidecars(calibration_data: dict[str, Any], models_dir: str, version: int=1) -> SaveCalibrationSidecarsResult:
    """Save calibration data as JSON sidecars next to model files.

    Parses versioned tag keys to determine which model (embedder + head) generated each tag,
    then saves calibration data as <model>-calibration-v{version}.json sidecars.

    Args:
        calibration_data: Calibration data dict with "calibrations" key mapping labels to {p5, p95}
        models_dir: Path to models directory
        version: Calibration version number

    Returns:
        Summary of saved files with paths and tag counts

    """
    from nomarr.components.ml.ml_discovery_comp import discover_heads
    logger.info("[calibration] Saving calibration sidecars")
    heads = discover_heads(models_dir)
    if not heads:
        msg = f"No heads found in {models_dir}"
        raise ValueError(msg)
    head_lookup = {}
    for head_info in heads:
        head_date = head_info.sidecar.data.get("release_date", "").replace("-", "")
        for label in head_info.sidecar.labels:
            from nomarr.components.tagging.tagging_aggregation_comp import normalize_tag_label
            norm_label = normalize_tag_label(label)
            key = (head_info.backbone, head_date, norm_label)
            head_lookup[key] = head_info
    model_calibrations: dict[str, dict[str, Any]] = {}
    calibrations = calibration_data.get("calibrations", {})
    for tag_key, calib_stats in calibrations.items():
        parsed = _parse_tag_key_components(tag_key)
        if not parsed:
            continue
        backbone, head_date, label = parsed
        lookup_key = (backbone, head_date, label)
        head_info_maybe = head_lookup.get(lookup_key)
        if head_info_maybe is None:
            logger.debug(f"[calibration] No head found for {tag_key} (backbone={backbone}, date={head_date}, label={label})")
            continue
        head_info = head_info_maybe
        model_path = head_info.sidecar.path
        model_dir = os.path.dirname(model_path)
        model_base = os.path.basename(model_path).rsplit(".", 1)[0]
        if model_path not in model_calibrations:
            model_calibrations[model_path] = {"model": model_base, "head_type": head_info.head_type, "backbone": head_info.backbone, "labels": {}}
        model_calibrations[model_path]["labels"][label] = calib_stats
    saved_files = {}
    for model_path, calib_data in model_calibrations.items():
        model_dir = os.path.dirname(model_path)
        model_base = os.path.basename(model_path).rsplit(".", 1)[0]
        calibration_filename = f"{model_base}-calibration-v{version}.json"
        calibration_path = os.path.join(model_dir, calibration_filename)
        library_size = calibration_data.get("library_size", 0)
        min_samples = calibration_data.get("min_samples", 1000)
        sidecar = {"calibration_version": version, "calibration_method": "minmax", "library_size": library_size, "min_samples": min_samples, "model": calib_data["model"], "head_type": calib_data["head_type"], "backbone": calib_data["backbone"], "labels": calib_data["labels"]}
        try:
            with open(calibration_path, "w", encoding="utf-8") as f:
                json.dump(sidecar, f, indent=2, ensure_ascii=False)
            saved_files[calibration_path] = {"labels": list(calib_data["labels"].keys()), "label_count": len(calib_data["labels"])}
            logger.info(f"[calibration] Saved {calibration_path} ({len(calib_data['labels'])} labels)")
        except Exception as e:
            logger.exception(f"[calibration] Failed to save {calibration_path}: {e}")
    logger.info(f"[calibration] Saved {len(saved_files)} calibration sidecars")
    total_labels = 0
    for file_data in saved_files.values():
        label_count = file_data.get("label_count", 0)
        total_labels += int(cast("int", label_count))
    return SaveCalibrationSidecarsResult(saved_files=saved_files, total_files=len(saved_files), total_labels=total_labels)

def apply_minmax_calibration(raw_score: float, calibration: dict[str, Any]) -> float:
    """Apply min-max scale calibration to a raw model score.

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
    if p95 <= p5:
        return raw_score
    scaled = (raw_score - p5) / (p95 - p5)
    clamped: float = max(0.0, min(1.0, scaled))
    return clamped

def compute_calibration_def_hash(model_key: str, head_name: str, label: str, version: int) -> str:
    """Compute calibration definition hash from model metadata.

    Stable identifier for a calibration configuration. Changes when version or label changes.

    Args:
        model_key: Model identifier (e.g., "effnet-discogs-effnet-1")
        head_name: Head name (e.g., "mood_happy")
        label: Label name (e.g., "happy", "male")
        version: Calibration version

    Returns:
        MD5 hash of calibration definition

    """
    import hashlib
    calib_def_str = f"{model_key}:{head_name}:{label}:{version}"
    return hashlib.md5(calib_def_str.encode()).hexdigest()

def get_default_histogram_spec(head_name: str) -> dict[str, Any]:
    """Get default histogram specification for a head type.

    All heads use same histogram parameters:
    - lo = 0.0 (minimum calibrated value)
    - hi = 1.0 (maximum calibrated value)
    - bins = 10000 (fixed resolution)
    - bin_width = 0.0001 (computed: (hi - lo) / bins)

    This provides consistent, memory-bounded histogram computation
    regardless of head type (mood, genre, instrument, etc).

    Args:
        head_name: Head name (e.g., "mood_happy", "genre_rock")

    Returns:
        {"lo": float, "hi": float, "bins": int}

    """
    return {"lo": 0.0, "hi": 1.0, "bins": 10000}

def derive_percentiles_from_sparse_histogram(sparse_bins: list[dict[str, Any]], lo: float=0.0, hi: float=1.0, bin_width: float=0.0001, p5_target: float=0.05, p95_target: float=0.95) -> dict[str, Any]:
    """Derive p5/p95 from sparse histogram (only non-zero bins).

    Args:
        sparse_bins: AQL query result - list of {min_val: float, count: int, underflow_count: int, overflow_count: int}
        lo: Histogram lower bound (0.0)
        hi: Histogram upper bound (1.0)
        bin_width: Uniform bin width (0.0001)
        p5_target: 5th percentile threshold (0.05)
        p95_target: 95th percentile threshold (0.95)

    Returns:
        {p5: float, p95: float, n: int, underflow_count: int, overflow_count: int}

    Note:
        Approximation error bounded by bin_width.
        Exact quantiles are not a goal; bin-level precision is sufficient.

    """
    sorted_bins = sorted(sparse_bins, key=lambda x: x["min_val"])
    total_n = sum(b["count"] for b in sorted_bins)
    underflow_count = sum(b["underflow_count"] for b in sorted_bins)
    overflow_count = sum(b["overflow_count"] for b in sorted_bins)
    cumsum = underflow_count
    p5_value = None
    p95_value = None
    for bin_data in sorted_bins:
        min_val = bin_data["min_val"]
        count = bin_data["count"]
        cumsum += count
        if p5_value is None and cumsum >= total_n * p5_target:
            p5_value = min_val
        if p95_value is None and cumsum >= total_n * p95_target:
            p95_value = min_val
            break
    if p5_value is None:
        p5_value = lo
    if p95_value is None:
        p95_value = hi
    return {"p5": p5_value, "p95": p95_value, "n": total_n, "underflow_count": underflow_count, "overflow_count": overflow_count}

def generate_calibration_from_histogram(db: Database, model_key: str, head_name: str, label: str, version: int, lo: float=0.0, hi: float=1.0, bins: int=10000) -> dict[str, Any]:
    """Generate calibration for a single label using DB histogram query.

    Stateless, idempotent computation. Always computes from current file_tags.

    Args:
        db: Database instance
        model_key: Model identifier (e.g., "effnet-discogs-effnet-1")
        head_name: Head name for logging (e.g., "mood_happy")
        label: Label to match (e.g., "happy", "male", "arousal")
        version: Calibration version
        lo: Lower bound of calibrated range (default 0.0)
        hi: Upper bound of calibrated range (default 1.0)
        bins: Number of uniform bins (default 10000)

    Returns:
        {p5: float, p95: float, n: int, underflow_count: int, overflow_count: int, histogram_bins: list[{val, count}]}

    """
    bin_width = (hi - lo) / bins
    sparse_bins = db.calibration_state.get_sparse_histogram(model_key=model_key, label=label, lo=lo, hi=hi, bins=bins)
    if not sparse_bins:
        logger.warning(f"[calibration] No data for {model_key}:{head_name}:{label}")
        return {"p5": lo, "p95": hi, "n": 0, "underflow_count": 0, "overflow_count": 0, "histogram_bins": []}

    result = derive_percentiles_from_sparse_histogram(sparse_bins=sparse_bins, lo=lo, hi=hi, bin_width=bin_width, p5_target=0.05, p95_target=0.95)

    # Transform sparse_bins to storage format: [{val: float, count: int}]
    histogram_bins = [{"val": b["min_val"], "count": b["count"]} for b in sparse_bins]
    result["histogram_bins"] = histogram_bins

    logger.info(f"[calibration] {model_key}:{head_name}:{label} -> p5={result['p5']:.4f}, p95={result['p95']:.4f}, n={result['n']}, bins={len(histogram_bins)}")
    return result

def export_calibration_state_to_json(db: Database, output_path: str) -> dict[str, Any]:
    """Export all calibration_state documents to a single JSON file.

    Exports the full calibration state collection for backup or distribution.
    The JSON file can be imported into another Nomarr instance.

    Args:
        db: Database instance
        output_path: Absolute path to output JSON file

    Returns:
        Dict with export summary: {"calibrations_exported": int, "path": str}

    Raises:
        IOError: If file cannot be written

    """
    logger.info(f"[calibration] Exporting calibration_state to {output_path}")
    calibrations = db.calibration_state.get_all_calibration_states()
    export_data = []
    for calib in calibrations:
        export_doc = {"model_key": calib["model_key"], "head_name": calib["head_name"], "calibration_def_hash": calib["calibration_def_hash"], "version": calib.get("version", 1), "histogram": calib["histogram"], "p5": calib["p5"], "p95": calib["p95"], "n": calib["n"], "underflow_count": calib.get("underflow_count", 0), "overflow_count": calib.get("overflow_count", 0), "updated_at": calib.get("updated_at"), "last_computation_at": calib.get("last_computation_at")}
        export_data.append(export_doc)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "format": "nomarr_calibration_state", "calibrations": export_data}, f, indent=2)
    logger.info(f"[calibration] Exported {len(export_data)} calibrations to {output_path}")
    return {"calibrations_exported": len(export_data), "path": output_path}

def import_calibration_state_from_json(db: Database, input_path: str, overwrite: bool=False) -> dict[str, Any]:
    """Import calibration_state documents from a JSON file.

    Imports calibrations exported by export_calibration_state_to_json().
    By default, skips calibrations that already exist (based on calibration_def_hash).

    Args:
        db: Database instance
        input_path: Absolute path to input JSON file
        overwrite: If True, overwrite existing calibrations. If False, skip existing.

    Returns:
        Dict with import summary: {"calibrations_imported": int, "skipped": int}

    Raises:
        ValueError: If file format is invalid
        IOError: If file cannot be read

    """
    logger.info(f"[calibration] Importing calibration_state from {input_path}")
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or data.get("format") != "nomarr_calibration_state":
        msg = "Invalid calibration export format"
        raise ValueError(msg)
    calibrations = data.get("calibrations", [])
    if not isinstance(calibrations, list):
        msg = "Invalid calibrations field in export file"
        raise ValueError(msg)
    imported_count = 0
    skipped_count = 0
    for calib in calibrations:
        try:
            model_key = calib["model_key"]
            head_name = calib["head_name"]
            label = calib["label"]
            calibration_def_hash = calib["calibration_def_hash"]
            existing = db.calibration_state.get_calibration_state(model_key, head_name, label)
            if existing and (not overwrite) and (existing.get("calibration_def_hash") == calibration_def_hash):
                logger.debug(f"[calibration] Skipping {model_key}:{head_name}:{label} (already exists)")
                skipped_count += 1
                continue
            db.calibration_state.upsert_calibration_state(model_key=model_key, head_name=head_name, label=label, calibration_def_hash=calibration_def_hash, version=calib.get("version", 1), histogram_spec=calib["histogram"], p5=calib["p5"], p95=calib["p95"], sample_count=calib["n"], underflow_count=calib.get("underflow_count", 0), overflow_count=calib.get("overflow_count", 0))
            logger.info(f"[calibration] Imported {model_key}:{head_name}:{label}")
            imported_count += 1
        except KeyError as e:
            logger.warning(f"[calibration] Skipping invalid calibration entry (missing {e})")
            skipped_count += 1
            continue
        except Exception as e:
            logger.exception(f"[calibration] Failed to import calibration: {e}")
            skipped_count += 1
            continue
    logger.info(f"[calibration] Import complete: {imported_count} imported, {skipped_count} skipped")
    return {"calibrations_imported": imported_count, "skipped": skipped_count}

def compute_global_calibration_hash(calibration_states: list[dict[str, Any]]) -> str:
    """Compute global calibration version hash from all calibration states.

    This hash changes whenever any head's calibration changes (version bump,
    p5/p95 update, etc). Used to detect if files need recalibration.

    Args:
        calibration_states: List of calibration_state documents

    Returns:
        MD5 hash representing the combined calibration version

    """
    import hashlib
    sorted_states = sorted(calibration_states, key=lambda x: x.get("_key", ""))
    hash_parts = []
    for state in sorted_states:
        _key = state.get("_key", "")
        calib_hash = state.get("calibration_def_hash", "")
        hash_parts.append(f"{_key}:{calib_hash}")
    combined = "|".join(hash_parts)
    return hashlib.md5(combined.encode()).hexdigest()
