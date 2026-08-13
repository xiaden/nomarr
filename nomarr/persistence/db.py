"""Database connection and session management for PostgreSQL.

Provides the :class:`Database` facade that creates a SQLAlchemy engine,
scoped session, and all repository instances, and exposes the ``app``,
``library``, and ``ml`` sub-facades.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import scoped_session

from nomarr.persistence.database.app_repo import AppRepository
from nomarr.persistence.database.calibration_repo import CalibrationRepo
from nomarr.persistence.database.embedding_stream_repo import EmbeddingStreamRepository
from nomarr.persistence.database.folder_repo import FolderRepository
from nomarr.persistence.database.library_repo import LibraryRepository
from nomarr.persistence.database.model_repo import ModelRepo
from nomarr.persistence.database.navidrome_repo import NavidromeRepo
from nomarr.persistence.database.output_repo import OutputRepo
from nomarr.persistence.database.pipeline_repo import PipelineRepository
from nomarr.persistence.database.scan_repo import ScanRepository
from nomarr.persistence.database.song_repo import SongRepository
from nomarr.persistence.database.song_state_repo import SongStateRepository
from nomarr.persistence.database.song_tag_repo import SongTagRepository
from nomarr.persistence.database.tag_repo import TagRepository
from nomarr.persistence.database.vector_repo import VectorRepo
from nomarr.persistence.pg_engine import create_pg_engine, session_factory

logger = logging.getLogger(__name__)


class Database:
    """PostgreSQL database facade.

    Creates a SQLAlchemy engine and scoped session, instantiates all
    repository classes, and exposes the ``app``, ``library``, and ``ml``
    sub-facades for application, library, and ML operations.
    """

    def __init__(
        self,
        *,
        url: str,
        echo: bool = False,
        pool_size: int = 5,
        max_overflow: int = 10,
    ) -> None:
        """Initialize PostgreSQL connection and all repositories.

        Args:
            url: PostgreSQL connection URL (e.g., ``postgresql+psycopg2://...``).
            echo: If ``True``, log all SQL statements.
            pool_size: Connection pool size.
            max_overflow: Max overflow connections beyond pool_size.

        """
        self._url = url
        self._echo = echo

        # Create engine and scoped session
        self._pg_engine = create_pg_engine(
            url,
            echo=echo,
            pool_size=pool_size,
            max_overflow=max_overflow,
        )
        _factory = session_factory(self._pg_engine)
        self._scoped = scoped_session(_factory)

        # Instantiate all repositories
        self._app_repo = AppRepository(self._scoped)
        self._scan_repo = ScanRepository(self._scoped)
        self._library_repo = LibraryRepository(self._scoped)
        self._navidrome_repo = NavidromeRepo(self._scoped)
        self._song_state_repo = SongStateRepository(self._scoped)
        self._pipeline_repo = PipelineRepository(self._scoped)
        self._song_repo = SongRepository(self._scoped)
        self._folder_repo = FolderRepository(self._scoped)
        self._tag_repo = TagRepository(self._scoped)
        self._song_tag_repo = SongTagRepository(self._scoped)
        self._vector_repo = VectorRepo(self._scoped)
        self._model_repo = ModelRepo(self._scoped)
        self._output_repo = OutputRepo(self._scoped)
        self._calibration_repo = CalibrationRepo(self._scoped)
        self._embedding_stream_repo = EmbeddingStreamRepository(self._scoped)

        # Import here to avoid circular imports
        from nomarr.persistence.api.application import AppDb
        from nomarr.persistence.api.library import LibraryDb
        from nomarr.persistence.api.library_regions import LibraryRegionsDb
        from nomarr.persistence.api.library_scans import LibraryScansDb
        from nomarr.persistence.api.library_songs import LibrarySongsDb
        from nomarr.persistence.api.library_tags import LibraryTagsDb
        from nomarr.persistence.api.ml import MlDb

        # Create sub-facades
        self.app = AppDb(
            session=self._scoped,
            app_repo=self._app_repo,
            library_repo=self._library_repo,
            navidrome_repo=self._navidrome_repo,
            song_state_repo=self._song_state_repo,
            pipeline_repo=self._pipeline_repo,
        )
        songs = LibrarySongsDb(
            session=self._scoped,
            song_repo=self._song_repo,
            folder_repo=self._folder_repo,
            song_state_repo=self._song_state_repo,
        )
        tags = LibraryTagsDb(
            session=self._scoped,
            tag_repo=self._tag_repo,
            song_tag_repo=self._song_tag_repo,
        )
        scans = LibraryScansDb(session=self._scoped, scan_repo=self._scan_repo)
        regions = LibraryRegionsDb(
            session=self._scoped,
            library_repo=self._library_repo,
            song_state_repo=self._song_state_repo,
        )
        self.library = LibraryDb(
            session=self._scoped,
            songs=songs,
            tags=tags,
            scans=scans,
            regions=regions,
        )
        self.ml = MlDb(
            session=self._scoped,
            vector_repo=self._vector_repo,
            model_repo=self._model_repo,
            output_repo=self._output_repo,
            calibration_repo=self._calibration_repo,
            embedding_stream_repo=self._embedding_stream_repo,
        )

    def close(self) -> None:
        """Remove the scoped session and dispose the PostgreSQL engine."""
        self._scoped.remove()
        self._pg_engine.dispose()

    def get_version(self) -> str | None:
        """Return the current schema version from the config table."""
        return self.app.get_schema_version()

    def set_version(self, version: str) -> None:
        """Update the schema version in the config table."""
        self.app.update_config_option("version", {"value": version})
