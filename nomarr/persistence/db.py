"""Database layer for Nomarr (ArangoDB)."""

from __future__ import annotations

import logging
import os

import yaml

from nomarr.persistence.api import AppDb, LibraryDb, MlDb
from nomarr.persistence.arango_client import SafeDatabase, create_arango_client
from nomarr.persistence.database.app_aql import AppAqlOperations
from nomarr.persistence.database.file_states_aql import FileStatesAqlOperations
from nomarr.persistence.database.libraries_aql import LibrariesAqlOperations
from nomarr.persistence.database.library_files_aql import LibraryFilesAqlOperations
from nomarr.persistence.database.ml_embedding_streams_aql import MlEmbeddingStreamsAqlOperations
from nomarr.persistence.database.ml_models_aql import MlModelsAqlOperations
from nomarr.persistence.database.ml_streams_aql import MlStreamsAqlOperations
from nomarr.persistence.database.navidrome_aql import NavidromeAqlOperations
from nomarr.persistence.database.scan_aql import ScanAqlOperations
from nomarr.persistence.database.tags_aql import TagsAqlOperations
from nomarr.persistence.database.vectors_aql import VectorsAqlOperations
from nomarr.persistence.schema import CollectionNames

__all__ = ["Database"]

# ==================== SCHEMA VERSIONING POLICY ====================
# Schema versioning uses forward-only migrations with semver strings (alpha policy).
#
# The current schema version is the MIGRATION_VERSION of the last applied
# migration (a semver string, e.g. "0.14.0"). Stored in meta.version.
# See nomarr/components/platform/migration_runner_comp.run_pending_migrations().
#
# Migration system:
#   - Migrations live in nomarr/migrations/ as V*.py modules
#   - Each migration declares MIGRATION_VERSION (semver string), DESCRIPTION, upgrade()
#   - Applied migrations tracked in applied_migrations collection
#   - Schema version stored in meta collection under key "version"
#   - Startup aborts if DB schema is ahead of code (__version__)
#
# Schema changes require:
#   1. Create migration file in nomarr/migrations/
#   2. Set MIGRATION_VERSION to next semver, implement upgrade()
#   3. See docs/dev/migrations.md for full migration architecture
#
# Alpha: Breaking changes allowed pre-1.0, but migrations provide self-repair.
# Post-1.0: Strict migration requirements with deprecation paths.
# ==================================================================


class _MigrationsAdapter:
    """Thin adapter preserving the legacy ``db.migrations.*`` contract.

    Migrations were previously exposed as a first-class collection on the
    Database facade.  This adapter delegates to the ``AppDb`` API while
    keeping existing callers working.
    """

    def __init__(self, app: AppDb) -> None:
        self._app = app

    def record_migration_started(
        self,
        name: str,
        migration_version: str,
        started_at: str,
    ) -> None:
        """Record that a migration has started."""
        self._app.upsert_migration(
            name,
            {
                "status": "in_progress",
                "started_at": started_at,
                "migration_version": migration_version,
            },
        )

    def mark_migration_applied(
        self,
        name: str,
        duration_ms: int,
        applied_at: str,
    ) -> None:
        """Mark a migration as successfully applied."""
        self._app.upsert_migration(
            name,
            {
                "status": "applied",
                "applied_at": applied_at,
                "duration_ms": duration_ms,
            },
        )

    def list_migrations(self) -> list[dict]:
        """Return all applied migration records."""
        return self._app.list_migrations()


