"""Unit tests for ``Database`` collection binding and dynamic registration."""

from __future__ import annotations

import os
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.base import DocumentCollection, VectorCollection, _BoundFieldAccessor, bind_all_collections
from nomarr.persistence.collections import LibraryFiles
from nomarr.persistence.db import Database, _matches_name_pattern


class TestBindAllCollections:
    """Unit tests for ``bind_all_collections()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_sets_db_on_document_collection_base(self) -> None:
        """``bind_all_collections()`` binds the shared ``SafeDatabase`` to collection bases."""
        safe_db = cast("SafeDatabase", MagicMock(spec=SafeDatabase))
        original_document_db = DocumentCollection._db
        original_library_files_db = LibraryFiles._db

        try:
            bind_all_collections(safe_db)

            assert DocumentCollection._db is safe_db
            assert LibraryFiles._db is safe_db
        finally:
            DocumentCollection._db = original_document_db
            LibraryFiles._db = original_library_files_db


class TestDatabaseInitialization:
    """Unit tests for ``Database.__init__()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_calls_bind_all_collections_and_exposes_collection_classes(self) -> None:
        """``Database()`` binds collections once and stores class refs on the facade."""
        fake_safe_db = cast("SafeDatabase", MagicMock(spec=SafeDatabase))

        with (
            patch.dict(os.environ, {"ARANGO_HOST": "http://localhost:8529"}, clear=False),
            patch("nomarr.persistence.db.create_arango_client", return_value=fake_safe_db) as create_client_mock,
            patch("nomarr.persistence.db.bind_all_collections") as bind_mock,
            patch.object(Database, "_load_password_from_config", return_value="secret"),
        ):
            db = Database()

        create_client_mock.assert_called_once_with(
            hosts="http://localhost:8529",
            username="nomarr",
            password="secret",
            db_name="nomarr",
        )
        bind_mock.assert_called_once_with(fake_safe_db)
        assert db.db is fake_safe_db
        assert db.library_files is LibraryFiles
        assert db.meta.__name__ == "Meta"
        assert isinstance(db.library_files.path, _BoundFieldAccessor)
        assert db._registered == {}


class TestDatabaseRegister:
    """Direct unit tests for ``Database.register()``."""

    def _make_database(self) -> Database:
        """Construct a ``Database`` instance without connecting to ArangoDB."""
        db: Database = object.__new__(Database)
        db._registered = {}
        db.db = MagicMock()
        return db

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_register_success_stores_collection_class_and_sets_attribute(self) -> None:
        """``register()`` caches the dynamic subclass and exposes it as an attribute."""
        database = self._make_database()
        database.db.has_collection.return_value = True

        class FakeVectorTemplate(VectorCollection):
            NAME_PATTERN = "vectors_track_hot__{model}__{library}"

        with (
            patch.dict(
                "nomarr.persistence.db._VECTOR_TEMPLATE_CLASSES",
                {"vectors_track_hot": FakeVectorTemplate},
                clear=True,
            ),
            patch("nomarr.persistence.db.reattach_vector_cascades") as reattach_mock,
        ):
            result = database.register("vectors_track_hot__effnet__lib1", "vectors_track_hot")

        assert isinstance(result, type)
        assert issubclass(result, FakeVectorTemplate)
        assert result is not FakeVectorTemplate
        result_attrs = cast("dict[str, object]", result.__dict__)
        assert result_attrs["_name"] == "vectors_track_hot__effnet__lib1"
        assert database._registered["vectors_track_hot__effnet__lib1"] is result
        assert database.__dict__["vectors_track_hot__effnet__lib1"] is result
        reattach_mock.assert_called_once_with(["vectors_track_hot__effnet__lib1"])

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_register_idempotent_returns_cached_without_db_check(self) -> None:
        """Calling ``register()`` twice with the same name returns the cached class."""
        database = self._make_database()

        class CachedVectorTemplate(VectorCollection):
            pass

        database._registered["vectors_track_hot__effnet__lib1"] = CachedVectorTemplate

        result = database.register("vectors_track_hot__effnet__lib1", "vectors_track_hot")

        assert result is CachedVectorTemplate
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
    def test_register_raises_for_non_template_collection_name(self) -> None:
        """``register()`` raises ``ValueError`` when ``template_name`` is not a supported template."""
        database = self._make_database()
        database.db.has_collection.return_value = True

        with pytest.raises(ValueError, match="is not a supported template collection"):
            database.register("libraries__foo", "libraries")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_register_raises_for_unknown_template_name(self) -> None:
        """``register()`` raises ``ValueError`` when ``template_name`` is not present in the template registry."""
        database = self._make_database()
        database.db.has_collection.return_value = True

        with pytest.raises(ValueError, match="is not a supported template collection"):
            database.register("nonexistent__foo", "nonexistent_template")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_register_raises_when_vector_template_name_does_not_match_pattern(self) -> None:
        """``register()`` raises ``ValueError`` when a vector template name mismatches its ``NAME_PATTERN``."""
        database = self._make_database()
        database.db.has_collection.return_value = True

        class FakeVectorTemplate(VectorCollection):
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

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_register_second_call_passes_cumulative_names_to_reattach(self) -> None:
        """The second register() call reattaches cascades with all registered dynamic names so far."""
        database = self._make_database()
        database.db.has_collection.return_value = True

        class FakeHotVectorTemplate(VectorCollection):
            NAME_PATTERN = "vectors_track_hot__{model}__{library}"

        class FakeColdVectorTemplate(VectorCollection):
            NAME_PATTERN = "vectors_track_cold__{model}__{library}"

        with (
            patch.dict(
                "nomarr.persistence.db._VECTOR_TEMPLATE_CLASSES",
                {
                    "vectors_track_hot": FakeHotVectorTemplate,
                    "vectors_track_cold": FakeColdVectorTemplate,
                },
                clear=True,
            ),
            patch("nomarr.persistence.db.reattach_vector_cascades") as reattach_mock,
        ):
            database.register("vectors_track_hot__effnet__lib1", "vectors_track_hot")
            database.register("vectors_track_cold__effnet__lib1", "vectors_track_cold")

        assert reattach_mock.call_args_list[0].args == (["vectors_track_hot__effnet__lib1"],)
        assert reattach_mock.call_args_list[1].args == (
            ["vectors_track_hot__effnet__lib1", "vectors_track_cold__effnet__lib1"],
        )


class TestDatabaseGetVersion:
    """Direct unit tests for ``Database.get_version()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_version_returns_string_value_from_meta_doc(self) -> None:
        """``get_version()`` returns the stored version string when present."""
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
        """``get_version()`` returns ``None`` when meta storage returns a non-dict."""
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
        """``get_version()`` returns ``None`` when the stored value is not a string."""
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
        """``set_version()`` writes the schema version to ``meta`` via ``upsert()``."""
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
    def test_matches_name_pattern(
        self,
        resolved_name: str,
        name_pattern: str,
        expected: bool,
    ) -> None:
        """``_matches_name_pattern()`` compares static segments and placeholder segments correctly."""
        result = _matches_name_pattern(resolved_name, name_pattern)

        assert result is expected
