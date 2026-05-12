"""Tests for migration_runner_comp.py."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType
from unittest.mock import ANY, MagicMock, patch

import pytest

from nomarr.components.platform.migration_runner_comp import (
    MigrationError,
    apply_migration,
    check_duplicate_versions,
    discover_migrations,
    get_pending_migrations,
    run_pending_migrations,
)


def _make_migration_module(version: str, description: str = "Test migration") -> MagicMock:
    """Return a mock module with all required migration attributes."""
    m = MagicMock()
    m.MIGRATION_VERSION = version
    m.DESCRIPTION = description
    m.upgrade = MagicMock()
    return m


class TestDiscoverMigrations:
    """Tests for discover_migrations()."""

    @pytest.mark.unit
    def test_returns_sorted_list(self, tmp_path: Path) -> None:
        """Discovered migrations are sorted by semver MIGRATION_VERSION, not filename."""
        (tmp_path / "V002_second.py").write_text("")
        (tmp_path / "V001_first.py").write_text("")
        mod_first = _make_migration_module("0.1.0")
        mod_second = _make_migration_module("0.2.0")

        with (
            patch("nomarr.components.platform.migration_runner_comp.MIGRATIONS_DIR", tmp_path),
            patch(
                "nomarr.components.platform.migration_runner_comp.importlib.import_module",
                side_effect=[mod_first, mod_second],
            ),
        ):
            result = discover_migrations()

        assert len(result) == 2
        assert result[0][1].MIGRATION_VERSION == "0.1.0"
        assert result[1][1].MIGRATION_VERSION == "0.2.0"

    @pytest.mark.unit
    def test_raises_migration_error_on_invalid_module(self, tmp_path: Path) -> None:
        """MigrationError raised when a module is missing MIGRATION_VERSION."""
        (tmp_path / "V001_bad.py").write_text("")
        bad_module = MagicMock(spec=["DESCRIPTION", "upgrade"])
        bad_module.DESCRIPTION = "Missing version"
        bad_module.upgrade = MagicMock()

        with (
            patch("nomarr.components.platform.migration_runner_comp.MIGRATIONS_DIR", tmp_path),
            patch(
                "nomarr.components.platform.migration_runner_comp.importlib.import_module",
                return_value=bad_module,
            ),
            pytest.raises(MigrationError, match="missing required attribute"),
        ):
            discover_migrations()


class TestCheckDuplicateVersions:
    """Tests for check_duplicate_versions()."""

    @pytest.mark.unit
    def test_raises_on_duplicate_migration_version(self) -> None:
        """MigrationError raised when two migrations share the same MIGRATION_VERSION."""
        mod_a = _make_migration_module("1.0.0")
        mod_b = _make_migration_module("1.0.0")
        migrations: list[tuple[str, ModuleType]] = [("V001_a", mod_a), ("V001_b", mod_b)]  # type: ignore[assignment]

        with pytest.raises(MigrationError, match="Duplicate MIGRATION_VERSION"):
            check_duplicate_versions(migrations)

    @pytest.mark.unit
    def test_passes_on_unique_versions(self) -> None:
        """No exception raised when all MIGRATION_VERSION values are distinct."""
        mod_a = _make_migration_module("1.0.0")
        mod_b = _make_migration_module("1.1.0")
        migrations: list[tuple[str, ModuleType]] = [("V001_a", mod_a), ("V002_b", mod_b)]  # type: ignore[assignment]

        # Should not raise
        check_duplicate_versions(migrations)


class TestGetPendingMigrations:
    """Tests for get_pending_migrations()."""

    @pytest.mark.unit
    def test_returns_all_on_fresh_database(self) -> None:
        """All migrations returned when current_db_version is None."""
        mod_a = _make_migration_module("0.1.0")
        mod_b = _make_migration_module("0.2.0")
        all_migrations: list[tuple[str, ModuleType]] = [("V001", mod_a), ("V002", mod_b)]  # type: ignore[assignment]

        result = get_pending_migrations(all_migrations, None)

        assert result == all_migrations

    @pytest.mark.unit
    def test_skips_applied_migrations_by_version(self) -> None:
        """Migrations at or below current_db_version are not included in pending list."""
        mod_a = _make_migration_module("0.1.0")
        mod_b = _make_migration_module("0.2.0")
        all_migrations: list[tuple[str, ModuleType]] = [("V001", mod_a), ("V002", mod_b)]  # type: ignore[assignment]

        result = get_pending_migrations(all_migrations, "0.1.0")

        assert len(result) == 1
        assert result[0][0] == "V002"

    @pytest.mark.unit
    def test_returns_empty_when_all_applied(self) -> None:
        """Empty list returned when DB version is at or beyond the latest migration."""
        mod_a = _make_migration_module("0.1.0")
        all_migrations: list[tuple[str, ModuleType]] = [("V001", mod_a)]  # type: ignore[assignment]

        result = get_pending_migrations(all_migrations, "0.2.0")

        assert result == []


class TestApplyMigration:
    """Tests for apply_migration()."""

    @pytest.mark.unit
    def test_calls_module_upgrade_with_raw_db(self) -> None:
        """apply_migration calls module.upgrade passing db.db."""
        module = _make_migration_module("1.0.0")
        db = MagicMock()

        apply_migration("V001_test", module, db)

        module.upgrade.assert_called_once_with(db.db)

    @pytest.mark.unit
    def test_calls_record_migration_started_with_name_and_version(self) -> None:
        """record_migration_started is called with the migration name and version."""
        module = _make_migration_module("1.0.0")
        db = MagicMock()

        apply_migration("V001_test", module, db)

        db.app.upsert_migration.assert_any_call(
            "V001_test",
            {
                "status": "in_progress",
                "started_at": ANY,
                "migration_version": "1.0.0",
            },
        )

    @pytest.mark.unit
    def test_calls_mark_migration_applied_after_upgrade(self) -> None:
        """mark_migration_applied is called once after upgrade() succeeds."""
        module = _make_migration_module("1.0.0")
        db = MagicMock()

        apply_migration("V001_test", module, db)

        db.app.upsert_migration.assert_any_call(
            "V001_test",
            {
                "status": "applied",
                "applied_at": ANY,
                "duration_ms": ANY,
            },
        )

    @pytest.mark.unit
    def test_calls_set_version_with_migration_version(self) -> None:
        """db.set_version is called with the migration's MIGRATION_VERSION."""
        module = _make_migration_module("1.0.0")
        db = MagicMock()

        apply_migration("V001_test", module, db)

        db.set_version.assert_called_once_with("1.0.0")


