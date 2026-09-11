"""Contract tests for the immutable ``libraries.library_uuid`` hard cut.

``TASK-song-row-mirror-leaks-into-domain-G`` P1-S1/P1-S6. ADR-049 makes
``libraries.library_uuid`` the immutable, NOT NULL, UNIQUE Nomarr-minted library
application identity. This module proves:

- the amended baseline declares the column for fresh databases and the revision
  chain is a single linear hard cut (no alias or dual path);
- the ``002`` revision backfills every existing row with a freshly minted UUID
  before enforcing NOT NULL + UNIQUE, and is a no-op when the baseline already
  created the column (the fresh-database path);
- malformed/unknown UUIDs are rejected by persistence lookups rather than
  falling back to integer identity (see the repository/facade suites).

The live-PostgreSQL backfill proof is guarded by ``NOMARR_TEST_DATABASE_URL``
and marked ``requires_database``: when no server is available it is skipped and
reported honestly, never treated as PASS.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

if TYPE_CHECKING:
    from types import ModuleType

_REPO_ROOT = Path(__file__).resolve().parents[4]
_BASELINE_PATH = _REPO_ROOT / "alembic" / "versions" / "001_current_schema_baseline.py"
_MIGRATION_PATH = _REPO_ROOT / "alembic" / "versions" / "002_add_libraries_library_uuid.py"
_PG_URL = os.environ.get("NOMARR_TEST_DATABASE_URL")


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("library_uuid_migration_002", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── unit-test fakes (no database required) ─────────────────────────────────


class _FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)


class _RecordingBind:
    """Minimal stand-in for the Alembic bind, recording every statement."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows
        self.calls: list[tuple[Any, Any]] = []

    def execute(self, statement: Any, parameters: Any = None) -> _FakeResult:
        self.calls.append((statement, parameters))
        return _FakeResult(self._rows)


class _FakeInspector:
    def __init__(self, *, has_column: bool, has_constraint: bool) -> None:
        self._has_column = has_column
        self._has_constraint = has_constraint

    def get_columns(self, _table: str) -> list[dict[str, Any]]:
        columns = [{"name": "id"}]
        if self._has_column:
            columns.append({"name": "library_uuid"})
        return columns

    def get_unique_constraints(self, _table: str) -> list[dict[str, Any]]:
        if self._has_constraint:
            return [{"name": "uq_libraries_library_uuid"}]
        return []


class _FakeSA:
    """Stand-in for the ``sqlalchemy`` module used by the revision."""

    def __init__(self, *, has_column: bool, has_constraint: bool = True) -> None:
        self._inspector = _FakeInspector(has_column=has_column, has_constraint=has_constraint)

    def inspect(self, _bind: Any) -> _FakeInspector:
        return self._inspector

    @staticmethod
    def Column(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"column": args, "kwargs": kwargs}

    @staticmethod
    def String(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"string": args, "kwargs": kwargs}

    @staticmethod
    def text(sql: str) -> str:
        return sql


@pytest.mark.unit
class TestLibraryUuidMigrationStatic:
    """The hard cut is one linear revision over the amended baseline."""

    def test_revision_chains_from_amended_baseline(self) -> None:
        migration = _load_migration()
        assert migration.revision == "002_libraries_library_uuid"
        assert migration.down_revision == "baseline_20260830"

    def test_baseline_declares_not_null_unique_uuid(self) -> None:
        baseline = _BASELINE_PATH.read_text(encoding="utf-8")
        assert 'sa.Column("library_uuid", sa.String(length=36), nullable=False)' in baseline
        assert "uq_libraries_library_uuid" in baseline

    def test_upgrade_orders_add_backfill_then_enforce(self) -> None:
        tree = ast.parse(_MIGRATION_PATH.read_text(encoding="utf-8"))
        upgrade = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "upgrade")
        order: list[str] = []
        for node in ast.walk(upgrade):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr in {"add_column", "alter_column", "create_unique_constraint"}:
                order.append(node.func.attr)
        assert order == ["add_column", "alter_column", "create_unique_constraint"]
        source = _MIGRATION_PATH.read_text(encoding="utf-8")
        assert "uuid.uuid4()" in source
        # Minted in Python, not via a database-generated default/extension.
        assert "sa.func.gen_random_uuid" not in source
        assert "server_default" not in source


