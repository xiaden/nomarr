"""Static validation of the canonical ML output stream Alembic revision.

Validates the ``003_canonical_ml_output_streams`` revision contract without a
database: the revision chain, and that upgrade/downgrade touch only the two
intended tables (the embedding-streams uniqueness must not disturb other
tables' schemas).
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_MIGRATION_PATH = _REPO_ROOT / "alembic" / "versions" / "003_canonical_ml_output_streams.py"

_TABLES_TOUCHED = {"ml_output_streams", "ml_embedding_streams"}
# Tables whose schemas must NOT be altered by this migration. ``ml_models`` is
# deliberately excluded: the downgrade re-creates ``ml_output_streams``'s FK
# *targeting* ``ml_models`` without altering ``ml_models``' schema.
_UNRELATED_TABLES = {
    "songs",
    "embeddings",
    "ml_model_outputs",
    "tags",
    "libraries",
}


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_003", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def migration():
    return _load_migration()


@pytest.mark.unit
class TestMlOutputStreamMigration:
    """Validates the 003_canonical_ml_output_streams revision contract."""

    def test_revision_chain(self, migration) -> None:
        """003 sits immediately after 002 (the previous head)."""
        assert migration.revision == "003_canonical_ml_output_streams"
        assert migration.down_revision == "002_drop_navidrome_tables"

    def test_upgrade_touches_only_intended_tables(self, migration) -> None:
        source = inspect.getsource(migration.upgrade)
        for table in _TABLES_TOUCHED:
            assert table in source
        for table in _UNRELATED_TABLES:
            assert table not in source

    def test_downgrade_touches_only_intended_tables(self, migration) -> None:
        source = inspect.getsource(migration.downgrade)
        for table in _TABLES_TOUCHED:
            assert table in source
        for table in _UNRELATED_TABLES:
            assert table not in source

    def test_embedding_streams_unique_constraint_round_trips(self, migration) -> None:
        """The (song_id, backbone_id) uniqueness is created in upgrade and dropped in downgrade."""
        upgrade_src = inspect.getsource(migration.upgrade)
        downgrade_src = inspect.getsource(migration.downgrade)
        assert "uq_ml_embedding_streams_song_backbone" in upgrade_src
        assert "uq_ml_embedding_streams_song_backbone" in downgrade_src