class TestRunPendingMigrations:
    """Tests for run_pending_migrations()."""

    @pytest.mark.unit
    def test_calls_get_version_on_db(self) -> None:
        """run_pending_migrations reads the current DB version before discovering migrations."""
        db = MagicMock()
        db.get_version.return_value = None

        with (
            patch(
                "nomarr.components.platform.migration_runner_comp.discover_migrations",
                return_value=[],
            ),
            patch("nomarr.components.platform.migration_runner_comp.check_duplicate_versions"),
            patch(
                "nomarr.components.platform.migration_runner_comp.get_pending_migrations",
                return_value=[],
            ),
        ):
            run_pending_migrations(db)

        db.get_version.assert_called()

    @pytest.mark.unit
    def test_calls_apply_migration_for_each_pending(self) -> None:
        """run_pending_migrations dispatches apply_migration for every pending migration."""
        mod = _make_migration_module("0.1.0")
        db = MagicMock()
        db.get_version.return_value = None

        with (
            patch(
                "nomarr.components.platform.migration_runner_comp.discover_migrations",
                return_value=[("V001", mod)],
            ),
            patch("nomarr.components.platform.migration_runner_comp.check_duplicate_versions"),
            patch(
                "nomarr.components.platform.migration_runner_comp.get_pending_migrations",
                return_value=[("V001", mod)],
            ),
            patch(
                "nomarr.components.platform.migration_runner_comp.apply_migration",
            ) as mock_apply,
        ):
            run_pending_migrations(db)

        mock_apply.assert_called_once_with("V001", mod, db)

    @pytest.mark.unit
    def test_calls_set_version_via_apply_migration(self) -> None:
        """db.set_version is called (via apply_migration) after each migration is applied."""
        mod = _make_migration_module("0.1.0")
        db = MagicMock()
        db.get_version.return_value = None

        with (
            patch(
                "nomarr.components.platform.migration_runner_comp.discover_migrations",
                return_value=[("V001", mod)],
            ),
            patch("nomarr.components.platform.migration_runner_comp.check_duplicate_versions"),
            patch(
                "nomarr.components.platform.migration_runner_comp.get_pending_migrations",
                return_value=[("V001", mod)],
            ),
        ):
            run_pending_migrations(db)

        db.set_version.assert_called_once_with("0.1.0")
