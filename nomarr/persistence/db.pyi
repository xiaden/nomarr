from __future__ import annotations

from typing import Any

from nomarr.persistence.stubs.calibration_history import CalibrationHistoryNamespace
from nomarr.persistence.stubs.calibration_state import CalibrationStateNamespace
from nomarr.persistence.stubs.file_has_segment_stats import FileHasSegmentStatsNamespace
from nomarr.persistence.stubs.file_has_state import FileHasStateNamespace
from nomarr.persistence.stubs.file_has_vectors import FileHasVectorsNamespace
from nomarr.persistence.stubs.file_states import FileStatesNamespace
from nomarr.persistence.stubs.has_nd_id import HasNdIdNamespace
from nomarr.persistence.stubs.has_plays import HasPlaysNamespace
from nomarr.persistence.stubs.health import HealthNamespace
from nomarr.persistence.stubs.libraries import LibrariesNamespace
from nomarr.persistence.stubs.library_contains_file import LibraryContainsFileNamespace
from nomarr.persistence.stubs.library_contains_folder import LibraryContainsFolderNamespace
from nomarr.persistence.stubs.library_files import LibraryFilesNamespace
from nomarr.persistence.stubs.library_folders import LibraryFoldersNamespace
from nomarr.persistence.stubs.library_has_pipeline_state import LibraryHasPipelineStateNamespace
from nomarr.persistence.stubs.library_has_scan import LibraryHasScanNamespace
from nomarr.persistence.stubs.library_pipeline_states import LibraryPipelineStatesNamespace
from nomarr.persistence.stubs.library_scans import LibraryScansNamespace
from nomarr.persistence.stubs.locks import LocksNamespace
from nomarr.persistence.stubs.meta import MetaNamespace
from nomarr.persistence.stubs.migrations import MigrationsNamespace
from nomarr.persistence.stubs.ml_capacity import MlCapacityNamespace
from nomarr.persistence.stubs.ml_model_outputs import MlModelOutputsNamespace
from nomarr.persistence.stubs.ml_models import MlModelsNamespace
from nomarr.persistence.stubs.model_has_calibration import ModelHasCalibrationNamespace
from nomarr.persistence.stubs.model_has_output import ModelHasOutputNamespace
from nomarr.persistence.stubs.navidrome_playcounts import NavidromePlaycountsNamespace
from nomarr.persistence.stubs.navidrome_tracks import NavidromeTracksNamespace
from nomarr.persistence.stubs.segment_scores_stats import SegmentScoresStatsNamespace
from nomarr.persistence.stubs.sessions import SessionsNamespace
from nomarr.persistence.stubs.song_has_tags import SongHasTagsNamespace
from nomarr.persistence.stubs.tag_model_output import TagModelOutputNamespace
from nomarr.persistence.stubs.tags import TagsNamespace
from nomarr.persistence.stubs.vram_promises import VramPromisesNamespace
from nomarr.persistence.stubs.worker_claims import WorkerClaimsNamespace
from nomarr.persistence.stubs.worker_restart_policy import WorkerRestartPolicyNamespace

class Database:
    calibration_history: CalibrationHistoryNamespace
    calibration_state: CalibrationStateNamespace
    file_has_segment_stats: FileHasSegmentStatsNamespace
    file_has_state: FileHasStateNamespace
    file_has_vectors: FileHasVectorsNamespace
    file_states: FileStatesNamespace
    has_nd_id: HasNdIdNamespace
    has_plays: HasPlaysNamespace
    health: HealthNamespace
    libraries: LibrariesNamespace
    library_contains_file: LibraryContainsFileNamespace
    library_contains_folder: LibraryContainsFolderNamespace
    library_files: LibraryFilesNamespace
    library_folders: LibraryFoldersNamespace
    library_has_pipeline_state: LibraryHasPipelineStateNamespace
    library_has_scan: LibraryHasScanNamespace
    library_pipeline_states: LibraryPipelineStatesNamespace
    library_scans: LibraryScansNamespace
    locks: LocksNamespace
    meta: MetaNamespace
    migrations: MigrationsNamespace
    ml_capacity: MlCapacityNamespace
    ml_model_outputs: MlModelOutputsNamespace
    ml_models: MlModelsNamespace
    model_has_calibration: ModelHasCalibrationNamespace
    model_has_output: ModelHasOutputNamespace
    navidrome_playcounts: NavidromePlaycountsNamespace
    navidrome_tracks: NavidromeTracksNamespace
    segment_scores_stats: SegmentScoresStatsNamespace
    sessions: SessionsNamespace
    song_has_tags: SongHasTagsNamespace
    tag_model_output: TagModelOutputNamespace
    tags: TagsNamespace
    vram_promises: VramPromisesNamespace
    worker_claims: WorkerClaimsNamespace
    worker_restart_policy: WorkerRestartPolicyNamespace

    # Private attributes
    _template_namespaces: dict[str, Any]

    USERNAME: str
    DB_NAME: str

    # Instance attributes set in __init__
    db: Any  # SafeDatabase — raw python-arango database handle
    hosts: str | None
    password: str | None
    username: str
    db_name: str

    def __init__(self, hosts: str | None = ..., password: str | None = ...) -> None: ...
    def register(self, collection_name: str, template_name: str) -> Any: ...
    def get_version(self) -> str | None: ...
    def set_version(self, version: str) -> None: ...
    def close(self) -> None: ...
