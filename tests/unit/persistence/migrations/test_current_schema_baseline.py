"""Static checks for the consolidated PostgreSQL schema baseline."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from nomarr.persistence.models.song_tag import SongTag
from nomarr.persistence.models.tag import Tag

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


def _tags_create_call():
    """Return the AST ``Call`` node for ``op.create_table("tags", ...)`` in the baseline."""
    tree = ast.parse(_baseline_source())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "create_table" or not node.args:
            continue
        table = node.args[0]
        if isinstance(table, ast.Constant) and isinstance(table.value, str) and table.value == "tags":
            return node
    return None


def _tags_table_columns() -> list[tuple[str, bool]]:
    """Ordered ``(name, nullable)`` pairs declared on the ``tags`` create_table."""
    call = _tags_create_call()
    assert call is not None, "baseline must create a tags table"
    columns: list[tuple[str, bool]] = []
    for arg in call.args[1:]:
        if not isinstance(arg, ast.Call) or not isinstance(arg.func, ast.Attribute):
            continue
        if arg.func.attr != "Column":
            continue
        name = arg.args[0] if arg.args else None
        if not isinstance(name, ast.Constant) or not isinstance(name.value, str):
            continue
        nullable = True
        for kw in arg.keywords:
            if kw.arg == "nullable":
                nullable = bool(ast.literal_eval(kw.value))
        columns.append((name.value, nullable))
    return columns


def _tags_table_unique_constraints() -> list[tuple[list[str], str | None]]:
    """``(column list, constraint name)`` for each UniqueConstraint on the ``tags`` table."""
    call = _tags_create_call()
    assert call is not None
    uniques: list[tuple[list[str], str | None]] = []
    for arg in call.args[1:]:
        if not isinstance(arg, ast.Call) or not isinstance(arg.func, ast.Attribute):
            continue
        if arg.func.attr == "UniqueConstraint":
            cols = [c.value for c in arg.args if isinstance(c, ast.Constant) and isinstance(c.value, str)]
            name = None
            for kw in arg.keywords:
                if kw.arg == "name" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    name = kw.value.value
            uniques.append((cols, name))
    return uniques


def _tags_table_has_foreign_key() -> bool:
    """True when the ``tags`` create_table declares any ``ForeignKeyConstraint``."""
    call = _tags_create_call()
    assert call is not None
    for arg in call.args[1:]:
        if (
            isinstance(arg, ast.Call)
            and isinstance(arg.func, ast.Attribute)
            and arg.func.attr == "ForeignKeyConstraint"
        ):
            return True
    return False


@pytest.mark.unit
class TestTagSchemaIdentityContract:
    """Spec-first: the fresh-start ``tags`` table carries only reusable identity.

    These assertions pin the immutable user ledger: exactly the columns ``id``,
    ``namespace``, ``name``, ``value``; ``namespace`` NOT NULL; uniqueness on
    the complete ``(namespace, name, value)`` tuple; and no metadata, FK, or
    index columns. They are expected to FAIL against the current legacy
    baseline (which still has ``parent_tag_id``/``source``/``confidence``/
    ``tier``/``created_at``) until Phase 2 trims the schema.
    """

    def test_tags_columns_are_exactly_identity_ordered(self) -> None:
        names = [name for name, _ in _tags_table_columns()]
        assert names == ["id", "namespace", "name", "value"]

    def test_tags_namespace_is_not_null(self) -> None:
        nullability = dict(_tags_table_columns())
        assert nullability["namespace"] is False

    def test_tags_unique_constraint_covers_complete_identity(self) -> None:
        named = [(cols, n) for cols, n in _tags_table_unique_constraints() if n == "uq_tags_name_value_ns"]
        assert named, "tags must declare the canonical uq_tags_name_value_ns unique constraint"
        cols, _ = named[0]
        assert set(cols) == {"namespace", "name", "value"}

    def test_tags_has_no_metadata_columns(self) -> None:
        names = [name for name, _ in _tags_table_columns()]
        for legacy in ("parent_tag_id", "source", "confidence", "tier", "created_at"):
            assert legacy not in names

    def test_tags_has_no_foreign_keys(self) -> None:
        assert _tags_table_has_foreign_key() is False

    def test_tags_has_no_extra_indexes_beyond_pk_and_unique(self) -> None:
        source = _baseline_source()
        assert "ix_tags_parent_tag_id" not in source
        assert "ix_tags_name_trgm" not in source


@pytest.mark.unit
class TestTagAndSongTagModelContract:
    """Spec-first: the ORM models mirror the identity-only ``tags`` and edge-owned ``song_tags``.

    ``Tag`` exposes only identity fields; ``SongTag`` retains only the
    relationship metadata owned by the ``song_tags`` edge. Expected to FAIL
    against the current ``Tag`` model (which still mirrors the legacy columns)
    until Phase 2 (P2-S2/P2-S4) trims it.
    """

    def test_tag_model_columns_are_identity_only(self) -> None:
        cols = [c.name for c in Tag.__table__.columns]
        assert cols == ["id", "namespace", "name", "value"]

    def test_tag_model_namespace_not_null(self) -> None:
        assert Tag.__table__.c.namespace.nullable is False

    def test_tag_model_unique_constraint_covers_complete_identity(self) -> None:
        named = [
            c
            for c in Tag.__table__.constraints  # type: ignore[attr-defined]  # Model.__table__ is typed as FromClause; constraints live on the Table
            if c.name == "uq_tags_name_value_ns"
        ]
        assert named, "Tag must declare the canonical uq_tags_name_value_ns unique constraint"
        cols = [c.name for c in named[0].columns]
        assert set(cols) == {"namespace", "name", "value"}

    def test_tag_model_has_no_metadata_columns(self) -> None:
        names = {c.name for c in Tag.__table__.columns}
        for legacy in ("parent_tag_id", "source", "confidence", "tier", "created_at"):
            assert legacy not in names

    def test_song_tag_model_columns_are_edge_relationship_only(self) -> None:
        cols = [c.name for c in SongTag.__table__.columns]
        assert cols == ["id", "song_id", "tag_id", "confidence", "source", "created_at"]
