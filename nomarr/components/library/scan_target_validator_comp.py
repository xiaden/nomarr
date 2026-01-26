"""
Scan target validation component.

Validates scan targets and resolves them to absolute paths.
"""

from __future__ import annotations

import logging
from pathlib import Path

from nomarr.helpers.dto import ScanTarget

logger = logging.getLogger(__name__)


def validate_scan_targets(
    scan_targets: list[ScanTarget],
    library_root: Path,
) -> list[Path]:
    """
    Validate scan targets and return valid absolute paths.

    Args:
        scan_targets: List of scan targets (empty folder_path = library root)
        library_root: Absolute library root path

    Returns:
        List of valid absolute paths ready for scanning
    """
    valid_paths: list[Path] = []

    for target in scan_targets:
        target_path = library_root / target.folder_path if target.folder_path else library_root

        if not target_path.exists():
            logger.warning(f"Scan target does not exist: {target_path}")
            continue

        if not target_path.is_dir():
            logger.warning(f"Scan target is not a directory: {target_path}")
            continue

        # Verify reachability by attempting a directory listing
        try:
            # Cheap check: just try to list the directory
            next(target_path.iterdir(), None)
        except PermissionError:
            logger.warning(f"Scan target is not accessible (permission denied): {target_path}")
            continue
        except OSError as e:
            logger.warning(f"Scan target is not accessible (mount/IO error): {target_path} - {e}")
            continue

        valid_paths.append(target_path)

    return valid_paths
