"""Unit tests for ``Database`` collection wiring and dynamic vector registration."""

from __future__ import annotations

import os
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.collections import FileHasState, LibraryFiles
from nomarr.persistence.collections_base import DocumentCollection, EdgeCollection, VectorCollection
from nomarr.persistence.db import _COLLECTION_FIRST_ROOTS, Database, _matches_name_pattern


class TestDatabaseInitialization:
    """Unit tests for ``Database.__init__()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_initializes_collection_instances_and_collection_lists(self) -> None:
        fake_safe_db = cast("SafeDatabase", MagicMock(spec=SafeDatabase))

        with (
            patch.dict(os.environ, {"ARANGO_HOST": "http://localhost:8529"}, clear=False),
            patch("nomarr.persistence.db.create_arango_client", return_value=fake_safe_db) as create_client_mock,
            patch.object(Database, "_load_password_from_config", return_value="secret"),
            patch.object(Database, "_compile_all_cascades") as compile_mock,
        ):
            db = Database()

        create_client_mock.assert_called_once_with(
            hosts="http://localhost:8529",
            username="nomarr",
            password="secret",
            db_name="nomarr",
        )
        compile_mock.assert_called_once_with()
        assert db.db is fake_safe_db
        assert isinstance(db.library_files, LibraryFiles)
        assert isinstance(db.file_has_state, FileHasState)
        assert db.library_files._db is fake_safe_db
        assert db.file_has_state._db is fake_safe_db
        assert db.library_files in db._document_collections
        assert db.file_has_state in db._edge_collections
        assert all(isinstance(coll, DocumentCollection) for coll in db._document_collections)
        assert all(isinstance(coll, EdgeCollection) for coll in db._edge_collections)
        assert db._registered == {}

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_does_not_create_vector_collection_attributes_before_register(self) -> None:
        fake_safe_db = cast("SafeDatabase", MagicMock(spec=SafeDatabase))

        with (
            patch.dict(os.environ, {"ARANGO_HOST": "http://localhost:8529"}, clear=False),
            patch("nomarr.persistence.db.create_arango_client", return_value=fake_safe_db),
            patch.object(Database, "_load_password_from_config", return_value="secret"),
            patch.object(Database, "_compile_all_cascades"),
        ):
            db = Database()

        assert not hasattr(db, "vectors_track_hot")
        assert not hasattr(db, "vectors_track_cold")


class TestDatabaseRegister:
    """Direct unit tests for ``Database.register()``."""

    def _make_database(self) -> Database:
        db: Database = object.__new__(Database)
        db._registered = {}
        db._vector_collections = []
        db.db = MagicMock()
        return db

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_register_success_stores_vector_instance_and_sets_attribute(self) -> None:
        database = self._make_database()
        database.db.has_collection.return_value = True

        class FakeVectorTemplate(VectorCollection):
            VECTOR_TIER = "hot"
            NAME_PATTERN = "vectors_track_hot__{model}__{library}"

        with (
            patch.dict(
                "nomarr.persistence.db._VECTOR_TEMPLATE_CLASSES",
                {"vectors_track_hot": FakeVectorTemplate},
                clear=True,
            ),
            patch.object(Database, "_reattach_vector_cascades") as reattach_mock,
        ):
            result = database.register("vectors_track_hot__effnet__lib1", "vectors_track_hot")

        assert isinstance(result, FakeVectorTemplate)
        assert result._name == "vectors_track_hot__effnet__lib1"
        assert result._db is database.db
        assert database._registered["vectors_track_hot__effnet__lib1"] is result
        assert database.__dict__["vectors_track_hot__effnet__lib1"] is result
        reattach_mock.assert_called_once_with()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_register_idempotent_returns_cached_without_db_check(self) -> None:
        database = self._make_database()

        class CachedVectorTemplate(VectorCollection):
            VECTOR_TIER = "hot"
            NAME_PATTERN = "vectors_track_hot__{model}__{library}"

        cached = CachedVectorTemplate(database.db, "vectors_track_hot__effnet__lib1")
        database._registered["vectors_track_hot__effnet__lib1"] = cached

        result = database.register("vectors_track_hot__effnet__lib1", "vectors_track_hot")

        assert result is cached
        database.db.has_collection.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_register_raises_when_collection_not_in_arango(self) -> None:
        database = self._make_database()
        database.db.has_collection.return_value = False

        with pytest.raises(ValueError, match="does not exist in ArangoDB"):
            database.register("vectors_track_hot__effnet__lib1", "vectors_track_hot")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_register_raises_for_unknown_template_name(self) -> None:
        database = self._make_database()
        database.db.has_collection.return_value = True

        with pytest.raises(ValueError, match="is not a supported template collection"):
            database.register("nonexistent__foo", "nonexistent_template")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_register_raises_when_vector_template_name_does_not_match_pattern(self) -> None:
        database = self._make_database()
        database.db.has_collection.return_value = True

        class FakeVectorTemplate(VectorCollection):
            VECTOR_TIER = "hot"
            NAME_PATTERN = "vectors_track_hot__{model}__{library}"

        with (
            patch.dict(
                "nomarr.persistence.db._VECTOR_TEMPLATE_CLASSES",
                {"vectors_track_hot": FakeVectorTemplate},
                clear=True,
            ),
            pytest.raises(ValueError, match="does not match template pattern"),
        ):
            database.register("vectors_track_hot__bad", "vectors_track_hot")


class TestDatabaseGetVersion:
    """Direct unit tests for ``Database.get_version()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_version_returns_string_value_from_meta_doc(self) -> None:
        database: Database = object.__new__(Database)
        meta_mock = cast("Any", MagicMock())
        database.meta = meta_mock
        meta_mock.get.return_value = {"value": "0.28.0"}

        result = database.get_version()

        assert result == "0.28.0"
        meta_mock.get.assert_called_once_with(key="version")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_version_returns_none_when_meta_doc_is_not_dict(self) -> None:
        database: Database = object.__new__(Database)
        meta_mock = cast("Any", MagicMock())
        database.meta = meta_mock
        meta_mock.get.return_value = None

        result = database.get_version()

        assert result is None
        meta_mock.get.assert_called_once_with(key="version")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_version_returns_none_when_value_is_not_string(self) -> None:
        database: Database = object.__new__(Database)
        meta_mock = cast("Any", MagicMock())
        database.meta = meta_mock
        meta_mock.get.return_value = {"value": 28}

        result = database.get_version()

        assert result is None
        meta_mock.get.assert_called_once_with(key="version")


