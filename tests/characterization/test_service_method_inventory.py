"""Characterization tests for service method inventory.

Captures the behavior of 15 priority service methods as JSON snapshots.
These tests establish a baseline of current behavior that future refactors
must preserve.

Each test:
1. Instantiates a service with minimal dependencies (mocked where needed)
2. Calls a service method with seed data
3. Serializes the result (with DB ID masking, float rounding, etc.)
4. Compares against a stored snapshot (or creates baseline on first run)

Marked with @pytest.mark.characterization.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from .conftest import assert_snapshot_matches


@pytest.mark.characterization
class TestServiceMethodInventory:
    """Characterization tests for service methods."""

    # -----------------------------------------------------------------------
    # LibraryService (6 methods)
    # -----------------------------------------------------------------------

    def test_library_service_list_libraries(self, db, seed_data):
        """Snapshot: LibraryService.list_libraries(enabled_only=False)."""
        from nomarr.services.domain.library_svc import LibraryService
        from nomarr.services.domain.library_svc.config import LibraryServiceConfig

        cfg = LibraryServiceConfig(
            models_dir="/tmp/models",
            namespace="nom",
            tagger_version="test-v1",
        )
        service = LibraryService(cfg=cfg, db=db)
        result = service.list_libraries()
        assert_snapshot_matches("LibraryService_list_libraries", result)

    def test_library_service_create_library(self, db, seed_data, tmp_path):
        """Snapshot: LibraryService.create_library(name, root_path, ...)."""
        from nomarr.services.domain.library_svc import LibraryService
        from nomarr.services.domain.library_svc.config import LibraryServiceConfig

        lib_root = tmp_path / "library_root"
        lib_root.mkdir()
        new_lib_path = lib_root / "servicetest"
        new_lib_path.mkdir()

        cfg = LibraryServiceConfig(
            models_dir="/tmp/models",
            namespace="nom",
            tagger_version="test-v1",
            library_root=str(lib_root),
        )
        service = LibraryService(cfg=cfg, db=db)
        result = service.create_library(
            name="ServiceTestLib",
            root_path=str(new_lib_path),
            is_enabled=True,
        )
        assert_snapshot_matches("LibraryService_create_library", result)
        # Cleanup: find and remove the library
        libs = service.list_libraries()
        for lib in libs:
            if lib.name == "ServiceTestLib":
                db.library.remove_library(lib.id)
                break

    def test_library_service_get_library_stats(self, db, seed_data):
        """Snapshot: LibraryService.get_library_stats()."""
        from nomarr.services.domain.library_svc import LibraryService
        from nomarr.services.domain.library_svc.config import LibraryServiceConfig

        cfg = LibraryServiceConfig(
            models_dir="/tmp/models",
            namespace="nom",
            tagger_version="test-v1",
        )
        service = LibraryService(cfg=cfg, db=db)
        result = service.get_library_stats()
        assert_snapshot_matches("LibraryService_get_library_stats", result)

    def test_library_service_search_files(self, db, seed_data):
        """Snapshot: LibraryService.search_files(query)."""
        from nomarr.helpers.dto.library_dto import SearchFilesQuery
        from nomarr.services.domain.library_svc import LibraryService
        from nomarr.services.domain.library_svc.config import LibraryServiceConfig

        cfg = LibraryServiceConfig(
            models_dir="/tmp/models",
            namespace="nom",
            tagger_version="test-v1",
        )
        service = LibraryService(cfg=cfg, db=db)

        # Create a SearchFilesQuery dataclass instance
        query = SearchFilesQuery(query_text="song1", limit=10)
        result = service.search_files(query)
        assert_snapshot_matches("LibraryService_search_files", result)

    def test_library_service_get_song_tags(self, db, seed_data):
        """Snapshot: LibraryService.get_song_tags(song_id, nomarr_only=False)."""
        from nomarr.services.domain.library_svc import LibraryService
        from nomarr.services.domain.library_svc.config import LibraryServiceConfig

        cfg = LibraryServiceConfig(
            models_dir="/tmp/models",
            namespace="nom",
            tagger_version="test-v1",
        )
        service = LibraryService(cfg=cfg, db=db)
        song_id = seed_data["songs"][0]
        result = service.get_song_tags(song_id, nomarr_only=False)
        assert_snapshot_matches("LibraryService_get_song_tags", result)

    def test_library_service_cleanup_orphaned_tags(self, db, seed_data):
        """Snapshot: LibraryService.cleanup_orphaned_tags(dry_run=True)."""
        from nomarr.services.domain.library_svc import LibraryService
        from nomarr.services.domain.library_svc.config import LibraryServiceConfig

        cfg = LibraryServiceConfig(
            models_dir="/tmp/models",
            namespace="nom",
            tagger_version="test-v1",
        )
        service = LibraryService(cfg=cfg, db=db)
        result = service.cleanup_orphaned_tags(dry_run=True)
        assert_snapshot_matches("LibraryService_cleanup_orphaned_tags", result)

    # -----------------------------------------------------------------------
    # TaggingService (4 methods)
    # -----------------------------------------------------------------------

    def test_tagging_service_get_calibration_status(self, db, seed_data):
        """Snapshot: TaggingService.get_calibration_status()."""
        from nomarr.services.domain.tagging_svc import TaggingService
        from nomarr.services.domain.tagging_svc.config import TaggingServiceConfig

        cfg = TaggingServiceConfig(
            models_dir="/tmp/models",
            namespace="nom",
            version_tag_key="nomarr:version",
        )
        # Mock dependencies
        bts = MagicMock()
        config_service = MagicMock()
        service = TaggingService(
            database=db,
            cfg=cfg,
            bts=bts,
            config_service=config_service,
        )
        result = service.get_calibration_status()
        assert_snapshot_matches("TaggingService_get_calibration_status", result)

    def test_tagging_service_update_song_tags(self, db, seed_data):
        """Snapshot: TaggingService.update_song_tags(song_id, name, values)."""
        from nomarr.services.domain.tagging_svc import TaggingService
        from nomarr.services.domain.tagging_svc.config import TaggingServiceConfig

        cfg = TaggingServiceConfig(
            models_dir="/tmp/models",
            namespace="nom",
            version_tag_key="nomarr:version",
        )
        bts = MagicMock()
        config_service = MagicMock()
        service = TaggingService(
            database=db,
            cfg=cfg,
            bts=bts,
            config_service=config_service,
        )
        song_id = str(seed_data["songs"][0])
        result = service.update_song_tags(
            song_id=song_id,
            name="mood",
            values=["happy", "energetic"],
        )
        assert_snapshot_matches("TaggingService_update_song_tags", result)

    def test_tagging_service_list_tag_values(self, db, seed_data):
        """Snapshot: TaggingService.list_tag_values(...)."""
        from nomarr.services.domain.tagging_svc import TaggingService
        from nomarr.services.domain.tagging_svc.config import TaggingServiceConfig

        cfg = TaggingServiceConfig(
            models_dir="/tmp/models",
            namespace="nom",
            version_tag_key="nomarr:version",
        )
        bts = MagicMock()
        config_service = MagicMock()
        service = TaggingService(
            database=db,
            cfg=cfg,
            bts=bts,
            config_service=config_service,
        )
        # Call with minimal args
        result = service.list_tag_values(name="nom:mood-strict")
        assert_snapshot_matches("TaggingService_list_tag_values", result)

    def test_tagging_service_get_unique_tag_keys(self, db, seed_data):
        """Snapshot: TaggingService.get_unique_tag_keys(nomarr_only=False)."""
        from nomarr.services.domain.tagging_svc import TaggingService
        from nomarr.services.domain.tagging_svc.config import TaggingServiceConfig

        cfg = TaggingServiceConfig(
            models_dir="/tmp/models",
            namespace="nom",
            version_tag_key="nomarr:version",
        )
        bts = MagicMock()
        config_service = MagicMock()
        service = TaggingService(
            database=db,
            cfg=cfg,
            bts=bts,
            config_service=config_service,
        )
        result = service.get_unique_tag_keys(nomarr_only=False)
        assert_snapshot_matches("TaggingService_get_unique_tag_keys", result)

    # -----------------------------------------------------------------------
    # WorkerSystemService (3 methods)
    # -----------------------------------------------------------------------

    def test_worker_system_service_get_workers_status(self, db, seed_data):
        """Snapshot: WorkerSystemService.get_workers_status()."""
        from nomarr.services.infrastructure.worker_system_svc.main import (
            WorkerSystemService,
        )

        # Mock dependencies
        processor_config = MagicMock()
        pipeline_svc = MagicMock()
        service = WorkerSystemService(
            db=db,
            processor_config=processor_config,
            pipeline_svc=pipeline_svc,
            worker_count=1,
        )
        result = service.get_workers_status()
        assert_snapshot_matches("WorkerSystemService_get_workers_status", result)

    def test_worker_system_service_is_worker_system_enabled(self, db, seed_data):
        """Snapshot: WorkerSystemService.is_worker_system_enabled()."""
        from nomarr.services.infrastructure.worker_system_svc.main import (
            WorkerSystemService,
        )

        processor_config = MagicMock()
        pipeline_svc = MagicMock()
        service = WorkerSystemService(
            db=db,
            processor_config=processor_config,
            pipeline_svc=pipeline_svc,
            worker_count=1,
        )
        result = service.is_worker_system_enabled()
        assert_snapshot_matches("WorkerSystemService_is_worker_system_enabled", result)

    def test_worker_system_service_get_worker_count(self, db, seed_data):
        """Snapshot: WorkerSystemService.get_worker_count()."""
        from nomarr.services.infrastructure.worker_system_svc.main import (
            WorkerSystemService,
        )

        processor_config = MagicMock()
        pipeline_svc = MagicMock()
        service = WorkerSystemService(
            db=db,
            processor_config=processor_config,
            pipeline_svc=pipeline_svc,
            worker_count=2,
        )
        result = service.get_worker_count()
        assert_snapshot_matches("WorkerSystemService_get_worker_count", result)

    # -----------------------------------------------------------------------
    # HealthMonitorService (2 methods)
    # -----------------------------------------------------------------------

    def test_health_monitor_service_get_all_statuses(self, db, seed_data):
        """Snapshot: HealthMonitorService.get_all_statuses()."""
        from nomarr.services.infrastructure.health_monitor_svc.main import (
            HealthMonitorService,
        )

        # Mock config
        cfg = MagicMock()
        service = HealthMonitorService(cfg=cfg, db=db)
        result = service.get_all_statuses()
        assert_snapshot_matches("HealthMonitorService_get_all_statuses", result)

    def test_health_monitor_service_get_component_ids(self, db, seed_data):
        """Snapshot: HealthMonitorService.get_component_ids()."""
        from nomarr.services.infrastructure.health_monitor_svc.main import (
            HealthMonitorService,
        )

        cfg = MagicMock()
        service = HealthMonitorService(cfg=cfg, db=db)
        result = service.get_component_ids()
        assert_snapshot_matches("HealthMonitorService_get_component_ids", result)
