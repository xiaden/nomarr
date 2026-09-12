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
    "song_mood_calibration_markers",
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

    def test_baseline_is_the_single_root_revision(self) -> None:
        assert _BASELINE_PATH.exists()
        revision_files = sorted(_VERSIONS_DIR.glob("*.py"))
        # The amended baseline remains the only root; the immutable-UUID hard
        # cut chains from it as one linear revision (no branching/dual path).
        names = [path.name for path in revision_files]
        assert _BASELINE_PATH.name in names
        assert names == [
            "001_current_schema_baseline.py",
            "002_add_libraries_library_uuid.py",
        ]
        source = _baseline_source()
        assert 'revision: str = "baseline_20260830"' in source
        assert "down_revision: str | None = None" in source
        child = (_VERSIONS_DIR / "002_add_libraries_library_uuid.py").read_text(encoding="utf-8")
        assert 'revision: str = "002_libraries_library_uuid"' in child
        assert 'down_revision: str | None = "baseline_20260830"' in child

    def test_creates_expected_tables_without_historical_navidrome_tables(self) -> None:
        assert _created_tables() == _EXPECTED_TABLES
        source = _baseline_source()
        assert "navidrome_" not in source

    def test_contains_final_schema_constraints(self) -> None:
        source = _baseline_source()
        assert "uq_library_scans_one_in_progress" in source
        assert "uq_ml_embedding_streams_song_backbone" in source
        assert "uq_libraries_name" in source
        assert "uq_libraries_library_uuid" in source
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
    """D1A canonical migration characterization: the baseline ``tags`` table carries only reusable identity.

    These assertions characterize the D1A canonical ``001_current_schema_baseline``
    migration source: exactly the columns ``id``, ``namespace``, ``name``, ``value``;
    ``namespace`` NOT NULL; uniqueness on the complete ``(namespace, name, value)``
    tuple; and no metadata, FK, or extra index columns. This is D1A source-level
    migration characterization only; it makes no D1B/D2/D3 runtime claim.
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
        assert cols == ["namespace", "name", "value"]

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
class TestMoodMarkerMigrationContract:
    """Characterize the approved marker table from the canonical migration AST."""

    def test_marker_table_columns_and_types_are_exact(self) -> None:
        source = _baseline_source()
        tree = ast.parse(source)
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "create_table"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "song_mood_calibration_markers"
        ]
        assert len(calls) == 1
        call = calls[0]
        columns = []
        for arg in call.args[1:]:
            if not isinstance(arg, ast.Call) or not isinstance(arg.func, ast.Attribute) or arg.func.attr != "Column":
                continue
            name = ast.literal_eval(arg.args[0])
            type_node = arg.args[1]
            type_name = (
                type_node.func.attr
                if isinstance(type_node, ast.Call) and isinstance(type_node.func, ast.Attribute)
                else None
            )
            type_length = None
            if isinstance(type_node, ast.Call):
                if type_node.args:
                    type_length = ast.literal_eval(type_node.args[0])
                else:
                    length_keyword = next((keyword for keyword in type_node.keywords if keyword.arg == "length"), None)
                    if length_keyword is not None:
                        type_length = ast.literal_eval(length_keyword.value)
            nullable = next(
                (ast.literal_eval(keyword.value) for keyword in arg.keywords if keyword.arg == "nullable"), True
            )
            columns.append((name, type_name, type_length, nullable))
        assert columns == [
            ("song_id", "Integer", None, False),
            ("calibration_version", "String", 255, False),
        ]

    def test_marker_constraints_and_forbidden_storage_are_exact(self) -> None:
        source = _baseline_source()
        tree = ast.parse(source)
        marker = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "create_table"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "song_mood_calibration_markers"
        )
        primary_keys = [
            arg
            for arg in marker.args[1:]
            if isinstance(arg, ast.Call)
            and isinstance(arg.func, ast.Attribute)
            and arg.func.attr == "PrimaryKeyConstraint"
        ]
        assert len(primary_keys) == 1
        assert [ast.literal_eval(arg) for arg in primary_keys[0].args] == ["song_id"]
        foreign_keys = [
            arg
            for arg in marker.args[1:]
            if isinstance(arg, ast.Call)
            and isinstance(arg.func, ast.Attribute)
            and arg.func.attr == "ForeignKeyConstraint"
        ]
        assert len(foreign_keys) == 1
        assert ast.literal_eval(foreign_keys[0].args[0]) == ["song_id"]
        assert ast.literal_eval(foreign_keys[0].args[1]) == ["songs.id"]
        ondelete = next(keyword.value for keyword in foreign_keys[0].keywords if keyword.arg == "ondelete")
        assert ast.literal_eval(ondelete) == "CASCADE"
        checks = [
            arg
            for arg in marker.args[1:]
            if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute) and arg.func.attr == "CheckConstraint"
        ]
        assert len(checks) == 1
        assert ast.literal_eval(checks[0].args[0]) == "calibration_version ~ '^[0-9a-f]{32}$'"
        assert "song_mood_calibration_markers" in source
        assert "mood_marker_history" not in source
        assert "mood_marker_registry" not in source
        assert "COLLATE" not in source

    def test_marker_has_no_lookup_index_beyond_primary_key(self) -> None:
        tree = ast.parse(_baseline_source())
        marker_indexes = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "create_index" or len(node.args) < 2:
                continue
            table = node.args[1]
            if isinstance(table, ast.Constant) and table.value == "song_mood_calibration_markers":
                marker_indexes.append(node)
        assert marker_indexes == []


@pytest.mark.unit
class TestTagAndSongTagModelContract:
    """D1A canonical model characterization: the ORM models mirror the identity-only ``tags`` and edge-owned ``song_tags``.

    ``Tag`` exposes only identity fields; ``SongTag`` retains only the
    relationship metadata owned by the ``song_tags`` edge. These assertions
    characterize the D1A canonical model/schema source; they are D1A
    source-level characterization only and make no D1B/D2/D3 runtime claim.
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
