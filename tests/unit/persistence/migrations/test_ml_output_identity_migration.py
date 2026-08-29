"""Static validation of the stable ML output identity Alembic revision.

Validates the ``005_stable_ml_output_identity`` revision contract without a
database: the revision chain, that upgrade/downgrade touch only the intended
table (``ml_model_outputs``), that the fake ``song_id`` FK is dropped in
upgrade and re-created in downgrade, and that the unique ``output_id``
constraint round-trips.
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_MIGRATION_PATH = _REPO_ROOT / "alembic" / "versions" / "005_stable_ml_output_identity.py"

_TABLES_TOUCHED = {"ml_model_outputs"}
# Tables whose schemas must NOT be altered by this migration.  ``songs`` is
# deliberately excluded from this set: the downgrade re-creates the FK
# *targeting* ``songs`` without altering ``songs``' schema (same treatment the
# 003 migration test gives ``ml_models``).  ``test_downgrade_restores_song_fk``
# pins the FK restoration by name.
_UNRELATED_TABLES = {
    "embeddings",
    "ml_output_streams",
    "tags",
    "libraries",
    "ml_models",
}


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_005", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def migration():
    return _load_migration()


@pytest.mark.unit
class TestMlOutputIdentityMigration:
    """Validates the 005_stable_ml_output_identity revision contract."""

    def test_revision_chain(self, migration) -> None:
        """005 sits immediately after 004 (the previous head)."""
        assert migration.revision == "005_stable_ml_output_identity"
        assert migration.down_revision == "004_one_active_scan_per_library"

    def test_upgrade_touches_only_intended_table(self, migration) -> None:
        source = inspect.getsource(migration.upgrade)
        assert "ml_model_outputs" in source
        for table in _UNRELATED_TABLES:
            assert table not in source

    def test_downgrade_touches_only_intended_table(self, migration) -> None:
        source = inspect.getsource(migration.downgrade)
        assert "ml_model_outputs" in source
        for table in _UNRELATED_TABLES:
            assert table not in source

    def test_upgrade_drops_song_fk_and_column(self, migration) -> None:
        """Upgrade removes the fake song FK, its index, and the column."""
        upgrade_src = inspect.getsource(migration.upgrade)
        assert "ml_model_outputs_song_id_fkey" in upgrade_src
        assert "ix_ml_model_outputs_song_id" in upgrade_src
        assert "drop_column" in upgrade_src
        assert '"song_id"' in upgrade_src or "'song_id'" in upgrade_src

    def test_downgrade_restores_song_fk(self, migration) -> None:
        """Downgrade re-creates the song FK, index, and column (nullable)."""
        downgrade_src = inspect.getsource(migration.downgrade)
        assert "ml_model_outputs_song_id_fkey" in downgrade_src
        assert "ix_ml_model_outputs_song_id" in downgrade_src
        assert "add_column" in downgrade_src
        assert '"song_id"' in downgrade_src or "'song_id'" in downgrade_src

    def test_output_id_unique_constraint_round_trips(self, migration) -> None:
        """The output_id uniqueness is created in upgrade and dropped in downgrade."""
        upgrade_src = inspect.getsource(migration.upgrade)
        downgrade_src = inspect.getsource(migration.downgrade)
        assert "uq_ml_model_outputs_output_id" in upgrade_src
        assert "uq_ml_model_outputs_output_id" in downgrade_src
