"""
File recalibration workflow.

This workflow applies calibration to existing library files without re-running ML inference.
It loads raw tag scores from the database, applies calibration transformations, and writes
updated tier and mood tags back to the audio file.

ARCHITECTURE:
- This is a PURE WORKFLOW that orchestrates: DB reads, calibration application, file writes
- It does NOT import services, interfaces, or the application object
- Callers must provide all dependencies: db, models_dir, namespace, calibrate_heads flag

EXPECTED DEPENDENCIES:
- `db: Database` - Database instance with library and conn accessors
- `models_dir: str` - Path to models directory (for loading calibration sidecars)
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

import logging
from typing import TYPE_CHECKING

from nomarr.tagging.aggregation import aggregate_mood_tiers, load_calibrations
from nomarr.tagging.writer import TagWriter

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def recalibrate_file_workflow(
    db: Database,
    file_path: str,
    models_dir: str,
    namespace: str = "nom",
    calibrate_heads: bool = False,
) -> None:
    """
    Recalibrate a single file by applying calibration to existing raw tags.

    This workflow:
    1. Loads calibrations from models directory (versioned or reference)
    2. Retrieves raw tag scores from library_tags table
    3. Applies calibration and regenerates mood tiers
    4. Writes updated tier and mood tags to the audio file

    This is much faster than retagging because it skips ML inference entirely,
    using the raw scores already stored in the database.

    Args:
        db: Database instance (must provide library, conn accessors)
        file_path: Absolute path to audio file to recalibrate
        models_dir: Path to models directory containing calibration sidecars
        namespace: Tag namespace (default: "nom")
        calibrate_heads: If True, use versioned calibration files (dev mode);
                        if False, use reference calibration files (production)

    Returns:
        None (updates file tags in-place)

    Raises:
        FileNotFoundError: If file not found in library database
        Exception: On calibration load or tag write failure

    Example:
        >>> recalibrate_file_workflow(
        ...     db=my_db, file_path="/music/song.mp3", models_dir="/app/models", namespace="nom", calibrate_heads=False
        ... )
    """
    logging.debug(f"[recalibration_workflow] Processing {file_path}")

    # Load calibrations from models directory
    # Use versioned files in dev mode (calibrate_heads=True), reference files otherwise
    calibrations = load_calibrations(models_dir, calibrate_heads=calibrate_heads)

    # Get file from library
    library_file = db.library.get_library_file(file_path)
    if not library_file:
        raise FileNotFoundError(f"File not in library: {file_path}")

    file_id = library_file["id"]

    # Get all raw tags for this file from library_tags (filtered by namespace)
    raw_tags = db.tags.get_file_tags_by_prefix(file_id, f"{namespace}:")

    if not raw_tags:
        logging.warning(f"[recalibration_workflow] No raw tags found for {file_path}")
        return

    # Apply calibration and regenerate mood tiers
    # Note: aggregate_mood_tiers mutates tags dict in-place
    aggregate_mood_tiers(raw_tags, calibrations=calibrations)

    # Only update tier and mood aggregation tags in the file
    # (Keep all raw score tags unchanged)
    tier_and_mood_keys = {
        f"{namespace}:mood-strict",
        f"{namespace}:mood-regular",
        f"{namespace}:mood-loose",
    }

    # Add all *_tier tags
    for key in raw_tags:
        if key.endswith("_tier"):
            tier_and_mood_keys.add(key)

    # Filter to only tier/mood tags
    tags_to_update = {k: v for k, v in raw_tags.items() if k in tier_and_mood_keys}

    if not tags_to_update:
        logging.debug(f"[recalibration_workflow] No tier tags to update for {file_path}")
        return

    # Strip namespace prefix from keys for TagWriter
    # TagWriter expects keys without namespace (it adds it internally)
    tags_without_namespace = {}
    for key, value in tags_to_update.items():
        # Remove 'namespace:' prefix
        if key.startswith(f"{namespace}:"):
            clean_key = key[len(namespace) + 1 :]
            tags_without_namespace[clean_key] = value

    # Write updated tags to file using TagWriter (handles all formats)
    writer = TagWriter(overwrite=True, namespace=namespace)
    writer.write(file_path, tags_without_namespace)

    logging.debug(f"[recalibration_workflow] Updated {len(tags_without_namespace)} tags in {file_path}")
