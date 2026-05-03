"""Tests that validate the constructor produces correct output from the real SCHEMA.

These tests are the primary correctness guarantee for the persistence constructor.
Since the entire API is generated at runtime from schema.py, we must verify that
SchemaConstructor.build() produces a namespace tree that:

1. Has the right verbs on every collection (matches capabilities)
2. Has the right fields with the right verb sets
3. Generates valid AQL for every verb invocation
4. Enforces constraints (unique → .get.one, non-unique → no .get.one)
5. Doesn't attach verbs that aren't declared
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from nomarr.helpers.filter_types import Op
from nomarr.persistence.constructor.builder import SchemaConstructor
from nomarr.persistence.constructor.namespaces import (
    CollectionGetNamespace,
    CollectionNamespace,
    FieldNamespace,
    GetModifierNamespace,
)
from nomarr.persistence.schema import SCHEMA, CapabilityError, CollectionType

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# TEMPLATE collections are intentionally excluded from build() — they are
# instantiated dynamically at runtime with concrete tier/backbone/library
# parameters. Tests must not expect them in the build output.
_BUILDABLE_SCHEMA = {name: spec for name, spec in SCHEMA.items() if spec.get("type") != CollectionType.TEMPLATE}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built_namespaces() -> dict[str, CollectionNamespace]:
    """Build all collection namespaces from the real SCHEMA once per module."""
    db = MagicMock()
    db.collection.return_value = MagicMock()

    constructor = SchemaConstructor(db)
    return constructor.build()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Verbs that are wired as collection-level attributes
_COLLECTION_VERBS = {"insert", "delete", "cascade", "count", "transition", "traversal", "ann_search"}

# Verbs that are wired as field-level attributes
_FIELD_VERBS = {"get", "count", "collect", "aggregate", "update", "upsert", "delete"}


def _expected_collection_verbs(spec: dict[str, Any]) -> set[str]:
    """Derive the set of collection-level verbs that should be attached."""
    declared = set(spec.get("capabilities", []))
    return declared & _COLLECTION_VERBS


def _expected_field_verbs(field_spec: dict[str, Any]) -> set[str]:
    """Derive the set of field-level verbs that should be attached."""
    declared = set(field_spec.get("capabilities", []))
    return declared & _FIELD_VERBS


# Dummy arguments for invoking each capability-gated verb. The capability
# check happens before any real work, so these placeholder values never
# reach a backend; they only need to satisfy the method signature so Python
# can dispatch into the body where ``_require_capability`` raises.
_COLLECTION_VERB_ARGS: dict[str, tuple[Any, ...]] = {
    "insert": ([{"x": 1}],),
    "delete": (["col/1"],),
    "cascade": (["col/1"],),
    "count": (),
    "transition": (["col/1"], "from/1", "to/1"),
    "traversal": ("col/1", "edge"),
    "ann_search": ([0.0], 1, 1),
}

_FIELD_VERB_ARGS: dict[str, tuple[Any, ...]] = {
    "count": ("v",),
    "collect": (),
    "aggregate": (),
    "update": ("v", {"x": 1}),
    "upsert": ([{"x": 1}], "_key"),
    "delete": ("v",),
}


# ---------------------------------------------------------------------------
# Test: Every collection is built
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.mocked
class TestAllCollectionsBuilt:
    """Verify that build() produces a namespace for every SCHEMA entry."""

    def test_every_buildable_collection_has_namespace(
        self,
        built_namespaces: dict[str, CollectionNamespace],
    ) -> None:
        missing = set(_BUILDABLE_SCHEMA.keys()) - set(built_namespaces.keys())
        assert missing == set(), f"Collections missing from build output: {missing}"

    def test_no_extra_namespaces(
        self,
        built_namespaces: dict[str, CollectionNamespace],
    ) -> None:
        extra = set(built_namespaces.keys()) - set(_BUILDABLE_SCHEMA.keys())
        assert extra == set(), f"Extra namespaces not in SCHEMA: {extra}"

    def test_template_collections_excluded_from_build(
        self,
        built_namespaces: dict[str, CollectionNamespace],
    ) -> None:
        """TEMPLATE collections must NOT appear in build() output."""
        templates = {name for name, spec in SCHEMA.items() if spec.get("type") == CollectionType.TEMPLATE}
        present = templates & set(built_namespaces.keys())
        assert present == set(), f"TEMPLATE collections in build output: {present}"

    def test_all_are_collection_namespaces(
        self,
        built_namespaces: dict[str, CollectionNamespace],
    ) -> None:
        for name, ns in built_namespaces.items():
            assert isinstance(ns, CollectionNamespace), f"{name}: expected CollectionNamespace, got {type(ns).__name__}"


# ---------------------------------------------------------------------------
# Test: Collection-level verb presence matches capabilities
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.mocked
class TestCollectionVerbPresence:
    """Verify each collection has exactly the verbs its capabilities declare."""

    @pytest.mark.parametrize(
        "col_name",
        list(_BUILDABLE_SCHEMA.keys()),
        ids=list(_BUILDABLE_SCHEMA.keys()),
    )
    def test_declared_verbs_present(
        self,
        col_name: str,
        built_namespaces: dict[str, CollectionNamespace],
    ) -> None:
        """Every declared capability verb must be a callable on the namespace."""
        ns = built_namespaces[col_name]
        expected = _expected_collection_verbs(_BUILDABLE_SCHEMA[col_name])

        for verb in expected:
            assert hasattr(ns, verb), f"{col_name}: missing verb '{verb}' (declared in capabilities)"
            assert callable(getattr(ns, verb)), f"{col_name}.{verb} exists but is not callable"

    @pytest.mark.parametrize(
        "col_name",
        list(_BUILDABLE_SCHEMA.keys()),
        ids=list(_BUILDABLE_SCHEMA.keys()),
    )
    def test_undeclared_verbs_absent(
        self,
        col_name: str,
        built_namespaces: dict[str, CollectionNamespace],
    ) -> None:
        """Verbs NOT in capabilities must raise CapabilityError when invoked."""
        ns = built_namespaces[col_name]
        expected = _expected_collection_verbs(_BUILDABLE_SCHEMA[col_name])
        absent = _COLLECTION_VERBS - expected

        for verb in absent:
            method = getattr(ns, verb)
            with pytest.raises(CapabilityError):
                method(*_COLLECTION_VERB_ARGS[verb])

    @pytest.mark.parametrize(
        "col_name",
        list(_BUILDABLE_SCHEMA.keys()),
        ids=list(_BUILDABLE_SCHEMA.keys()),
    )
    def test_get_always_present(
        self,
        col_name: str,
        built_namespaces: dict[str, CollectionNamespace],
    ) -> None:
        """Every collection MUST have a .get namespace (always wired)."""
        ns = built_namespaces[col_name]
        assert hasattr(ns, "get")
        assert isinstance(ns.get, CollectionGetNamespace)


# ---------------------------------------------------------------------------
# Test: Field namespace presence and verb wiring
# ---------------------------------------------------------------------------


def _field_params() -> list[tuple[str, str, dict[str, Any]]]:
    """Generate (col_name, field_name, field_spec) tuples for parametrization."""
    return [
        (col_name, field_name, field_spec)
        for col_name, spec in _BUILDABLE_SCHEMA.items()
        for field_name, field_spec in spec.get("fields", {}).items()
    ]


def _field_ids() -> list[str]:
    """Generate readable test IDs for field parametrization."""
    return [
        f"{col_name}.{field_name}"
        for col_name, spec in _BUILDABLE_SCHEMA.items()
        for field_name in spec.get("fields", {})
    ]


@pytest.mark.unit
@pytest.mark.mocked
class TestFieldNamespacePresence:
    """Verify field namespaces are built for every field in SCHEMA."""

    @pytest.mark.parametrize(
        ("col_name", "field_name", "field_spec"),
        _field_params(),
        ids=_field_ids(),
    )
    def test_field_namespace_exists(
        self,
        col_name: str,
        field_name: str,
        field_spec: dict[str, Any],
        built_namespaces: dict[str, CollectionNamespace],
    ) -> None:
        ns = built_namespaces[col_name]
        assert hasattr(ns, field_name), f"{col_name}: missing field namespace for '{field_name}'"
        assert isinstance(getattr(ns, field_name), FieldNamespace), (
            f"{col_name}.{field_name}: expected FieldNamespace, got {type(getattr(ns, field_name)).__name__}"
        )


@pytest.mark.unit
@pytest.mark.mocked
class TestFieldVerbPresence:
    """Verify each field namespace has exactly the verbs its spec declares."""

    @pytest.mark.parametrize(
        ("col_name", "field_name", "field_spec"),
        _field_params(),
        ids=_field_ids(),
    )
    def test_declared_field_verbs_present(
        self,
        col_name: str,
        field_name: str,
        field_spec: dict[str, Any],
        built_namespaces: dict[str, CollectionNamespace],
    ) -> None:
        """Every declared field capability must be a callable on the FieldNamespace."""
        field_ns = getattr(built_namespaces[col_name], field_name)
        expected = _expected_field_verbs(field_spec)

        for verb in expected:
            if verb == "get":
                # get is a GetModifierNamespace, not a plain callable
                assert isinstance(field_ns.get, GetModifierNamespace), (
                    f"{col_name}.{field_name}.get: expected GetModifierNamespace"
                )
            else:
                assert hasattr(field_ns, verb), f"{col_name}.{field_name}: missing verb '{verb}'"
                assert callable(getattr(field_ns, verb)), f"{col_name}.{field_name}.{verb} exists but is not callable"

    @pytest.mark.parametrize(
        ("col_name", "field_name", "field_spec"),
        _field_params(),
        ids=_field_ids(),
    )
    def test_undeclared_field_verbs_absent(
        self,
        col_name: str,
        field_name: str,
        field_spec: dict[str, Any],
        built_namespaces: dict[str, CollectionNamespace],
    ) -> None:
        """Verbs NOT in field capabilities must raise CapabilityError when invoked."""
        field_ns = getattr(built_namespaces[col_name], field_name)
        expected = _expected_field_verbs(field_spec)
        absent = _FIELD_VERBS - expected

        for verb in absent:
            if verb == "get":
                # `get` is always a GetModifierNamespace; calling it raises
                # CapabilityError when the capability is not declared.
                with pytest.raises(CapabilityError):
                    field_ns.get("v")
                continue
            method = getattr(field_ns, verb)
            with pytest.raises(CapabilityError):
                method(*_FIELD_VERB_ARGS[verb])


# ---------------------------------------------------------------------------
# Test: Unique field constraint (.get.one only on unique fields)
# ---------------------------------------------------------------------------


def _get_capable_fields() -> list[tuple[str, str, dict[str, Any]]]:
    """Get all fields with 'get' capability for uniqueness tests."""
    return [
        (col_name, field_name, field_spec)
        for col_name, spec in _BUILDABLE_SCHEMA.items()
        for field_name, field_spec in spec.get("fields", {}).items()
        if "get" in field_spec.get("capabilities", [])
    ]


def _get_capable_ids() -> list[str]:
    return [
        f"{col_name}.{field_name}"
        for col_name, spec in _BUILDABLE_SCHEMA.items()
        for field_name, field_spec in spec.get("fields", {}).items()
        if "get" in field_spec.get("capabilities", [])
    ]


@pytest.mark.unit
@pytest.mark.mocked
class TestGetModifierUniqueness:
    """Verify .get.one is present only on unique fields, .many/.in_/.like on all."""

    @pytest.mark.parametrize(
        ("col_name", "field_name", "field_spec"),
        _get_capable_fields(),
        ids=_get_capable_ids(),
    )
    def test_unique_field_has_one(
        self,
        col_name: str,
        field_name: str,
        field_spec: dict[str, Any],
        built_namespaces: dict[str, CollectionNamespace],
    ) -> None:
        """Unique fields MUST expose .get.one."""
        if not field_spec.get("unique", False):
            pytest.skip("Not a unique field")

        get_ns = getattr(built_namespaces[col_name], field_name).get
        # Use __getattr__ path since .one is gated
        assert callable(get_ns.one)

    @pytest.mark.parametrize(
        ("col_name", "field_name", "field_spec"),
        _get_capable_fields(),
        ids=_get_capable_ids(),
    )
    def test_non_unique_field_no_one(
        self,
        col_name: str,
        field_name: str,
        field_spec: dict[str, Any],
        built_namespaces: dict[str, CollectionNamespace],
    ) -> None:
        """Non-unique fields must raise CapabilityError when .one is invoked."""
        if field_spec.get("unique", False):
            pytest.skip("Unique field")

        get_ns = getattr(built_namespaces[col_name], field_name).get
        with pytest.raises(CapabilityError):
            get_ns.one("v")

    @pytest.mark.parametrize(
        ("col_name", "field_name", "field_spec"),
        _get_capable_fields(),
        ids=_get_capable_ids(),
    )
    def test_all_get_fields_have_many(
        self,
        col_name: str,
        field_name: str,
        field_spec: dict[str, Any],
        built_namespaces: dict[str, CollectionNamespace],
    ) -> None:
        """Every get-capable field MUST have .get.many."""
        get_ns = getattr(built_namespaces[col_name], field_name).get
        assert callable(get_ns.many)

    @pytest.mark.parametrize(
        ("col_name", "field_name", "field_spec"),
        _get_capable_fields(),
        ids=_get_capable_ids(),
    )
    def test_all_get_fields_have_in(
        self,
        col_name: str,
        field_name: str,
        field_spec: dict[str, Any],
        built_namespaces: dict[str, CollectionNamespace],
    ) -> None:
        """Every get-capable field MUST have .get.in (aliased from .in_)."""
        get_ns = getattr(built_namespaces[col_name], field_name).get
        in_method = getattr(get_ns, "in")
        assert callable(in_method)

    @pytest.mark.parametrize(
        ("col_name", "field_name", "field_spec"),
        _get_capable_fields(),
        ids=_get_capable_ids(),
    )
    def test_all_get_fields_have_like(
        self,
        col_name: str,
        field_name: str,
        field_spec: dict[str, Any],
        built_namespaces: dict[str, CollectionNamespace],
    ) -> None:
        """Get-capable fields expose .get.like only when collection operators allow it."""
        get_ns = getattr(built_namespaces[col_name], field_name).get
        collection_spec = _BUILDABLE_SCHEMA[col_name]
        get_ops = cast("list[str] | None", collection_spec.get("operators", {}).get("get"))

        if get_ops is None or "like" in get_ops:
            assert callable(get_ns.like)
            return

        with pytest.raises(CapabilityError):
            get_ns.like("%v%")


# ---------------------------------------------------------------------------
# Test: AQL generation validity for every verb path
# ---------------------------------------------------------------------------


def _mock_db_for_aql() -> MagicMock:
    """Create a mock db that captures AQL calls."""
    db = MagicMock()
    db.aql.execute.return_value = iter([])
    col = MagicMock()
    col.get.return_value = None
    col.insert.return_value = {"_id": "test/1", "_key": "1", "new": {"_id": "test/1"}}
    col.insert_many.return_value = [{"_id": "test/1", "_key": "1", "new": {"_id": "test/1"}}]
    db.collection.return_value = col
    return db


@pytest.mark.unit
@pytest.mark.mocked
class TestAQLGeneration:
    """Verify that verb invocations produce valid AQL with bind variables."""

    def _build_all(self, db: MagicMock) -> dict[str, CollectionNamespace]:
        constructor = SchemaConstructor(db)
        return constructor.build()

    def test_get_many_by_field_generates_parameterized_aql(self) -> None:
        """get.many must use bind_vars, not string interpolation."""
        db = _mock_db_for_aql()
        namespaces = self._build_all(db)

        # Pick first field with get capability from any collection
        for col_name, spec in _BUILDABLE_SCHEMA.items():
            for field_name, field_spec in spec.get("fields", {}).items():
                if "get" in field_spec.get("capabilities", []):
                    field_ns = getattr(namespaces[col_name], field_name)
                    field_ns.get.many("test_value")

                    call_args = db.aql.execute.call_args
                    aql = call_args[0][0]
                    bind_vars = call_args[1]["bind_vars"]

                    # Must be parameterized
                    assert "@col" in bind_vars
                    assert "val" in bind_vars
                    # Must NOT interpolate values into AQL string
                    assert "test_value" not in aql
                    return

        pytest.fail("No get-capable fields found in SCHEMA")

    def test_get_in_list_generates_in_operator(self) -> None:
        """get.in with a list must generate AQL IN operator."""
        db = _mock_db_for_aql()
        namespaces = self._build_all(db)

        for col_name, spec in _BUILDABLE_SCHEMA.items():
            for field_name, field_spec in spec.get("fields", {}).items():
                if "get" in field_spec.get("capabilities", []):
                    field_ns = getattr(namespaces[col_name], field_name)
                    field_ns.get.in_(["a", "b", "c"])

                    aql = db.aql.execute.call_args[0][0]
                    assert "IN" in aql
                    return

        pytest.fail("No get-capable fields found")

    def test_get_in_filter_dict_generates_comparison(self) -> None:
        """get.in with a FilterDict must generate comparison operators."""
        db = _mock_db_for_aql()
        namespaces = self._build_all(db)

        for col_name, spec in _BUILDABLE_SCHEMA.items():
            for field_name, field_spec in spec.get("fields", {}).items():
                if "get" in field_spec.get("capabilities", []):
                    field_ns = getattr(namespaces[col_name], field_name)
                    field_ns.get.in_({Op.GT: 5, Op.LT: 100})

                    aql = db.aql.execute.call_args[0][0]
                    bind_vars = db.aql.execute.call_args[1]["bind_vars"]

                    assert ">" in aql or "doc." in aql
                    assert "@col" in bind_vars
                    return

        pytest.fail("No get-capable fields found")

    def test_get_like_generates_like_operator(self) -> None:
        """get.like must generate AQL LIKE operator."""
        db = _mock_db_for_aql()
        namespaces = self._build_all(db)

        for col_name, spec in _BUILDABLE_SCHEMA.items():
            for field_name, field_spec in spec.get("fields", {}).items():
                if "get" in field_spec.get("capabilities", []):
                    field_ns = getattr(namespaces[col_name], field_name)
                    field_ns.get.like("%test%")

                    aql = db.aql.execute.call_args[0][0]
                    assert "LIKE" in aql
                    return

        pytest.fail("No get-capable fields found")

    def test_count_by_field_generates_count(self) -> None:
        """Field-level count must generate COUNT/COLLECT AQL."""
        db = _mock_db_for_aql()
        db.aql.execute.return_value = iter([0])
        namespaces = self._build_all(db)

        for col_name, spec in _BUILDABLE_SCHEMA.items():
            for field_name, field_spec in spec.get("fields", {}).items():
                if "count" in field_spec.get("capabilities", []):
                    field_ns = getattr(namespaces[col_name], field_name)
                    field_ns.count("test_value")

                    aql = db.aql.execute.call_args[0][0]
                    assert "COUNT" in aql or "LENGTH" in aql
                    return

        pytest.fail("No count-capable fields found")

    def test_collect_field_generates_distinct(self) -> None:
        """Field-level collect must generate COLLECT/RETURN DISTINCT AQL."""
        db = _mock_db_for_aql()
        namespaces = self._build_all(db)

        for col_name, spec in _BUILDABLE_SCHEMA.items():
            for field_name, field_spec in spec.get("fields", {}).items():
                if "collect" in field_spec.get("capabilities", []):
                    field_ns = getattr(namespaces[col_name], field_name)
                    field_ns.collect()

                    aql = db.aql.execute.call_args[0][0]
                    assert "COLLECT" in aql or "RETURN DISTINCT" in aql
                    return

        pytest.fail("No collect-capable fields found")

    def test_aggregate_field_generates_count_grouping(self) -> None:
        """Field-level aggregate must generate grouped COUNT AQL."""
        db = _mock_db_for_aql()
        namespaces = self._build_all(db)

        for col_name, spec in _BUILDABLE_SCHEMA.items():
            for field_name, field_spec in spec.get("fields", {}).items():
                if "aggregate" in field_spec.get("capabilities", []):
                    field_ns = getattr(namespaces[col_name], field_name)
                    field_ns.aggregate()

                    aql = db.aql.execute.call_args[0][0]
                    assert "COLLECT" in aql
                    assert "COUNT" in aql or "WITH COUNT" in aql
                    return

        pytest.fail("No aggregate-capable fields found")

    def test_update_by_field_generates_update_aql(self) -> None:
        """Field-level update must generate UPDATE AQL."""
        db = _mock_db_for_aql()
        namespaces = self._build_all(db)

        for col_name, spec in _BUILDABLE_SCHEMA.items():
            for field_name, field_spec in spec.get("fields", {}).items():
                if "update" in field_spec.get("capabilities", []):
                    field_ns = getattr(namespaces[col_name], field_name)
                    field_ns.update("match_val", {"status": "new"})

                    aql = db.aql.execute.call_args[0][0]
                    assert "UPDATE" in aql
                    return

        pytest.fail("No update-capable fields found")

    def test_upsert_by_field_generates_upsert_aql(self) -> None:
        """Field-level upsert must generate UPSERT AQL."""
        db = _mock_db_for_aql()
        # upsert_by_field calls next(cursor) expecting the _id back
        db.aql.execute.return_value = iter(["test/1"])
        namespaces = self._build_all(db)

        for col_name, spec in _BUILDABLE_SCHEMA.items():
            for field_name, field_spec in spec.get("fields", {}).items():
                if "upsert" in field_spec.get("capabilities", []):
                    db.aql.execute.return_value = iter(["test/1"])
                    field_ns = getattr(namespaces[col_name], field_name)
                    field_ns.upsert([{field_name: "val", "extra": "data"}], field_name)

                    aql = db.aql.execute.call_args[0][0]
                    assert "UPSERT" in aql
                    return

        pytest.fail("No upsert-capable fields found")

    def test_delete_by_field_generates_remove_aql(self) -> None:
        """Field-level delete must generate REMOVE AQL."""
        db = _mock_db_for_aql()
        db.aql.execute.return_value = iter([0])
        namespaces = self._build_all(db)

        for col_name, spec in _BUILDABLE_SCHEMA.items():
            for field_name, field_spec in spec.get("fields", {}).items():
                if "delete" in field_spec.get("capabilities", []):
                    field_ns = getattr(namespaces[col_name], field_name)
                    field_ns.delete("val_to_delete")

                    aql = db.aql.execute.call_args[0][0]
                    assert "REMOVE" in aql
                    return

        pytest.fail("No delete-capable fields found")

    def test_all_aql_uses_bind_vars_not_interpolation(self) -> None:
        """Exhaustively check that NO AQL query contains raw values.

        Iterates every get-capable field and calls .many() with a sentinel
        string. If the sentinel appears in the AQL text, we have injection risk.
        """
        sentinel = "SENTINEL_XSS_PROBE_12345"
        db = _mock_db_for_aql()
        namespaces = self._build_all(db)

        violations = []
        for col_name, spec in _BUILDABLE_SCHEMA.items():
            for field_name, field_spec in spec.get("fields", {}).items():
                if "get" not in field_spec.get("capabilities", []):
                    continue

                db.aql.execute.reset_mock()
                db.aql.execute.return_value = iter([])

                field_ns = getattr(namespaces[col_name], field_name)
                field_ns.get.many(sentinel)

                if db.aql.execute.called:
                    aql = db.aql.execute.call_args[0][0]
                    if sentinel in aql:
                        violations.append(f"{col_name}.{field_name}.get.many")

        assert violations == [], f"AQL injection risk — sentinel found in raw AQL for: {violations}"


# ---------------------------------------------------------------------------
# Test: Collection-level verbs execute without error
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.mocked
class TestCollectionLevelVerbsCallable:
    """Walk every collection-level verb and invoke it to catch construction bugs."""

    def test_insert_callable_on_capable_collections(self) -> None:
        """insert() should not raise TypeError on invocation."""
        db = _mock_db_for_aql()
        namespaces = self._build_all_namespaces(db)

        for col_name, spec in _BUILDABLE_SCHEMA.items():
            if "insert" in spec.get("capabilities", []):
                ns = namespaces[col_name]
                ns.insert([{"test": "doc"}])

    def test_delete_callable_on_capable_collections(self) -> None:
        """delete() should not raise TypeError on invocation."""
        db = _mock_db_for_aql()
        namespaces = self._build_all_namespaces(db)

        for col_name, spec in _BUILDABLE_SCHEMA.items():
            if "delete" in spec.get("capabilities", []):
                ns = namespaces[col_name]
                ns.delete([f"{col_name}/1"])

    def test_count_callable_on_capable_collections(self) -> None:
        """count() should not raise TypeError on invocation."""
        db = _mock_db_for_aql()
        db.aql.execute.return_value = iter([0])
        namespaces = self._build_all_namespaces(db)

        for col_name, spec in _BUILDABLE_SCHEMA.items():
            if "count" in spec.get("capabilities", []):
                db.aql.execute.return_value = iter([0])
                ns = namespaces[col_name]
                ns.count()

    def _build_all_namespaces(self, db: MagicMock) -> dict[str, CollectionNamespace]:
        constructor = SchemaConstructor(db)
        return constructor.build()


# ---------------------------------------------------------------------------
# Test: Schema coverage statistics
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.mocked
class TestSchemaCoverage:
    """Verify SCHEMA coverage expectations from the DD."""

    def test_schema_has_minimum_collection_count(self) -> None:
        """SCHEMA must declare at least 30 collections (DD says 37)."""
        assert len(SCHEMA) >= 30, f"SCHEMA has only {len(SCHEMA)} collections, expected ≥30"

    def test_buildable_schema_excludes_templates(self) -> None:
        """_BUILDABLE_SCHEMA should have fewer entries than SCHEMA."""
        assert len(_BUILDABLE_SCHEMA) < len(SCHEMA)
        assert len(_BUILDABLE_SCHEMA) >= 29  # 37 - templates

    def test_every_collection_has_type(self) -> None:
        for col_name, spec in SCHEMA.items():
            assert "type" in spec, f"{col_name}: missing 'type'"
            assert spec["type"] in CollectionType.__members__.values(), f"{col_name}: invalid type '{spec['type']}'"

    def test_every_collection_has_capabilities(self) -> None:
        for col_name, spec in SCHEMA.items():
            assert "capabilities" in spec, f"{col_name}: missing 'capabilities'"
            assert isinstance(spec["capabilities"], list), f"{col_name}: capabilities must be a list"

    def test_every_buildable_collection_has_fields(self) -> None:
        for col_name, spec in _BUILDABLE_SCHEMA.items():
            assert "fields" in spec, f"{col_name}: missing 'fields'"
            assert isinstance(spec["fields"], dict), f"{col_name}: fields must be a dict"

    def test_template_collections_have_fields(self) -> None:
        """TEMPLATE collections use flat top-level fields after the template split."""
        for col_name, spec in SCHEMA.items():
            if spec["type"] == CollectionType.TEMPLATE:
                assert "fields" in spec, f"{col_name}: TEMPLATE missing 'fields'"
                assert isinstance(spec["fields"], dict), f"{col_name}: TEMPLATE fields must be a dict"

    def test_every_field_has_capabilities(self) -> None:
        for col_name, spec in _BUILDABLE_SCHEMA.items():
            for field_name, field_spec in spec.get("fields", {}).items():
                assert "capabilities" in field_spec, f"{col_name}.{field_name}: missing 'capabilities'"

    def test_state_graph_collections_have_edge_collection(self) -> None:
        """STATE_GRAPH collections MUST declare edge_collection."""
        for col_name, spec in SCHEMA.items():
            if spec["type"] == CollectionType.STATE_GRAPH:
                assert "edge_collection" in spec, f"{col_name}: STATE_GRAPH missing 'edge_collection'"

    def test_template_collections_have_name_pattern(self) -> None:
        """TEMPLATE collections MUST declare name_pattern."""
        for col_name, spec in SCHEMA.items():
            if spec["type"] == CollectionType.TEMPLATE:
                assert "name_pattern" in spec, f"{col_name}: TEMPLATE missing 'name_pattern'"

    def test_cascade_targets_are_valid_edges(self) -> None:
        """Cascade targets must reference EDGE/STATE_GRAPH edge collections in SCHEMA."""
        for col_name, spec in SCHEMA.items():
            if "cascade" not in spec:
                continue
            for target in spec["cascade"]:
                assert target in SCHEMA, f"{col_name}: cascade target '{target}' not in SCHEMA"
                target_type = SCHEMA[target]["type"]
                assert target_type == CollectionType.EDGE, (
                    f"{col_name}: cascade target '{target}' is {target_type}, not EDGE"
                )


# ---------------------------------------------------------------------------
# Test: Template collection capability split (hot vs cold)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.mocked
class TestTemplateCapabilitySplit:
    """Verify the hot/cold template capability differences declared in SCHEMA."""

    def _get_template_caps(self, template_name: str) -> set[str]:
        from nomarr.persistence.schema import SCHEMA

        return set(SCHEMA[template_name].get("capabilities", []))

    def test_vectors_track_hot_lacks_ann_search(self) -> None:
        """vectors_track_hot must NOT declare ann_search (search is cold-only)."""
        caps = self._get_template_caps("vectors_track_hot")
        assert "ann_search" not in caps

    def test_vectors_track_cold_has_ann_search(self) -> None:
        """vectors_track_cold MUST declare ann_search."""
        caps = self._get_template_caps("vectors_track_cold")
        assert "ann_search" in caps

    def test_vectors_track_hot_lacks_upsert(self) -> None:
        """vectors_track_hot must NOT declare upsert (writes go through insert only)."""
        caps = self._get_template_caps("vectors_track_hot")
        assert "upsert" not in caps

    def test_vectors_track_cold_has_upsert(self) -> None:
        """vectors_track_cold MUST declare upsert (cold allows idempotent writes)."""
        caps = self._get_template_caps("vectors_track_cold")
        assert "upsert" in caps

    def test_vectors_track_hot_lacks_update_many(self) -> None:
        """vectors_track_hot must NOT declare update_many."""
        caps = self._get_template_caps("vectors_track_hot")
        assert "update_many" not in caps

    def test_vectors_track_cold_has_update_many(self) -> None:
        """vectors_track_cold MUST declare update_many (used by backfill_genres)."""
        caps = self._get_template_caps("vectors_track_cold")
        assert "update_many" in caps