class _MlCapacityAdapter:
    """Adapter providing the legacy ``db.ml_capacity.*`` contract.

    ML capacity estimates and probe locks are stored as app-level config
    options and locks, delegating to ``AppDb`` under the hood.
    """

    def __init__(self, app: AppDb) -> None:
        self._app = app

    @staticmethod
    def _estimate_key(model_set_hash: str) -> str:
        return f"ml_capacity_estimate_{model_set_hash}"

    @staticmethod
    def _lock_id(model_set_hash: str) -> str:
        return f"ml_capacity_probe_{model_set_hash}"

    def get_capacity_estimate(self, model_set_hash: str) -> dict | None:
        return self._app.get_config_option(self._estimate_key(model_set_hash))

    def save_capacity_estimate(
        self,
        *,
        model_set_hash: str,
        measured_backbone_vram_mb: int,
        estimated_worker_ram_mb: int,
        probe_duration_s: float,
        probed_by_worker: str,
    ) -> None:
        self._app.update_config_option(
            self._estimate_key(model_set_hash),
            {
                "model_set_hash": model_set_hash,
                "measured_backbone_vram_mb": measured_backbone_vram_mb,
                "estimated_worker_ram_mb": estimated_worker_ram_mb,
                "probe_duration_s": probe_duration_s,
                "probed_by_worker": probed_by_worker,
            },
        )

    def delete_capacity_estimate(self, model_set_hash: str) -> None:
        self._app.remove_config_option(self._estimate_key(model_set_hash))

    def try_acquire_probe_lock(self, model_set_hash: str, worker_id: str) -> bool:
        lock_id = self._lock_id(model_set_hash)
        existing = self._app.get_lock(lock_id)
        if existing is not None:
            return False
        self._app.add_lock({"resource_id": lock_id, "worker_id": worker_id, "status": "probing"})
        return True

    def release_probe_lock(self, model_set_hash: str) -> None:
        self._app.remove_lock(self._lock_id(model_set_hash))

    def complete_probe_lock(self, model_set_hash: str) -> None:
        lock_id = self._lock_id(model_set_hash)
        lock = self._app.get_lock(lock_id)
        if lock is not None:
            lock["status"] = "complete"
            # Re-insert with overwrite via upsert_meta pattern
            self._app.remove_lock(lock_id)
            self._app.add_lock({"resource_id": lock_id, "worker_id": lock.get("worker_id", ""), "status": "complete"})

    def get_probe_lock_status(self, model_set_hash: str) -> dict | None:
        return self._app.get_lock(self._lock_id(model_set_hash))


class _VramPromisesAdapter:
    """Adapter providing the legacy ``db.vram_promises.*`` contract.

    VRAM promise records are stored as per-persistence-layer convention
    (via ``AppDb.add_vram_promise`` / ``list_vram_promises`` /
    ``remove_vram_promise``), wrapped here to present the exact API the
    ``ml_vram_coordinator_comp`` component expects.
    """

    _MAX_GPU_VRAM_MB = 24_576  # 24 GiB is a safe server-side default

    def __init__(self, app: AppDb) -> None:
        self._app = app

    def try_register(
        self,
        *,
        worker_id: str,
        pid: int,
        model_path: str,
        promised_mb: float,
        total_mb: float,
        used_mb: float,
    ) -> bool:
        """Atomically register a VRAM promise if headroom permits.

        Returns True when the promise was inserted, False when the GPU is
        oversubscribed and the caller should fall back to CPU.
        """
        existing = self._app.list_vram_promises()
        committed = sum(float(p.get("promised_mb", 0)) for p in existing)
        if committed + promised_mb > total_mb * 0.90:
            return False

        self._app.add_vram_promise({
            "worker_id": worker_id,
            "pid": pid,
            "model_path": model_path,
            "promised_mb": promised_mb,
            "total_mb": total_mb,
            "used_mb": used_mb,
        })
        return True

    def release(self, *, worker_id: str, model_path: str) -> None:
        """Release a single VRAM promise by worker and model path."""
        for p in self._app.list_vram_promises():
            if p.get("worker_id") == worker_id and p.get("model_path") == model_path:
                pid = p.get("_id") or p.get("_key")
                if pid:
                    self._app.remove_vram_promise(pid)
                break

    def get_all(self) -> list[dict]:
        """Return all active VRAM promises."""
        return self._app.list_vram_promises()

    def release_all_for_worker(self, *, worker_id: str) -> int:
        """Release every VRAM promise belonging to *worker_id*."""
        removed = 0
        for p in self._app.list_vram_promises():
            if p.get("worker_id") == worker_id:
                pid = p.get("_id") or p.get("_key")
                if pid:
                    self._app.remove_vram_promise(pid)
                    removed += 1
        return removed


