"""Enforcement tests for the normalized persistence public surface."""

from __future__ import annotations

import inspect
import re
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from nomarr.persistence import collections as persistence_collections
from nomarr.persistence.accessors import FieldAccessor
from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.collections_base import (
    DocumentCollection,
    EdgeCollection,
    StateGraphCollection,
    VectorCollection,
)
from nomarr.persistence.db import (
    _COLLECTION_FIRST_ROOTS,
    _STATIC_DOCUMENT_COLLECTIONS,
    _STATIC_EDGE_COLLECTIONS,
    Database,
)
from nomarr.persistence.query_specs import PUBLIC_NAMING_GRAMMAR

_RESERVED_PUBLIC_ROOT_NAMES = (
    frozenset(_COLLECTION_FIRST_ROOTS)
    | frozenset(
        root.value for root in (PUBLIC_NAMING_GRAMMAR.generic_roots | PUBLIC_NAMING_GRAMMAR.storage_native_roots)
    )
    | frozenset({"get_vector", "get_vectors_by_file_ids", "transition", "upsert_vector"})
)
_COLLECTION_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_ALLOWED_CONCRETE_PUBLIC_METHODS: dict[str, set[str]] = {
    "LibraryFiles": {"get_files_by_paths_bulk"},
}


def _make_db() -> SafeDatabase:
    return cast("SafeDatabase", MagicMock(spec=SafeDatabase))


def _make_database_shell() -> Database:
    facade = Database.__new__(Database)
    facade.db = _make_db()
    facade._document_collections = []
    facade._edge_collections = []
    facade._vector_collections = []
    facade._registered = {}
    return facade


def _instantiate_collection(
    collection_cls: type[DocumentCollection | EdgeCollection | VectorCollection],
) -> DocumentCollection | EdgeCollection | VectorCollection:
    if issubclass(collection_cls, VectorCollection):
        return collection_cls(_make_db(), "vectors_test")
    return collection_cls(_make_db())


def _concrete_collection_classes() -> list[type[DocumentCollection | EdgeCollection | VectorCollection]]:
    classes: list[type[DocumentCollection | EdgeCollection | VectorCollection]] = []
    for _, obj in inspect.getmembers(persistence_collections, inspect.isclass):
        if obj.__module__ != persistence_collections.__name__:
            continue
        if obj in {DocumentCollection, EdgeCollection, StateGraphCollection, VectorCollection}:
            continue
        if issubclass(obj, (DocumentCollection, EdgeCollection, VectorCollection)):
            classes.append(obj)
    return classes


@pytest.mark.unit
@pytest.mark.mocked
class TestDatabasePersistenceEnforcement:
    """Tests guarding the `Database` facade naming and binding surface."""

    def test_bound_public_instance_attributes_are_only_collection_names(self) -> None:
        """Static binding should only expose registry-declared collection attributes."""
        facade = _make_database_shell()

        facade._bind_static_collections()

        expected_names = {name for name, _ in _STATIC_DOCUMENT_COLLECTIONS} | {
            name for name, _ in _STATIC_EDGE_COLLECTIONS
        }
        bound_public_names = {name for name in vars(facade) if not name.startswith("_") and name != "db"}

        assert bound_public_names == expected_names
        assert all(_COLLECTION_NAME_PATTERN.fullmatch(name) for name in bound_public_names)
        assert bound_public_names.isdisjoint(_RESERVED_PUBLIC_ROOT_NAMES)

    def test_register_binds_runtime_vectors_by_collection_name(self) -> None:
        """Runtime registration should expose vectors under their concrete collection name only."""
        facade = _make_database_shell()
        facade.db = cast("SafeDatabase", MagicMock())
        cast("MagicMock", facade.db.has_collection).return_value = True

        with patch.object(facade, "_reattach_vector_cascades") as reattach_mock:
            instance = facade.register("vectors_track_hot__effnet__lib1", "vectors_track_hot")

        assert facade.vectors_track_hot__effnet__lib1 is instance
        assert facade._registered["vectors_track_hot__effnet__lib1"] is instance
        assert _COLLECTION_NAME_PATTERN.fullmatch("vectors_track_hot__effnet__lib1")
        assert "vectors_track_hot__effnet__lib1" not in _RESERVED_PUBLIC_ROOT_NAMES
        reattach_mock.assert_called_once_with()


