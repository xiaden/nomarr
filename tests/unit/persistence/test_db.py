"""Unit tests for ``nomarr.persistence.db.Database`` public surface."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

import nomarr.persistence.api as persistence_api
from nomarr.persistence.api import AppDb, AppMaintenanceDb, LibraryDb, LibraryMaintenanceDb, MlDb, MlMaintenanceDb
from nomarr.persistence.api.application import AppLegacyNavidromeDb
from nomarr.persistence.database.app_aql import AppAqlOperations
from nomarr.persistence.database.library_files_aql import LibraryFilesAqlOperations

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


@pytest.mark.unit
@pytest.mark.mocked
class TestDatabaseInit:
    """Tests for Database.__init__ validation."""

    def test_raises_when_arango_host_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """RuntimeError raised when ARANGO_HOST env var is absent."""
        monkeypatch.delenv("ARANGO_HOST", raising=False)

        from nomarr.persistence.db import Database

        with pytest.raises(RuntimeError, match="ARANGO_HOST"):
            Database(hosts=None, password="test")

    def test_raises_when_password_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """RuntimeError raised when no password is available."""
        monkeypatch.setenv("ARANGO_HOST", "http://localhost:8529")

        from nomarr.persistence.db import Database

        with (
            patch("nomarr.persistence.db.Database._load_password_from_config", return_value=None),
            pytest.raises(RuntimeError, match="password"),
        ):
            Database(hosts="http://localhost:8529", password=None)

    def test_exposes_library_ml_app_attributes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Constructed Database exposes .library, .ml, and .app tier attributes."""
        monkeypatch.setenv("ARANGO_HOST", "http://localhost:8529")

        mock_safe_db = MagicMock()

        from nomarr.persistence.db import Database

        with patch("nomarr.persistence.db.create_arango_client", return_value=mock_safe_db):
            db = Database(hosts="http://localhost:8529", password="test")

        assert isinstance(db.library, LibraryDb)
        assert isinstance(db.ml, MlDb)
        assert isinstance(db.app, AppDb)

    def test_exposes_raw_db_attribute(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Constructed Database exposes .db for raw ArangoDB access."""
        monkeypatch.setenv("ARANGO_HOST", "http://localhost:8529")

        mock_safe_db = MagicMock()

        from nomarr.persistence.db import Database

        with patch("nomarr.persistence.db.create_arango_client", return_value=mock_safe_db):
            db = Database(hosts="http://localhost:8529", password="test")

        assert db.db is mock_safe_db


@pytest.mark.unit
@pytest.mark.mocked
class TestDatabaseVersioning:
    """Tests for Database.get_version() and set_version()."""

    def _make_db(self) -> Database:
        from nomarr.persistence.db import Database

        with patch("nomarr.persistence.db.create_arango_client", return_value=MagicMock()):
            return Database(hosts="http://localhost:8529", password="test")

    def test_get_version_returns_string_value(self) -> None:
        """get_version() returns the stored semver string."""
        db = self._make_db()
        mock_coll = MagicMock()
        mock_coll.get.return_value = {"_key": "version", "value": "0.14.0"}

        with patch.object(db.db, "collection", return_value=mock_coll):
            assert db.get_version() == "0.14.0"

    def test_get_version_returns_none_when_absent(self) -> None:
        """get_version() returns None when no version doc exists."""
        db = self._make_db()
        mock_coll = MagicMock()
        mock_coll.get.return_value = None

        with patch.object(db.db, "collection", return_value=mock_coll):
            assert db.get_version() is None

    def test_set_version_inserts_with_overwrite(self) -> None:
        """set_version() inserts the version doc with overwrite=True."""
        db = self._make_db()
        mock_coll = MagicMock()

        with patch.object(db.db, "collection", return_value=mock_coll):
            db.set_version("0.15.0")

        mock_coll.insert.assert_called_once_with(
            {"_key": "version", "value": "0.15.0"},
            overwrite=True,
        )

    def test_close_does_not_raise(self) -> None:
        """close() completes without raising."""
        db = self._make_db()
        db.close()  # should not raise


@pytest.mark.unit
def test_persistence_api_exports_final_public_facades() -> None:
    """persistence.api __all__ exports exactly the six Tier 3 public facade classes."""
    assert persistence_api.__all__ == [
        "AppDb",
        "AppMaintenanceDb",
        "LibraryDb",
        "LibraryMaintenanceDb",
        "MlDb",
        "MlMaintenanceDb",
    ]


@pytest.mark.unit
@pytest.mark.mocked
def test_database_exposes_maintenance_surfaces_without_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Database exposes .maintenance sub-facades on each domain group but has no top-level .admin surface."""
    monkeypatch.setenv("ARANGO_HOST", "http://localhost:8529")

    mock_safe_db = MagicMock()

    from nomarr.persistence.db import Database

    with patch("nomarr.persistence.db.create_arango_client", return_value=mock_safe_db):
        db = Database(hosts="http://localhost:8529", password="test")

    assert isinstance(db.library.maintenance, LibraryMaintenanceDb)
    assert isinstance(db.app.maintenance, AppMaintenanceDb)
    assert isinstance(db.ml.maintenance, MlMaintenanceDb)
    assert not hasattr(db, "admin")


@pytest.mark.unit
@pytest.mark.mocked
def test_database_keeps_compatibility_aliases_pointing_at_tier2_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compatibility aliases keep only the evidence-backed Tier 2 debt; removed aliases are absent."""
    monkeypatch.setenv("ARANGO_HOST", "http://localhost:8529")

    mock_safe_db = MagicMock()

    from nomarr.persistence.db import Database

    with patch("nomarr.persistence.db.create_arango_client", return_value=mock_safe_db):
        db = Database(hosts="http://localhost:8529", password="test")

    expected_aliases = {
        "libraries": "libraries_aql",
        "library_files": "library_files_aql",
        "file_states": "file_states_aql",
    }

    for alias_name, implementation_name in expected_aliases.items():
        assert getattr(db, alias_name) is getattr(db, implementation_name)

    assert not hasattr(db, "tags")
    assert not hasattr(db, "scan")
    assert not hasattr(db, "ml_streams")
    assert not hasattr(db, "ml_models")
    assert not hasattr(db, "vectors")
    assert not hasattr(db, "navidrome")


@pytest.mark.unit
@pytest.mark.mocked
def test_database_keeps_legacy_navidrome_isolated_under_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy Navidrome persistence is isolated under db.app.legacy_navidrome; not directly accessible on Database or flattened onto AppDb."""
    monkeypatch.setenv("ARANGO_HOST", "http://localhost:8529")

    mock_safe_db = MagicMock()

    from nomarr.persistence.db import Database

    with patch("nomarr.persistence.db.create_arango_client", return_value=mock_safe_db):
        db = Database(hosts="http://localhost:8529", password="test")

    assert isinstance(db.app.legacy_navidrome, AppLegacyNavidromeDb)
    assert not hasattr(db, "legacy_navidrome")
    assert not hasattr(db.app, "get_nd_track")


@pytest.mark.unit
@pytest.mark.mocked
def test_database_keeps_representative_tier2_bindings_internal_and_facades_free_of_primitive_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Representative Tier 2 bindings remain wired on Database without promoting Tier 1 helpers onto Tier 3 facades."""
    monkeypatch.setenv("ARANGO_HOST", "http://localhost:8529")

    mock_safe_db = MagicMock()

    from nomarr.persistence.db import Database

    with patch("nomarr.persistence.db.create_arango_client", return_value=mock_safe_db):
        db = Database(hosts="http://localhost:8529", password="test")

    assert isinstance(db.app_aql, AppAqlOperations)
    assert isinstance(db.library_files_aql, LibraryFilesAqlOperations)
    assert not hasattr(db.app, "delete_many_by_field")
    assert not hasattr(db.library, "delete_many_by_field")
