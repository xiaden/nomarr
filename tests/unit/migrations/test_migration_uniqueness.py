"""Code-smell test: verify no migration file declares a duplicate MIGRATION_VERSION."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

pytestmark = pytest.mark.code_smell

_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "nomarr" / "migrations"
_MIGRATIONS_PACKAGE = "nomarr.migrations"


class TestMigrationVersionUniqueness:
    """Verify all migration files declare unique MIGRATION_VERSION values."""

    @pytest.mark.code_smell
    def test_no_duplicate_migration_versions(self) -> None:
        """Each V*.py in nomarr/migrations/ must declare a unique MIGRATION_VERSION."""
        versions: list[str] = []
        for path in sorted(_MIGRATIONS_DIR.glob("V*.py")):
            name = path.stem
            module = importlib.import_module(f"{_MIGRATIONS_PACKAGE}.{name}")
            versions.append(module.MIGRATION_VERSION)

        duplicated = [v for v in versions if versions.count(v) > 1]
        assert len(versions) == len(set(versions)), (
            f"Duplicate MIGRATION_VERSION values detected: {list(set(duplicated))}"
        )
