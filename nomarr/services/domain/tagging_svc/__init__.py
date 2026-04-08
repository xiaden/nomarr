"""Tagging service package."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.recalibration_dto import ApplyCalibrationResult

from .apply import TaggingApplyMixin
from .config import CALIBRATION_APPLY_TASK_ID, ApplyCalibrationCombinedStatusDict, TaggingServiceConfig
from .curation import TaggingCurationMixin
from .query import TaggingQueryMixin
from .write import TaggingWriteMixin

if TYPE_CHECKING:
    from nomarr.persistence.db import Database
    from nomarr.services.domain.library_svc import LibraryService
    from nomarr.services.infrastructure.background_tasks_svc import BackgroundTaskService
    from nomarr.services.infrastructure.config_svc import ConfigService


class TaggingService(TaggingApplyMixin, TaggingWriteMixin, TaggingCurationMixin, TaggingQueryMixin):
    """Service for writing calibrated tags to library files.

    This service provides methods to apply calibration to files.
    It updates tier and mood tags by applying calibration to raw scores
    already stored in the database, without re-running ML inference.

    Architecture note:
    - Service provides API surface and DI
    - Actual tagging logic lives in workflows/calibration/write_calibrated_tags_wf.py
    - Background execution is managed via BackgroundTaskService (BTS), scoped to this service
    """

    def __init__(
        self,
        database: Database,
        cfg: TaggingServiceConfig,
        bts: BackgroundTaskService,
        config_service: ConfigService,
        library_service: LibraryService | None = None,
    ) -> None:
        """Initialize the tagging service.

        Args:
            database: Database instance for persistence operations
            cfg: Service configuration (models_dir, namespace, etc.)
            bts: BackgroundTaskService for managed background task execution
            config_service: Live configuration provider (for calibrate_heads)
            library_service: LibraryService instance (optional, for library operations)

        """
        self.db = database
        self.cfg = cfg
        self._bts = bts
        self._config_service = config_service
        self.library_service = library_service

        self._apply_result: ApplyCalibrationResult | None = None
        self._apply_error: Exception | None = None
        self._apply_progress_lock = threading.Lock()
        self._apply_progress: dict[str, Any] = {}

    @property
    def namespace(self) -> str:
        """Get the tag namespace from library service config."""
        if self.library_service is None:
            msg = "LibraryService not configured. Cannot determine namespace."
            raise ValueError(msg)
        return self.library_service.cfg.namespace


__all__ = [
    "CALIBRATION_APPLY_TASK_ID",
    "ApplyCalibrationCombinedStatusDict",
    "TaggingService",
    "TaggingServiceConfig",
]
