"""Database connection and session management for PostgreSQL.

Provides the :class:`Database` facade that creates a SQLAlchemy async engine,
session factory, and all repository instances. Also exposes lightweight
adapter classes (``_MigrationsAdapter``, ``_MlCapacityAdapter``,
``_VramPromisesAdapter``) that delegate to the async ``AppDb`` methods for
backward compatibility with sync callers.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.persistence.api.application import AppDb

from nomarr.persistence.database.app_repo import AppRepository
from nomarr.persistence.database.calibration_repo import CalibrationRepo
from nomarr.persistence.database.embedding_stream_repo import EmbeddingStreamRepository
from nomarr.persistence.database.file_repo import FileRepository
from nomarr.persistence.database.file_state_repo import FileStateRepository
from nomarr.persistence.database.file_tag_repo import FileTagRepository
from nomarr.persistence.database.folder_repo import FolderRepository
from nomarr.persistence.database.library_repo import LibraryRepository
from nomarr.persistence.database.model_repo import ModelRepo
from nomarr.persistence.database.navidrome_repo import NavidromeRepo
from nomarr.persistence.database.output_repo import OutputRepo
from nomarr.persistence.database.pipeline_repo import PipelineRepository
from nomarr.persistence.database.scan_repo import ScanRepository
from nomarr.persistence.database.tag_repo import TagRepository
from nomarr.persistence.database.vector_repo import VectorRepo
from nomarr.persistence.pg_engine import async_session_factory, create_pg_engine

logger = logging.getLogger(__name__)


class Database:
    """PostgreSQL database facade.

    Creates an async SQLAlchemy engine and session factory, instantiates all
    repository classes, and exposes the ``app``, ``library``, and ``ml``
    sub-facades for application, library, and ML operations.

    Also provides adapter classes (``migrations``, ``ml_capacity``,
    ``vram_promises``) that wrap async ``AppDb`` methods for backward
    compatibility with sync callers.
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
            url: PostgreSQL connection URL (e.g., ``postgresql+asyncpg://...``).
            echo: If ``True``, log all SQL statements.
            pool_size: Connection pool size.
            max_overflow: Max overflow connections beyond pool_size.

        """
        self._url = url
        self._echo = echo

        # Create async engine and session factory
        self._pg_engine = create_pg_engine(
            url,
            echo=echo,
            pool_size=pool_size,
            max_overflow=max_overflow,
        )
        _session_factory = async_session_factory(self._pg_engine)
        self._pg_session = _session_factory()

        # Instantiate all repositories
        self._app_repo = AppRepository(self._pg_session)
        self._scan_repo = ScanRepository(self._pg_session)
        self._library_repo = LibraryRepository(self._pg_session)
        self._navidrome_repo = NavidromeRepo(self._pg_session)
        self._file_state_repo = FileStateRepository(self._pg_session)
        self._pipeline_repo = PipelineRepository(self._pg_session)
        self._file_repo = FileRepository(self._pg_session)
        self._folder_repo = FolderRepository(self._pg_session)
        self._tag_repo = TagRepository(self._pg_session)
        self._file_tag_repo = FileTagRepository(self._pg_session)
        self._vector_repo = VectorRepo(self._pg_session)
        self._model_repo = ModelRepo(self._pg_session)
        self._output_repo = OutputRepo(self._pg_session)
        self._calibration_repo = CalibrationRepo(self._pg_session)
        self._embedding_stream_repo = EmbeddingStreamRepository(self._pg_session)

        # Import here to avoid circular imports
        from nomarr.persistence.api.application import AppDb
        from nomarr.persistence.api.library import LibraryDb
        from nomarr.persistence.api.ml import MlDb

        # Create sub-facades
        self.app = AppDb(
            session=self._pg_session,
            app_repo=self._app_repo,
            library_repo=self._library_repo,
            navidrome_repo=self._navidrome_repo,
            file_state_repo=self._file_state_repo,
            pipeline_repo=self._pipeline_repo,
        )
        self.library = LibraryDb(
            library_repo=self._library_repo,
            file_repo=self._file_repo,
            folder_repo=self._folder_repo,
            scan_repo=self._scan_repo,
            tag_repo=self._tag_repo,
            file_tag_repo=self._file_tag_repo,
            file_state_repo=self._file_state_repo,
        )
        self.ml = MlDb(
            vector_repo=self._vector_repo,
            model_repo=self._model_repo,
            output_repo=self._output_repo,
            calibration_repo=self._calibration_repo,
            embedding_stream_repo=self._embedding_stream_repo,
        )

        # Adapter instances for backward compatibility
        self.migrations = _MigrationsAdapter(self.app)
        self.ml_capacity = _MlCapacityAdapter(self.app)
        self.vram_promises = _VramPromisesAdapter(self.app)

    async def close(self) -> None:
        """Dispose the PostgreSQL engine and release all connections."""
        await self._pg_engine.dispose()

    async def get_version(self) -> str | None:
        """Return the current schema version from the config table."""
        return await self.app.get_schema_version()

    async def set_version(self, version: str) -> None:
        """Update the schema version in the config table."""
        await self.app.update_config_option("version", {"value": version})


class _MigrationsAdapter:
    """Sync-compatible adapter wrapping async ``AppDb`` migration methods.

    Provides a sync-looking interface for migration orchestration code.
    All methods are async and delegate to ``AppDb``.
    """

    def __init__(self, app: AppDb) -> None:
        self._app = app

    async def record_migration_started(
        self,
        migration_id: str,
        *,
        filename: str,
        checksum: str | None = None,
    ) -> None:
        """Record that a migration has started."""
        await self._app.upsert_migration(
            migration_id,
            {
                "filename": filename,
                "checksum": checksum,
                "status": "running",
            },
        )

    async def mark_migration_applied(self, migration_id: str) -> None:
        """Mark a migration as successfully applied."""
        await self._app.upsert_migration(migration_id, {"status": "applied"})

    async def list_migrations(self) -> list[dict]:
        """Return all migration records."""
        return await self._app.list_migrations()


class _MlCapacityAdapter:
    """Adapter wrapping async ``AppDb`` lock methods for ML capacity management.

    Provides methods for probing, acquiring, and releasing distributed locks
    used to coordinate ML worker capacity.
    """

    def __init__(self, app: AppDb) -> None:
        self._app = app

    async def probe(self, *, lock_id: str, worker_id: str) -> None:
        """Create a probing lock for a worker."""
        await self._app.add_lock({"key": lock_id, "value": {"worker_id": worker_id, "status": "probing"}})

    async def acquire(self, *, lock_id: str, worker_id: str) -> None:
        """Upgrade a lock to acquired status."""
        await self._app.add_lock({"key": lock_id, "value": {"worker_id": worker_id, "status": "acquired"}})

    async def release(self, *, lock_id: str) -> None:
        """Release a lock by ID."""
        await self._app.remove_lock(lock_id)

    async def get(self, *, lock_id: str) -> dict | None:
        """Get lock data by ID, or None if not found."""
        lock = await self._app.get_lock(lock_id)
        if lock is None:
            return None
        # LockRow is a TypedDict with 'key' and 'value' fields
        return {"key": lock["key"], **lock["value"]}

    async def list_all(self) -> list[dict]:
        """Return all locks as dicts."""
        locks = await self._app.list_locks()
        return [{"key": lock["key"], **lock["value"]} for lock in locks]


class _VramPromisesAdapter:
    """Adapter wrapping async ``AppDb`` VRAM promise methods.

    Provides methods for managing GPU VRAM promises made by ML workers.
    """

    def __init__(self, app: AppDb) -> None:
        self._app = app

    async def promise(
        self,
        *,
        worker_id: str,
        pid: int,
        model_path: str,
        promised_mb: float,
        total_mb: float,
        used_mb: float,
    ) -> None:
        """Record or update a VRAM promise from a worker."""
        await self._app.add_vram_promise(
            {
                "worker_id": worker_id,
                "pid": pid,
                "model_path": model_path,
                "promised_mb": promised_mb,
                "total_mb": total_mb,
                "used_mb": used_mb,
            }
        )

    async def release(self, *, worker_id: str, model_path: str) -> None:
        """Release a VRAM promise for a specific worker and model."""
        for p in await self._app.list_vram_promises():
            if p.get("worker_id") == worker_id and p.get("model_path") == model_path:
                pid = p.get("id")
                if pid:
                    await self._app.remove_vram_promise(pid)
                break

    async def release_all_for_worker(self, *, worker_id: str) -> None:
        """Release all VRAM promises for a worker."""
        for p in await self._app.list_vram_promises():
            if p.get("worker_id") == worker_id:
                pid = p.get("id")
                if pid:
                    await self._app.remove_vram_promise(pid)

    async def list_all(self) -> list[dict]:
        """Return all VRAM promises as dicts."""
        return await self._app.list_vram_promises()
