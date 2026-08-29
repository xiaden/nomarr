"""Static validation of the worker restart policy uniqueness migration."""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_MIGRATION_PATH = _REPO_ROOT / "alembic" / "versions" / "007_unique_worker_restart_policy_component.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_007", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
class TestWorkerRestartPolicyMigration:
    """Validate the revision chain and uniqueness round-trip contract."""

    def test_revision_chain(self) -> None:
        migration = _load_migration()
        assert migration.revision == "007_unique_worker_restart_policy_component"
        assert migration.down_revision == "006_add_folder_cache_metadata"

    def test_upgrade_repairs_duplicates_and_adds_unique_constraint(self) -> None:
        source = inspect.getsource(_load_migration().upgrade)
        assert "DELETE FROM worker_restart_policies" in source
        assert "ix_worker_restart_policies_component_id" in source
        assert "uq_worker_restart_policies_component_id" in source
        assert "create_unique_constraint" in source

    def test_downgrade_restores_non_unique_index(self) -> None:
        source = inspect.getsource(_load_migration().downgrade)
        assert "uq_worker_restart_policies_component_id" in source
        assert "drop_constraint" in source
        assert "create_index" in source