class TestDatabaseSetVersion:
    """Direct unit tests for ``Database.set_version()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_set_version_upserts_version_doc(self) -> None:
        database: Database = object.__new__(Database)
        meta_mock = cast("Any", MagicMock())
        database.meta = meta_mock

        database.set_version("0.28.0")

        meta_mock.upsert.assert_called_once_with(key="version", fields={"value": "0.28.0"})


class TestMatchesNamePattern:
    """Unit tests for ``_matches_name_pattern()``."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("resolved_name", "name_pattern", "expected"),
        [
            pytest.param("foo__bar", "foo__bar", True, id="exact-static-match"),
            pytest.param(
                "vectors_track_hot__effnet__lib1",
                "vectors_track_hot__{backbone_id}__{library_key}",
                True,
                id="single-placeholder-match",
            ),
            pytest.param(
                "vectors_track_hot__bad",
                "vectors_track_hot__{backbone_id}__{library_key}",
                False,
                id="wrong-number-of-parts",
            ),
            pytest.param(
                "vectors_track_hot____lib1",
                "vectors_track_hot__{backbone_id}__{library_key}",
                False,
                id="empty-placeholder-segment",
            ),
            pytest.param(
                "vectors_track_cold__effnet__lib1",
                "vectors_track_hot__{backbone_id}__{library_key}",
                False,
                id="static-part-mismatch",
            ),
        ],
    )
    def test_matches_name_pattern(self, resolved_name: str, name_pattern: str, expected: bool) -> None:
        assert _matches_name_pattern(resolved_name, name_pattern) is expected


class TestDatabaseCollectionFirstSurface:
    """Unit tests for consistent collection-first surface wiring on the facade."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_static_bindings_expose_normative_collection_first_roots(self) -> None:
        fake_safe_db = cast("SafeDatabase", MagicMock(spec=SafeDatabase))

        with (
            patch.dict(os.environ, {"ARANGO_HOST": "http://localhost:8529"}, clear=False),
            patch("nomarr.persistence.db.create_arango_client", return_value=fake_safe_db),
            patch.object(Database, "_load_password_from_config", return_value="secret"),
            patch.object(Database, "_compile_all_cascades"),
        ):
            db = Database()

        for collection in (db.meta, db.library_files, db.file_has_state):
            for root_name in _COLLECTION_FIRST_ROOTS:
                assert hasattr(collection, root_name), f"{collection._name} missing {root_name}"

        assert db._vector_collections == []

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_register_runtime_vector_exposes_normative_roots_and_tracks_instance(self) -> None:
        database: Database = object.__new__(Database)
        database._registered = {}
        database._vector_collections = []
        database.db = MagicMock()
        database.db.has_collection.return_value = True

        class FakeVectorTemplate(VectorCollection):
            VECTOR_TIER = "hot"
            NAME_PATTERN = "vectors_track_hot__{model}__{library}"

        with (
            patch.dict(
                "nomarr.persistence.db._VECTOR_TEMPLATE_CLASSES",
                {"vectors_track_hot": FakeVectorTemplate},
                clear=True,
            ),
            patch.object(Database, "_reattach_vector_cascades") as reattach_mock,
        ):
            result = database.register("vectors_track_hot__effnet__lib1", "vectors_track_hot")

        assert result is database._registered["vectors_track_hot__effnet__lib1"]
        assert database._vector_collections == [result]
        assert database.vectors_track_hot__effnet__lib1 is result
        for root_name in _COLLECTION_FIRST_ROOTS:
            assert hasattr(result, root_name), f"registered vector missing {root_name}"
        reattach_mock.assert_called_once_with()

    @pytest.mark.unit
    def test_bind_collection_instance_rejects_missing_collection_first_roots(self) -> None:
        database: Database = object.__new__(Database)

        with pytest.raises(TypeError, match="missing collection-first roots"):
            database._bind_collection_instance("broken", cast("Any", object()))
