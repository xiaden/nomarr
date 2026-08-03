"""SQLAlchemy ORM models for PostgreSQL persistence layer."""

from nomarr.persistence.models.applied_migration import AppliedMigration
from nomarr.persistence.models.base import Base
from nomarr.persistence.models.calibration_history import CalibrationHistory
from nomarr.persistence.models.calibration_state import CalibrationState
from nomarr.persistence.models.embedding import Embedding
from nomarr.persistence.models.file_state import FileState
from nomarr.persistence.models.file_state_assignment import FileStateAssignment
from nomarr.persistence.models.file_tag import SongTag
from nomarr.persistence.models.health import Health
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.library_file import LibraryFile
from nomarr.persistence.models.library_folder import LibraryFolder
from nomarr.persistence.models.library_scan import LibraryScan
from nomarr.persistence.models.lock import Lock
from nomarr.persistence.models.meta import Meta
from nomarr.persistence.models.ml_embedding_stream import MlEmbeddingStream
from nomarr.persistence.models.ml_model import MlModel
from nomarr.persistence.models.ml_model_output import MlModelOutput
from nomarr.persistence.models.ml_output_stream import MlOutputStream
from nomarr.persistence.models.navidrome_play import NavidromePlay
from nomarr.persistence.models.navidrome_play_map import NavidromePlayMap
from nomarr.persistence.models.navidrome_track import NavidromeTrack
from nomarr.persistence.models.navidrome_track_map import NavidromeTrackMap
from nomarr.persistence.models.pipeline_state import PipelineState
from nomarr.persistence.models.session import Session
from nomarr.persistence.models.tag import Tag
from nomarr.persistence.models.vram_promise import VramPromise
from nomarr.persistence.models.worker_claim import WorkerClaim
from nomarr.persistence.models.worker_restart_policy import WorkerRestartPolicy

__all__ = [
    "AppliedMigration",
    "Base",
    "CalibrationHistory",
    "CalibrationState",
    "Embedding",
    "FileState",
    "FileStateAssignment",
    "Health",
    "Library",
    "LibraryFile",
    "LibraryFolder",
    "LibraryScan",
    "Lock",
    "Meta",
    "MlEmbeddingStream",
    "MlModel",
    "MlModelOutput",
    "MlOutputStream",
    "NavidromePlay",
    "NavidromePlayMap",
    "NavidromeTrack",
    "NavidromeTrackMap",
    "PipelineState",
    "Session",
    "SongTag",
    "Tag",
    "VramPromise",
    "WorkerClaim",
    "WorkerRestartPolicy",
]
