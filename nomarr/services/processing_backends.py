"""
Processing backends for worker threads.

Each backend is a callable with signature: (path: str, force: bool) -> ProcessFileResult | dict[str, Any]
Backends can wrap coordinators (process pools) or run workflows directly.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.helpers.dto.processing_dto import ProcessFileResult
    from nomarr.persistence.db import Database
    from nomarr.services.coordinator_svc import CoordinatorService


ProcessingBackend = Callable[[str, bool], "ProcessFileResult | dict[str, Any]"]


def make_coordinator_backend(coordinator: CoordinatorService) -> ProcessingBackend:
    """
    Create a processing backend that delegates to a CoordinatorService (process pool).

    Args:
        coordinator: CoordinatorService instance (already started)

    Returns:
        Callable backend for worker process_fn
    """

    def backend(path: str, force: bool) -> ProcessFileResult | dict[str, Any]:
        return coordinator.submit(path, force)

    return backend


def make_tagger_backend(db: Database) -> ProcessingBackend:
    """
    Create a direct (non-pooled) processing backend for tagging workflow.
    Used when coordinator is not available.

    Args:
        db: Database instance

    Returns:
        Callable backend for worker process_fn
    """

    def backend(path: str, force: bool) -> ProcessFileResult | dict[str, Any]:
        from nomarr.services.config_svc import ConfigService
        from nomarr.workflows.processing.process_file_wf import process_file_workflow

        config_service = ConfigService()
        processor_config = config_service.make_processor_config()
        return process_file_workflow(path, config=processor_config, db=db)

    return backend


def make_scanner_backend(db: Database, namespace: str, auto_tag: bool, ignore_patterns: str) -> ProcessingBackend:
    """
    Create a processing backend for library scanning workflow.

    Args:
        db: Database instance
        namespace: Tag namespace
        auto_tag: Auto-enqueue for tagging
        ignore_patterns: Patterns to skip

    Returns:
        Callable backend for worker process_fn
    """

    def backend(path: str, force: bool) -> dict[str, Any]:
        from nomarr.helpers.dto.library_dto import ScanSingleFileWorkflowParams
        from nomarr.workflows.library.scan_single_file_wf import scan_single_file_workflow

        params = ScanSingleFileWorkflowParams(
            file_path=path,
            namespace=namespace,
            force=force,
            auto_tag=auto_tag,
            ignore_patterns=ignore_patterns,
            library_id=None,
        )
        return scan_single_file_workflow(db, params)

    return backend


def make_recalibration_backend(
    db: Database,
    models_dir: str,
    namespace: str,
    version_tag_key: str,
    calibrate_heads: bool,
) -> ProcessingBackend:
    """
    Create a processing backend for recalibration workflow.

    Args:
        db: Database instance
        models_dir: Path to models directory
        namespace: Tag namespace
        version_tag_key: Version tag key
        calibrate_heads: Use versioned calibration

    Returns:
        Callable backend for worker process_fn
    """

    def backend(path: str, force: bool) -> dict[str, Any]:
        from nomarr.helpers.dto.calibration_dto import RecalibrateFileWorkflowParams
        from nomarr.workflows.calibration.recalibrate_file_wf import recalibrate_file_workflow

        params = RecalibrateFileWorkflowParams(
            file_path=path,
            models_dir=models_dir,
            namespace=namespace,
            version_tag_key=version_tag_key,
            calibrate_heads=calibrate_heads,
        )
        recalibrate_file_workflow(db, params)
        return {"status": "success", "path": path}

    return backend


# ============================================================================
# Pooled Backends (for use in process pools via CoordinatorService)
# ============================================================================
# These must be top-level functions (not closures) to be picklable by multiprocessing.
# Each loads its own ConfigService and Database instance per process.


def pooled_tagger_backend(path: str, force: bool) -> ProcessFileResult | dict[str, Any]:
    """
    Pooled processing backend for tagging workflow.
    Loads config and workflows internally for process pool execution.

    Args:
        path: File path to process
        force: Force reprocessing flag

    Returns:
        ProcessFileResult or dict with results
    """
    import os

    from nomarr.services.config_svc import ConfigService
    from nomarr.workflows.processing.process_file_wf import process_file_workflow

    pid = os.getpid()
    import logging

    logging.info(f"[Worker PID {pid}] Tagger processing: {path}")

    try:
        config_service = ConfigService()
        processor_config = config_service.make_processor_config()
        result = process_file_workflow(path, config=processor_config, db=None)
        logging.info(f"[Worker PID {pid}] Tagger completed: {path}")
        return result
    except Exception as e:
        logging.error(f"[Worker PID {pid}] Tagger error for {path}: {e}")
        return {"error": str(e), "status": "error", "path": path}


def pooled_scanner_backend(path: str, force: bool) -> dict[str, Any]:
    """
    Pooled processing backend for library scanning workflow.
    Loads config, database, and workflows internally for process pool execution.

    Args:
        path: File path to scan
        force: Force rescan flag

    Returns:
        Dict with scan results
    """
    import os

    from nomarr.helpers.dto.library_dto import ScanSingleFileWorkflowParams
    from nomarr.persistence.db import Database
    from nomarr.services.config_svc import ConfigService
    from nomarr.workflows.library.scan_single_file_wf import scan_single_file_workflow

    pid = os.getpid()
    import logging

    logging.info(f"[Worker PID {pid}] Scanner processing: {path}")

    try:
        config_service = ConfigService()
        config = config_service.get_config().config
        db = Database(str(config["db_path"]))

        params = ScanSingleFileWorkflowParams(
            file_path=path,
            namespace=str(config.get("namespace", "nom")),
            force=force,
            auto_tag=bool(config.get("library_auto_tag", False)),
            ignore_patterns=str(config.get("library_ignore_patterns", "")),
            library_id=None,
        )

        result = scan_single_file_workflow(db, params)
        logging.info(f"[Worker PID {pid}] Scanner completed: {path}")
        return result
    except Exception as e:
        logging.error(f"[Worker PID {pid}] Scanner error for {path}: {e}")
        return {"error": str(e), "status": "error", "path": path}


def pooled_recalibration_backend(path: str, force: bool) -> dict[str, Any]:
    """
    Pooled processing backend for recalibration workflow.
    Loads config, database, and workflows internally for process pool execution.

    Args:
        path: File path to recalibrate
        force: Force reprocessing flag (unused for recalibration)

    Returns:
        Dict with recalibration results
    """
    import os

    from nomarr.helpers.dto.calibration_dto import RecalibrateFileWorkflowParams
    from nomarr.persistence.db import Database
    from nomarr.services.config_svc import ConfigService
    from nomarr.workflows.calibration.recalibrate_file_wf import recalibrate_file_workflow

    pid = os.getpid()
    import logging

    logging.info(f"[Worker PID {pid}] Recalibration processing: {path}")

    try:
        config_service = ConfigService()
        config = config_service.get_config().config
        db = Database(str(config["db_path"]))

        params = RecalibrateFileWorkflowParams(
            file_path=path,
            models_dir=str(config.get("models_dir", "models")),
            namespace=str(config.get("namespace", "nom")),
            version_tag_key=str(config.get("version_tag_key", "nom_version")),
            calibrate_heads=bool(config.get("calibrate_heads", False)),
        )

        recalibrate_file_workflow(db, params)
        logging.info(f"[Worker PID {pid}] Recalibration completed: {path}")
        return {"status": "success", "path": path}
    except Exception as e:
        logging.error(f"[Worker PID {pid}] Recalibration error for {path}: {e}")
        return {"error": str(e), "status": "error", "path": path}
