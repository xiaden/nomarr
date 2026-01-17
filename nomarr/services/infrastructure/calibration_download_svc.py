"""
Calibration bundle download service - fetch pre-made calibration bundles from GitHub.

ARCHITECTURE:
- Bundles are TRANSPORT ARTIFACTS for distribution (e.g., from nom-cal repo)
- Database (calibration_state) is the SINGLE SOURCE OF TRUTH
- This service downloads bundles → calls import_calibration_bundle_wf → upserts to DB

WORKFLOW:
1. Check local models directory for missing bundle files
2. Download missing bundles from nom-cal repository
3. Import bundles to database via import_calibration_bundle_wf
4. Production code uses calibration_loader_wf to read from DB

USAGE:
- For users with calibrate_heads=false (default)
- Downloads reference bundles instead of generating locally
- Post-download, all processing uses DB exclusively
"""

from __future__ import annotations

import logging
import os
from typing import Any

from nomarr.helpers.dto.calibration_dto import EnsureCalibrationsExistResult

logger = logging.getLogger(__name__)


def download_calibrations(repo_url: str, models_dir: str) -> dict[str, Any]:
    """
    Download pre-made calibration bundles from GitHub repository.

    NOTE: After download, bundles must be imported to database via
    import_calibration_bundle_wf before use. This function only handles
    the download step (transport artifact acquisition).

    Checks local models directory for missing bundle files and downloads
    them from the specified repository.

    Args:
        repo_url: GitHub repository URL (e.g., "https://github.com/xiaden/nom-cal")
        models_dir: Path to local models directory

    Returns:
        Dict with download results:
            - checked: Number of heads checked
            - downloaded: Number of files downloaded
            - already_exist: Number of files already present
            - errors: List of error messages

    Raises:
        NotImplementedError: Feature not yet implemented (stub)

    Example:
        >>> download_calibrations("https://github.com/xiaden/nom-cal", "/app/models")
        NotImplementedError: Calibration bundle download not yet implemented
    """
    logger.info(f"[calibration_download] Checking for missing calibration bundle files in {models_dir}")

    # This is a stub implementation
    # TODO: Implement actual download logic
    # TODO: After download, call import_calibration_bundle_wf to import to DB
    raise NotImplementedError(
        "Calibration bundle download feature is not yet implemented.\n\n"
        "To use nomarr without local calibration generation:\n"
        "1. Manually download calibration files from the repository:\n"
        f"   {repo_url}\n"
        "2. Place them in your models directory structure:\n"
        "   models/effnet/heads/<head_name>-calibration.json\n"
        "   models/yamnet/heads/<head_name>-calibration.json\n"
        "3. Restart the application\n\n"
        "OR enable calibration generation mode:\n"
        "1. Set calibrate_heads: true in config.yaml\n"
        "2. Tag your library (minimum 1000 files recommended)\n"
        "3. Run calibration generation via API endpoint\n"
        "4. Use generated calibration files\n\n"
        "See documentation for more details: docs/CALIBRATION.md"
    )


def check_missing_calibrations(models_dir: str) -> list[dict[str, str]]:
    """
    Check which heads are missing calibration files.

    Scans models directory to find all heads and checks if each has
    a calibration.json (or calibration-v*.json) file.

    Args:
        models_dir: Path to models directory

    Returns:
        List of dicts with missing calibration info:
            - model: Model name (e.g., "effnet")
            - head: Head name (e.g., "mood_happy")
            - path: Expected calibration file path

    Example:
        >>> check_missing_calibrations("/app/models")
        [
            {"model": "effnet", "head": "mood_happy", "path": "/app/models/effnet/heads/mood_happy-calibration.json"},
            ...
        ]
    """
    from nomarr.components.ml.ml_discovery_comp import discover_heads

    logger.info(f"[calibration_download] Scanning for heads in {models_dir}")

    # Discover all heads
    heads = discover_heads(models_dir)

    missing = []

    for head in heads:
        # Determine expected calibration file path
        model_path = head.sidecar.path
        model_dir = os.path.dirname(model_path)
        model_base = os.path.basename(model_path).rsplit(".", 1)[0]

        # Check for calibration.json (reference file)
        calib_path = os.path.join(model_dir, f"{model_base}-calibration.json")

        if not os.path.exists(calib_path):
            # Also check for versioned files (calibration-v*.json)
            has_versioned = any(
                f.startswith(f"{model_base}-calibration-v") and f.endswith(".json") for f in os.listdir(model_dir)
            )

            if not has_versioned:
                missing.append(
                    {
                        "model": head.backbone,
                        "head": head.sidecar.data.get("name", model_base),
                        "path": calib_path,
                    }
                )

    logger.info(f"[calibration_download] Found {len(missing)} heads without calibration files")

    return missing


def ensure_calibrations_exist(
    repo_url: str, models_dir: str, auto_download: bool = False
) -> EnsureCalibrationsExistResult:
    """
    Ensure calibration files exist, optionally downloading if missing.

    This is the main entry point for calibration availability checking.
    Called during application startup to verify calibrations are available.

    Args:
        repo_url: GitHub repository URL for calibration files
        models_dir: Path to local models directory
        auto_download: If True, automatically download missing files (not yet implemented)

    Returns:
        EnsureCalibrationsExistResult DTO

    Example:
        >>> ensure_calibrations_exist("https://github.com/xiaden/nom-cal", "/app/models")
        EnsureCalibrationsExistResult(has_calibrations=False, missing_count=5, ...)
    """
    logger.info("[calibration_download] Checking calibration availability")

    missing = check_missing_calibrations(models_dir)

    if not missing:
        logger.info("[calibration_download] All heads have calibration bundle files")
        return EnsureCalibrationsExistResult(
            has_calibrations=True,
            missing_count=0,
            missing_heads=[],
            action_required=None,
        )

    logger.warning(f"[calibration_download] {len(missing)} heads missing calibration bundle files")

    if auto_download:
        logger.info("[calibration_download] Attempting automatic download...")
        try:
            download_calibrations(repo_url, models_dir)
        except NotImplementedError as e:
            logger.warning(f"[calibration_download] Auto-download not available: {e}")

    return EnsureCalibrationsExistResult(
        has_calibrations=False,
        missing_count=len(missing),
        missing_heads=missing,
        action_required=(
            f"Download calibration bundles from {repo_url} and import via "
            f"import_calibration_bundle_wf, or enable calibrate_heads mode in config"
        ),
    )
