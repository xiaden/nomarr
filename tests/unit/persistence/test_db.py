"""Unit tests for ``nomarr.persistence.db.Database`` public surface."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.persistence.api import AppDb, LibraryDb, MlDb


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

    def _make_db(self) -> Database:  # type: ignore[name-defined]  # noqa: F821
        from nomarr.persistence.db import Database

        with patch("nomarr.persistence.db.create_arango_client", return_value=MagicMock()):
            return Database(hosts="http://localhost:8529", password="test")

    def test_get_version_returns_string_value(self) -> None:
        """get_version() returns the stored semver string."""
        db = self._make_db()
        mock_coll = MagicMock()
        mock_coll.get.return_value = {"_key": "version", "value": "0.14.0"}
        db.db.collection.return_value = mock_coll

        assert db.get_version() == "0.14.0"

    def test_get_version_returns_none_when_absent(self) -> None:
        """get_version() returns None when no version doc exists."""
        db = self._make_db()
        mock_coll = MagicMock()
        mock_coll.get.return_value = None
        db.db.collection.return_value = mock_coll

        assert db.get_version() is None

    def test_set_version_inserts_with_overwrite(self) -> None:
        """set_version() inserts the version doc with overwrite=True."""
        db = self._make_db()
        mock_coll = MagicMock()
        db.db.collection.return_value = mock_coll

        db.set_version("0.15.0")

        mock_coll.insert.assert_called_once_with(
            {"_key": "version", "value": "0.15.0"},
            overwrite=True,
        )

    def test_close_does_not_raise(self) -> None:
        """close() completes without raising."""
        db = self._make_db()
        db.close()  # should not raise
