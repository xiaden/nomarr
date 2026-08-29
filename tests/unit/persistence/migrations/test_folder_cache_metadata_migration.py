"""Static validation of the folder-cache metadata migration."""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_MIGRATION_PATH = _REPO_ROOT / "alembic" / "versions" / "006_add_folder_cache_metadata.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_006_folder_cache", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
class TestFolderCacheMetadataMigration:
    """Validate the folder-cache revision chain and round-trip operations."""

    def test_revision_chain(self) -> None:
        migration = _load_migration()
        assert migration.revision == "006_add_folder_cache_metadata"
        assert migration.down_revision == "005_stable_ml_output_identity"

    def test_upgrade_adds_folder_metadata_columns(self) -> None:
        source = inspect.getsource(_load_migration().upgrade)
        assert source.count('op.add_column("library_folders"') == 3
        assert "mtime" in source
        assert "file_count" in source
        assert "last_scanned_at" in source

    def test_downgrade_removes_folder_metadata_columns(self) -> None:
        source = inspect.getsource(_load_migration().downgrade)
        assert source.count('op.drop_column("library_folders"') == 3
