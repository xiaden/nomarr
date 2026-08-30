"""Static checks for the consolidated PostgreSQL schema baseline."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_BASELINE_PATH = _REPO_ROOT / "alembic" / "versions" / "001_current_schema_baseline.py"
_VERSIONS_DIR = _REPO_ROOT / "alembic" / "versions"

_EXPECTED_TABLES = {
    "libraries",
    "library_folders",
    "songs",
    "tags",
    "song_tags",
    "song_states",
    "song_state_assignments",
    "pipeline_states",
    "library_scans",
    "ml_models",
    "ml_output_streams",
    "ml_embedding_streams",
    "ml_model_outputs",
    "calibration_states",
    "calibration_history",
    "meta",
    "sessions",
    "worker_health",
    "worker_claims",
    "locks",
    "worker_restart_policies",
    "applied_migrations",
    "vram_promises",
    "embeddings",
}


def _baseline_source() -> str:
    return _BASELINE_PATH.read_text(encoding="utf-8")


def _created_tables() -> set[str]:
    tree = ast.parse(_baseline_source())
    tables: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "create_table" or not node.args:
            continue
        table = node.args[0]
        if isinstance(table, ast.Constant) and isinstance(table.value, str):
            tables.add(table.value)
    return tables


@pytest.mark.unit
class TestCurrentSchemaBaseline:
    """Validate that Alembic has one complete, current baseline."""

    def test_is_the_only_revision_with_no_parent(self) -> None:
        assert _BASELINE_PATH.exists()
        revision_files = sorted(_VERSIONS_DIR.glob("*.py"))
        assert [path.name for path in revision_files] == [_BASELINE_PATH.name]
        source = _baseline_source()
        assert 'revision: str = "baseline_20260830"' in source
        assert "down_revision: str | None = None" in source

    def test_creates_expected_tables_without_historical_navidrome_tables(self) -> None:
        assert _created_tables() == _EXPECTED_TABLES
        source = _baseline_source()
        assert "navidrome_" not in source

    def test_contains_final_schema_constraints(self) -> None:
        source = _baseline_source()
        assert "uq_library_scans_one_in_progress" in source
        assert "uq_ml_embedding_streams_song_backbone" in source
        assert "uq_libraries_name" in source
        assert "uq_ml_model_outputs_output_id" in source
        assert "uq_worker_restart_policies_component_id" in source
        assert 'sa.Column("heartbeat_at", sa.BigInteger(), nullable=True)' in source
        assert 'sa.Column("mtime", sa.BigInteger(), nullable=True)' in source
        assert 'sa.Column("file_count", sa.Integer(), nullable=True)' in source
        assert 'sa.Column("last_scanned_at", sa.BigInteger(), nullable=True)' in source
