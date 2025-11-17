"""
File recalibration workflow.

This workflow applies calibration to existing library files without re-running ML inference.
It reconstructs HeadOutput objects from stored numeric tags and calibration metadata,
then re-runs aggregation to update mood-* tags.

ARCHITECTURE:
- This is a PURE WORKFLOW that orchestrates: DB reads, calibration application, file writes
- It does NOT import services, interfaces, or the application object
- Callers must provide all dependencies: db, models_dir, namespace, calibrate_heads flag

EXPECTED DEPENDENCIES:
- `db: Database` - Database instance with library and conn accessors
- `models_dir: str` - Path to models directory (for loading calibration sidecars and head metadata)
- `namespace: str` - Tag namespace (e.g., "nom")
- `calibrate_heads: bool` - Whether to use versioned calibration files (dev mode)

USAGE:
    from nomarr.workflows.recalibrate_file import recalibrate_file_workflow

    recalibrate_file_workflow(
        db=database_instance,
        file_path="/path/to/audio.mp3",
        models_dir="/app/models",
        namespace="nom",
        calibrate_heads=False
    )
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from nomarr.ml.models.discovery import HeadOutput, discover_heads
from nomarr.tagging.aggregation import aggregate_mood_tiers, load_calibrations
from nomarr.tagging.writer import TagWriter

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def _load_library_state(
    db: Database,
    file_path: str,
    namespace: str,
) -> tuple[int, dict[str, Any], dict[str, str]]:
    """
    Load file metadata and tags from library database.

    Args:
        db: Database instance
        file_path: Path to audio file
        namespace: Tag namespace

    Returns:
        Tuple of (file_id, all_tags, calibration_map)

    Raises:
        FileNotFoundError: If file not found in library database
    """
    # Get file from library
    library_file = db.library.get_library_file(file_path)
    if not library_file:
        raise FileNotFoundError(f"File not in library: {file_path}")

    file_id = library_file["id"]

    # Load calibration metadata (model_key -> calibration_id mapping)
    calibration_json = library_file.get("calibration")
    calibration_map: dict[str, str] = {}
    if calibration_json:
        try:
            calibration_map = json.loads(calibration_json) if isinstance(calibration_json, str) else calibration_json
        except Exception as e:
            logging.warning(f"[recalibration] Failed to parse calibration metadata: {e}")

    # Get all numeric tags for this file from library_tags
    all_tags = db.tags.get_file_tags_by_prefix(file_id, f"{namespace}:")

    if not all_tags:
        logging.warning(f"[recalibration] No tags found for {file_path}")

    return file_id, all_tags, calibration_map


def _filter_numeric_tags(
    all_tags: dict[str, Any],
    version_tag_key: str,
) -> dict[str, float | int]:
    """
    Filter to numeric tags only, excluding mood-* and version tags.

    Args:
        all_tags: All tags for the file
        version_tag_key: Un-namespaced key for the tagger version tag (e.g., "nom_version")

    Returns:
        Dictionary of numeric tags only
    """

    def _is_version_key(key: str) -> bool:
        if not isinstance(key, str):
            return False
        # Raw (no namespace)
        if key == version_tag_key:
            return True
        # Namespaced form, e.g. "ns:nom_version"
        return ":" in key and key.split(":", 1)[1] == version_tag_key

    numeric_tags = {
        k: v
        for k, v in all_tags.items()
        if isinstance(v, (int, float))
        and not k.endswith(":mood-strict")
        and not k.endswith(":mood-regular")
        and not k.endswith(":mood-loose")
        and not _is_version_key(k)
    }

    if not numeric_tags:
        logging.warning("[recalibration] No numeric tags found")

    logging.debug(f"[recalibration] Found {len(numeric_tags)} numeric tags")

    return numeric_tags


def _discover_head_mappings(
    models_dir: str,
    namespace: str,
    numeric_tags: dict[str, float | int],
) -> dict[str, tuple[Any, str]]:
    """
    Discover heads and build mapping from tag keys to HeadInfo.

    Args:
        models_dir: Path to models directory
        namespace: Tag namespace
        numeric_tags: Numeric tags to match against heads

    Returns:
        Dictionary mapping tag_key -> (HeadInfo, label)

    Raises:
        ValueError: If no heads discovered
    """
    # Discover HeadInfo from models directory to get metadata
    heads = discover_heads(models_dir)
    if not heads:
        raise ValueError(f"No heads discovered in {models_dir}")

    # Build lookup: model_key -> HeadInfo
    head_by_model_key: dict[str, tuple[Any, str]] = {}  # model_key -> (HeadInfo, label)
    for head in heads:
        for label in head.labels:
            # Try to match tags to heads by checking if label appears in tag key
            # This is heuristic but works for versioned keys like "happy_essentia_v1_yamnet..."
            normalized_label = label.lower().replace(" ", "_")
            for tag_key in numeric_tags:
                # Strip namespace prefix for matching
                clean_key = tag_key[len(namespace) + 1 :] if tag_key.startswith(f"{namespace}:") else tag_key
                if normalized_label in clean_key.lower():
                    head_by_model_key[tag_key] = (head, label)

    logging.debug(f"[recalibration] Matched {len(head_by_model_key)} tags to heads")

    return head_by_model_key


def _load_calibrations(
    models_dir: str,
    calibrate_heads: bool,
) -> dict[str, Any]:
    """
    Load calibration sidecars from models directory.

    Args:
        models_dir: Path to models directory
        calibrate_heads: Whether to use versioned calibration files

    Returns:
        Dictionary of calibrations (may be empty)
    """
    calibrations = load_calibrations(models_dir, calibrate_heads=calibrate_heads)
    if calibrations:
        logging.info(f"[recalibration] Loaded calibrations for {len(calibrations)} labels")

    return calibrations


def _reconstruct_head_outputs(
    numeric_tags: dict[str, float | int],
    head_by_model_key: dict[str, tuple[Any, str]],
    calibration_map: dict[str, str],
    namespace: str,
    calibrations: dict[str, Any],
) -> list[HeadOutput]:
    """
    Reconstruct HeadOutput objects from numeric tags and calibration data.

    Args:
        numeric_tags: Numeric tags from database
        head_by_model_key: Mapping of tag_key -> (HeadInfo, label)
        calibration_map: Mapping of model_key -> calibration_id
        namespace: Tag namespace
        calibrations: Calibration parameters

    Returns:
        List of HeadOutput objects
    """
    head_outputs: list[HeadOutput] = []
    for tag_key, value in numeric_tags.items():
        if tag_key not in head_by_model_key:
            continue

        head_info, label = head_by_model_key[tag_key]

        # Strip namespace for clean key
        clean_key = tag_key[len(namespace) + 1 :] if tag_key.startswith(f"{namespace}:") else tag_key

        # Get calibration_id for this tag
        calib_id = calibration_map.get(clean_key)

        # Compute tier from value using calibration
        # For now, use simple thresholds (can be enhanced with actual calibration logic)
        tier: str | None = None
        if head_info.is_mood_source or head_info.is_regression_mood_source:
            # Apply calibration if available
            calibrated_value = value
            if calibrations and clean_key in calibrations:
                from nomarr.ml.calibration import apply_minmax_calibration

                calibrated_value = apply_minmax_calibration(value, calibrations[clean_key])

            # Compute tier based on calibrated value
            if calibrated_value >= 0.7:
                tier = "high"
            elif calibrated_value >= 0.5:
                tier = "medium"
            elif calibrated_value >= 0.3:
                tier = "low"

        head_outputs.append(
            HeadOutput(
                head=head_info,
                model_key=clean_key,
                label=label,
                value=value,
                tier=tier,
                calibration_id=calib_id,
            )
        )

    if not head_outputs:
        logging.warning("[recalibration] No HeadOutput objects reconstructed")

    logging.info(f"[recalibration] Reconstructed {len(head_outputs)} HeadOutput objects")

    return head_outputs


def _compute_mood_tags(
    head_outputs: list[HeadOutput],
    calibrations: dict[str, Any],
) -> dict[str, Any]:
    """
    Aggregate HeadOutput objects into mood-* tags.

    Args:
        head_outputs: List of HeadOutput objects
        calibrations: Calibration parameters

    Returns:
        Dictionary of mood tags
    """
    mood_tags = aggregate_mood_tiers(head_outputs, calibrations=calibrations)

    if not mood_tags:
        logging.debug("[recalibration] No mood tags generated")
    else:
        logging.info(f"[recalibration] Generated {len(mood_tags)} mood tags")

    return mood_tags


def _update_db_and_file(
    db: Database,
    file_id: int,
    file_path: str,
    namespace: str,
    mood_tags: dict[str, Any],
) -> None:
    """
    Update mood-* tags in database and file.

    Args:
        db: Database instance
        file_id: File ID in library
        file_path: Path to audio file
        namespace: Tag namespace
        mood_tags: Mood tags to write
    """
    # Build namespaced tags for DB
    namespaced_mood_tags = {f"{namespace}:{k}": v for k, v in mood_tags.items()}

    # Upsert mood tags in DB
    db.tags.upsert_file_tags(file_id, namespaced_mood_tags)

    logging.debug(f"[recalibration] Updated {len(namespaced_mood_tags)} mood tags in DB")

    # Write mood-* tags to file
    writer = TagWriter(overwrite=True, namespace=namespace)
    writer.write(file_path, mood_tags)

    logging.info(f"[recalibration] Recalibration complete for {file_path}")


def recalibrate_file_workflow(
    db: Database,
    file_path: str,
    models_dir: str,
    namespace: str,
    version_tag_key: str,
    calibrate_heads: bool = False,
) -> None:
    """
    Recalibrate a single file by applying calibration to existing numeric tags.

    This workflow:
    1. Loads numeric tags from DB (model_key -> value)
    2. Loads calibration metadata from library_files.calibration
    3. Discovers HeadInfo from models directory
    4. Reconstructs HeadOutput objects from tags + calibration
    5. Re-runs aggregation to compute mood-* tags
    6. Updates mood-* tags in DB and file

    This is much faster than retagging because it skips ML inference entirely,
    reusing the numeric scores already stored in the database.

    Args:
        db: Database instance (must provide library, tags accessors)
        file_path: Absolute path to audio file to recalibrate
        models_dir: Path to models directory containing calibration sidecars and head metadata
        namespace: Tag namespace (e.g., "nom")
        version_tag_key: Un-namespaced key for the tagger version tag (e.g., "nom_version")
        calibrate_heads: If True, use versioned calibration files (dev mode);
                        if False, use reference calibration files (production)

    Returns:
        None (updates file tags in-place)

    Raises:
        FileNotFoundError: If file not found in library database
        ValueError: If no heads discovered or no tags found

    Example:
        >>> recalibrate_file_workflow(
        ...     db=my_db,
        ...     file_path="/music/song.mp3",
        ...     models_dir="/app/models",
        ...     namespace="nom",
        ...     version_tag_key="nom_version",
        ...     calibrate_heads=False,
        ... )
    """
    logging.debug(f"[recalibration] Processing {file_path}")

    # Step 1: Load library state (file metadata, tags, calibration)
    file_id, all_tags, calibration_map = _load_library_state(db, file_path, namespace)

    if not all_tags:
        return

    # Step 2: Filter to numeric tags only
    numeric_tags = _filter_numeric_tags(all_tags, version_tag_key)

    if not numeric_tags:
        return

    # Step 3: Discover heads and build tag-to-head mappings
    head_by_model_key = _discover_head_mappings(models_dir, namespace, numeric_tags)

    # Step 4: Load calibration sidecars
    calibrations = _load_calibrations(models_dir, calibrate_heads)

    # Step 5: Reconstruct HeadOutput objects from tags and calibration
    head_outputs = _reconstruct_head_outputs(numeric_tags, head_by_model_key, calibration_map, namespace, calibrations)

    if not head_outputs:
        return

    # Step 6: Re-run aggregation to compute mood-* tags
    mood_tags = _compute_mood_tags(head_outputs, calibrations)

    if not mood_tags:
        return

    # Step 7: Update mood-* tags in database and file
    _update_db_and_file(db, file_id, file_path, namespace, mood_tags)
