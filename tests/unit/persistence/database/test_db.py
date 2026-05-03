"""Unit tests for ``Database.register()`` template namespace behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.persistence.db import Database


class TestDatabaseRegister:
    """Direct unit tests for ``Database.register()``."""

    def _make_database(self) -> Database:
        """Construct a ``Database`` instance without connecting to ArangoDB."""
        db: Database = object.__new__(Database)
        db._template_namespaces = {}  # type: ignore[attr-defined]
        db.db = MagicMock()
        return db

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_register_success_stores_namespace_and_sets_attribute(self) -> None:
        """``register()`` stores the namespace in ``_template_namespaces`` and as an attribute."""
        database = self._make_database()
        database.db.has_collection.return_value = True
        fake_ns = MagicMock()

        with patch("nomarr.persistence.db.SchemaConstructor") as mock_ctor:
            mock_ctor.return_value.build_template_namespace.return_value = fake_ns
            result = database.register("vectors_track_hot__effnet__lib1", "vectors_track_hot")

        assert result is fake_ns
        assert database._template_namespaces["vectors_track_hot__effnet__lib1"] is fake_ns
        assert database.__dict__["vectors_track_hot__effnet__lib1"] is fake_ns

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_register_idempotent_returns_cached_without_db_check(self) -> None:
        """Calling ``register()`` twice with the same name returns the cached namespace."""
        database = self._make_database()
        cached_ns = MagicMock()
        database._template_namespaces["vectors_track_hot__effnet__lib1"] = cached_ns

        result = database.register("vectors_track_hot__effnet__lib1", "vectors_track_hot")

        assert result is cached_ns
        database.db.has_collection.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_register_raises_when_collection_not_in_arango(self) -> None:
        """``register()`` raises ``ValueError`` when the ArangoDB collection does not exist."""
        database = self._make_database()
        database.db.has_collection.return_value = False

        with pytest.raises(ValueError, match="does not exist in ArangoDB"):
            database.register("vectors_track_hot__effnet__lib1", "vectors_track_hot")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_register_raises_for_non_template_schema_name(self) -> None:
        """``register()`` raises ``ValueError`` when ``template_name`` is not a TEMPLATE collection."""
        database = self._make_database()
        database.db.has_collection.return_value = True

        with pytest.raises(ValueError, match="is not a TEMPLATE collection"):
            database.register("libraries__foo", "libraries")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_register_raises_for_unknown_schema_name(self) -> None:
        """``register()`` raises ``ValueError`` when ``template_name`` does not exist in ``SCHEMA``."""
        database = self._make_database()
        database.db.has_collection.return_value = True

        with pytest.raises(ValueError, match="is not a TEMPLATE collection"):
            database.register("nonexistent__foo", "nonexistent_template")