@pytest.mark.unit
class TestLibraryUuidMigrationBackfill:
    """Backfill existing rows before enforcing the identity contract."""

    def _install(self, monkeypatch: pytest.MonkeyPatch, *, has_column: bool) -> tuple[Any, Any, _RecordingBind]:
        from unittest.mock import MagicMock

        migration = _load_migration()
        bind = _RecordingBind([(1,), (2,)])
        monkeypatch.setattr(migration, "sa", _FakeSA(has_column=has_column))
        operation = MagicMock()
        operation.get_bind.return_value = bind
        monkeypatch.setattr(migration, "op", operation)
        return migration, operation, bind

    def test_existing_rows_are_backfilled_with_distinct_uuids(self, monkeypatch: pytest.MonkeyPatch) -> None:
        migration, operation, bind = self._install(monkeypatch, has_column=False)
        monkeypatch.setattr(uuid, "uuid4", _DeterministicUuid())

        migration.upgrade()

        operation.add_column.assert_called_once()
        operation.alter_column.assert_called_once()
        assert operation.alter_column.call_args.kwargs["nullable"] is False
        operation.create_unique_constraint.assert_called_once_with(
            "uq_libraries_library_uuid", "libraries", ["library_uuid"]
        )

        updates = [parameters for _statement, parameters in bind.calls if parameters is not None]
        assert len(updates) == 2
        minted = [parameters["library_uuid"] for parameters in updates]
        assert all(isinstance(value, str) and value for value in minted)
        assert len(set(minted)) == 2
        for value in minted:
            uuid.UUID(value)

    def test_baseline_created_column_makes_upgrade_a_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        migration, operation, bind = self._install(monkeypatch, has_column=True)

        migration.upgrade()

        operation.add_column.assert_not_called()
        operation.alter_column.assert_not_called()
        operation.create_unique_constraint.assert_not_called()
        assert bind.calls == []

    def test_downgrade_drops_constraint_then_column(self, monkeypatch: pytest.MonkeyPatch) -> None:
        migration, operation, _bind = self._install(monkeypatch, has_column=True)

        migration.downgrade()

        operation.drop_constraint.assert_called_once_with("uq_libraries_library_uuid", "libraries", type_="unique")
        operation.drop_column.assert_called_once_with("libraries", "library_uuid")

    def test_downgrade_without_column_is_a_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        migration, operation, _bind = self._install(monkeypatch, has_column=False)

        migration.downgrade()

        operation.drop_constraint.assert_not_called()
        operation.drop_column.assert_not_called()


class _DeterministicUuid:
    """Deterministic ``uuid.uuid4`` substitute so backfill values differ per call."""

    def __init__(self) -> None:
        self._counter = 0

    def __call__(self) -> uuid.UUID:
        self._counter += 1
        return uuid.UUID(int=self._counter)


@pytest.mark.integration
@pytest.mark.requires_database
@pytest.mark.skipif(
    not _PG_URL,
    reason=(
        "requires a live PostgreSQL server via NOMARR_TEST_DATABASE_URL; "
        "Docker/PostgreSQL unavailable locally so this evidence is environment-blocked"
    ),
)
class TestLibraryUuidMigrationOnPostgres:
    """Live-PostgreSQL backfill evidence for the pre-amendment database path.

    ``NOMARR_TEST_DATABASE_URL`` must point at a throwaway database: this test
    drops and recreates the ``libraries`` table in the default schema.
    """

    def _prepare(self, engine: sa.Engine) -> sa.Table:
        metadata = sa.MetaData()
        libraries = sa.Table(
            "libraries",
            metadata,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(120), nullable=False),
        )
        metadata.drop_all(engine)
        metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(libraries.insert().values(id=1, name="a"))
            conn.execute(libraries.insert().values(id=2, name="b"))
        return libraries

    def test_backfills_existing_rows_and_enforces_identity(self) -> None:
        engine = sa.create_engine(_PG_URL or "")
        try:
            self._prepare(engine)
            migration = _load_migration()
            with engine.begin() as conn:
                context = MigrationContext.configure(conn)
                with Operations.context(context):
                    migration.upgrade()

            inspector = sa.inspect(engine)
            column = {c["name"]: c for c in inspector.get_columns("libraries")}["library_uuid"]
            assert column["nullable"] is False
            constraint_names = {c["name"] for c in inspector.get_unique_constraints("libraries")}
            assert "uq_libraries_library_uuid" in constraint_names
            with engine.connect() as conn:
                rows = conn.execute(sa.text("SELECT library_uuid FROM libraries ORDER BY id")).fetchall()
            values = [row[0] for row in rows]
            assert all(isinstance(value, str) and value for value in values)
            assert len(set(values)) == 2
            for value in values:
                uuid.UUID(value)
        finally:
            engine.dispose()

    def test_upgrade_is_idempotent_on_amended_baseline_schema(self) -> None:
        engine = sa.create_engine(_PG_URL or "")
        try:
            self._prepare(engine)
            migration = _load_migration()
            for _ in range(2):
                with engine.begin() as conn:
                    context = MigrationContext.configure(conn)
                    with Operations.context(context):
                        migration.upgrade()
            inspector = sa.inspect(engine)
            column = {c["name"]: c for c in inspector.get_columns("libraries")}["library_uuid"]
            assert column["nullable"] is False
        finally:
            engine.dispose()

    def test_downgrade_removes_the_identity_column(self) -> None:
        engine = sa.create_engine(_PG_URL or "")
        try:
            self._prepare(engine)
            migration = _load_migration()
            with engine.begin() as conn:
                context = MigrationContext.configure(conn)
                with Operations.context(context):
                    migration.upgrade()
            with engine.begin() as conn:
                context = MigrationContext.configure(conn)
                with Operations.context(context):
                    migration.downgrade()
            column_names = {c["name"] for c in sa.inspect(engine).get_columns("libraries")}
            assert "library_uuid" not in column_names
        finally:
            engine.dispose()