@pytest.mark.unit
@pytest.mark.mocked
class TestCollectionNamingGrammarEnforcement:
    """Tests guarding concrete collection classes against bespoke helper creep."""

    def test_field_accessors_are_registered_and_never_use_reserved_public_roots(self) -> None:
        """Concrete collections may expose fields, but field names must not claim public helper roots."""
        for collection_cls in _concrete_collection_classes():
            instance = _instantiate_collection(collection_cls)
            field_names = {name for name, value in vars(instance).items() if isinstance(value, FieldAccessor)}

            assert field_names == set(instance._fields), collection_cls.__name__
            assert field_names.isdisjoint(_RESERVED_PUBLIC_ROOT_NAMES), collection_cls.__name__

    def test_concrete_collection_classes_define_no_bespoke_public_methods(self) -> None:
        """Concrete collections should stay declarative; helper logic belongs in shared base classes."""
        for collection_cls in _concrete_collection_classes():
            public_methods = {
                name
                for name, value in collection_cls.__dict__.items()
                if inspect.isfunction(value) and not name.startswith("_") and name != "__init__"
            }
            allowed_methods = _ALLOWED_CONCRETE_PUBLIC_METHODS.get(collection_cls.__name__, set())

            assert public_methods <= allowed_methods, (
                f"{collection_cls.__name__} defines extra public methods: {sorted(public_methods - allowed_methods)}"
            )


@pytest.mark.unit
@pytest.mark.mocked
class TestCollectionFirstSurfaceGuard:
    """Tests for ``Database._assert_collection_first_surface`` enforcement."""

    def test_raises_type_error_when_collection_missing_required_roots(self) -> None:
        """Binding a collection that lacks collection-first roots must raise TypeError."""

        class BrokenCollection(DocumentCollection):
            # Shadow 'get' with a property that raises AttributeError so hasattr() returns False.
            @property
            def get(self) -> None:  # type: ignore[override]
                raise AttributeError("deliberately absent")

        broken = BrokenCollection.__new__(BrokenCollection)
        broken._db = _make_db()
        broken._name = "broken_collection"

        with pytest.raises(TypeError, match="missing collection-first roots"):
            Database._assert_collection_first_surface("broken_collection", broken)

    def test_passes_silently_for_fully_conformant_collection(self) -> None:
        """Binding a fully conformant collection must not raise."""
        from nomarr.persistence.collections import LibraryFiles

        instance = LibraryFiles(_make_db())

        # No exception is expected.
        Database._assert_collection_first_surface("library_files", instance)


@pytest.mark.unit
@pytest.mark.mocked
class TestDatabaseRegisterErrorPaths:
    """Tests guarding the error paths of ``Database.register``."""

    def test_register_returns_cached_instance_without_re_registering(self) -> None:
        """Registering an already-registered collection returns the cached instance."""
        facade = _make_database_shell()
        cached = MagicMock()
        facade._registered["vectors_track_hot__effnet__lib1"] = cached

        result = facade.register("vectors_track_hot__effnet__lib1", "vectors_track_hot")

        assert result is cached

    def test_register_raises_value_error_when_collection_absent_in_arango(self) -> None:
        """register() must reject a collection that does not exist in ArangoDB."""
        facade = _make_database_shell()
        facade.db = cast("SafeDatabase", MagicMock())
        cast("MagicMock", facade.db.has_collection).return_value = False

        with pytest.raises(ValueError, match="does not exist in ArangoDB"):
            facade.register("vectors_track_hot__effnet__lib1", "vectors_track_hot")

    def test_register_raises_value_error_for_unknown_template_name(self) -> None:
        """register() must reject an unrecognised template_name."""
        facade = _make_database_shell()
        facade.db = cast("SafeDatabase", MagicMock())
        cast("MagicMock", facade.db.has_collection).return_value = True

        with pytest.raises(ValueError, match="is not a supported template collection"):
            facade.register("vectors_track_hot__effnet__lib1", "unknown_template")

    def test_register_raises_value_error_for_name_pattern_mismatch(self) -> None:
        """register() must reject a collection name that violates the template name pattern."""
        facade = _make_database_shell()
        facade.db = cast("SafeDatabase", MagicMock())
        cast("MagicMock", facade.db.has_collection).return_value = True

        with pytest.raises(ValueError, match="does not match template pattern"):
            facade.register("wrong_prefix__effnet__lib1", "vectors_track_hot")