class Database:
    """Application database (ArangoDB).

    Handles all data persistence: queue, library, sessions, meta config.
    Single source of truth for database operations across all services.

    Connection pooling is handled automatically by python-arango.
    Thread-safe within a single process. Each process creates its own pool.

    Credential Flow:
    - First run: App provisions DB with root password, generates app password,
      stores in config file. Database is NOT usable until first-run completes.
    - After first run: Password read from config file (/app/config/nomarr.yaml).
    - Username and db_name are hardcoded as 'nomarr' (not configurable).
    """

    USERNAME = "nomarr"
    DB_NAME = "nomarr"

    def __init__(
        self,
        hosts: str | None = None,
        password: str | None = None,
    ) -> None:
        """Initialize database connection.

        Args:
            hosts: ArangoDB server URL(s). Read from ARANGO_HOST env var if not provided.
            password: Database password. Read from config file if not provided.

        Raises:
            RuntimeError: If password not available or ARANGO_HOST not set

        """
        self.hosts = hosts or os.getenv("ARANGO_HOST")
        if not self.hosts:
            msg = (
                "ARANGO_HOST environment variable required. "
                "Set to 'http://nomarr-arangodb:8529' for Docker Compose or 'http://localhost:8529' for dev."
            )
            raise RuntimeError(msg)

        self.username = self.USERNAME
        self.db_name = self.DB_NAME
        self.password = password or self._load_password_from_config()

        if not self.password:
            msg = (
                "Database password not available. "
                "On first run, ensure ARANGO_ROOT_PASSWORD is set for provisioning. "
                "After first run, password is read from /app/config/nomarr.yaml."
            )
            raise RuntimeError(msg)

        self.db: SafeDatabase = create_arango_client(
            hosts=self.hosts,
            username=self.username,
            password=self.password,
            db_name=self.db_name,
        )

        self.libraries_aql = LibrariesAqlOperations(self.db)
        self.library_files_aql = LibraryFilesAqlOperations(self.db)
        self.tags_aql = TagsAqlOperations(self.db)
        self.scan_aql = ScanAqlOperations(self.db)
        self.file_states_aql = FileStatesAqlOperations(self.db)
        self.ml_streams_aql = MlStreamsAqlOperations(self.db)
        self.vectors_aql = VectorsAqlOperations(self.db)
        self.ml_models_aql = MlModelsAqlOperations(self.db)
        self.ml_embedding_streams_aql = MlEmbeddingStreamsAqlOperations(self.db)
        self.app_aql = AppAqlOperations(self.db)
        self.navidrome_aql = NavidromeAqlOperations(self.db)

        # Direct Tier 2 aliases remain only where compatibility evidence still
        # justifies keeping the debt temporarily explicit.
        # Higher-layer callers must treat db.library / db.app / db.ml as the
        # supported Tier 3 persistence API.
        self.libraries = self.libraries_aql
        self.library_files = self.library_files_aql
        self.file_states = self.file_states_aql
        self.tags = self.tags_aql

        # Canonical Tier 3 caller entrypoints. Shared maintenance scaffolding is
        # nested under these three domain facades; no top-level db.admin surface.
        self.library: LibraryDb = LibraryDb(
            libraries=self.libraries_aql,
            files=self.library_files_aql,
            tags=self.tags_aql,
            scan=self.scan_aql,
            file_states=self.file_states_aql,
            vectors=self.vectors_aql,
            streams=self.ml_streams_aql,
        )
        self.ml: MlDb = MlDb(
            streams=self.ml_streams_aql,
            vectors=self.vectors_aql,
            models=self.ml_models_aql,
            embedding_streams=self.ml_embedding_streams_aql,
        )
        self.app: AppDb = AppDb(
            db=self.db,
            file_states=self.file_states_aql,
            scan=self.scan_aql,
            app=self.app_aql,
            navidrome=self.navidrome_aql,
            libraries=self.libraries_aql,
        )

        # Legacy migrations namespace — delegates to AppDb
        self.migrations = _MigrationsAdapter(self.app)
        # Legacy ml_capacity namespace — delegates to AppDb
        self.ml_capacity = _MlCapacityAdapter(self.app)
        # Legacy vram_promises namespace — delegates to AppDb
        self.vram_promises = _VramPromisesAdapter(self.app)

    def get_version(self) -> str | None:
        """Read the current schema version from the meta store."""
        meta_coll = self.db.collection(CollectionNames.META.value)
        version_doc = meta_coll.get({"_key": "version"})
        if not isinstance(version_doc, dict):
            return None
        value = version_doc.get("value")
        return value if isinstance(value, str) else None

    def set_version(self, version: str) -> None:
        """Persist the schema version to the meta store."""
        meta_coll = self.db.collection(CollectionNames.META.value)
        meta_coll.insert({"_key": "version", "value": version}, overwrite=True)

    def close(self) -> None:
        """Close database connection (cleanup)."""

    @staticmethod
    def _load_password_from_config() -> str | None:
        """Load arango_password from config file.

        Checks standard config locations in order:
        1. /app/config/nomarr.yaml (Docker container)
        2. ./config/nomarr.yaml (local dev)

        Returns:
            Password string if found, None otherwise

        """
        config_paths = [
            "/app/config/nomarr.yaml",
            os.path.join(os.getcwd(), "config", "nomarr.yaml"),
        ]

        for path in config_paths:
            if os.path.exists(path):
                try:
                    with open(path, encoding="utf-8") as f:
                        config = yaml.safe_load(f) or {}
                    password = config.get("arango_password")
                    if isinstance(password, str) and password:
                        return password
                except Exception as e:
                    logging.getLogger(__name__).debug("[db] Failed to read config file %s: %s", path, e)

        return None
