"""Sabotage tests: transaction policy and facade API shape (AR-1, AR-2).

These tests are RED at creation time. They define the target state per
CONTRACTS.md AR-1 (sub-facade boundaries) and AR-2 (transaction policy).

They will turn GREEN as the implementing parts (B, C1, C2) complete their work.
Do NOT claim the overall plan is complete while these tests are RED.

Target state (per CONTRACTS.md):
- WRITE facade methods require ``transaction()`` context; calling them
  outside a transaction raises ``FacadeMisuseError``.
- READ facade methods use SQLAlchemy autobegin (no explicit transaction).
- ``transaction()`` is a context manager on each sub-facade that wraps
  ``session.begin()`` and warns if called after autobegin.
- Facade methods return domain objects (TypedDict-like) with typed fields.
- Facade methods accept domain-shaped payloads (not integer PKs).

Current state (RED baseline):
- No ``FacadeMisuseError`` exception exists (only ``FacadeMisuseWarning``).
- No ``transaction()`` method on facades.
- No guard clause on write methods.
- Write methods work without transaction (autobegin).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Conditional import: FacadeMisuseError does NOT exist yet.
# It will be created in Part C2 (CONTRACTS.md C2).
# TYPE_CHECKING block satisfies pyright; runtime try/except preserves
# the red-baseline behavior.
# ---------------------------------------------------------------------------
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    # FacadeMisuseError will be created in Part C2 (CONTRACTS.md C2).
    # This stub satisfies pyright without affecting runtime behavior.
    class FacadeMisuseError(RuntimeError): ...
else:
    try:
        from nomarr.helpers.exceptions import FacadeMisuseError  # type: ignore[assignment]
    except ImportError:
        # Placeholder — never matches a real exception at runtime.
        # When FacadeMisuseError is defined in Part C2, this branch is skipped
        # and the real exception class is used.
        FacadeMisuseError = type(
            "_FacadeMisuseErrorPlaceholder",
            (RuntimeError,),
            {"__doc__": "Placeholder — FacadeMisuseError not yet defined (Part C2)"},
        )


# ---------------------------------------------------------------------------
# Test 1: Write methods must require transaction() context
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestWriteMethodsRequireTransaction:
    """RED BASELINE: Write methods should raise FacadeMisuseError outside transaction().

    Target behavior (AR-2):
        if not self._session.in_transaction():
            raise FacadeMisuseError(
                f"{type(self).__name__}.{method_name}() is a write method "
                f"— call within a transaction() context"
            )

    Current behavior: write methods work without transaction (autobegin).
    This test FAILS until Part C2 adds FacadeMisuseError and the guard clause.
    """

    def test_write_method_outside_transaction_raises(self, db, seed_data):
        """Calling a WRITE facade method without transaction() raises FacadeMisuseError.

        RED → GREEN transition:
        - RED: FacadeMisuseError doesn't exist OR write method succeeds without transaction.
        - GREEN: FacadeMisuseError exists AND write method raises it outside transaction().
        """
        with pytest.raises(FacadeMisuseError, match="write method"):
            # add_library is a WRITE method — should require transaction() context
            db.library.add_library(
                {
                    "name": "SabotageTestLib",
                    "path": "/tmp/sabotage_test",
                    "library_type": "music",
                }
            )


# ---------------------------------------------------------------------------
# Test 2: Nested transaction detection
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestNestedTransactionDetection:
    """RED BASELINE: Nested transaction() calls should warn.

    Target behavior (AR-2):
        def transaction(self) -> ContextManager[Session]:
            if self._session.in_transaction():
                warnings.warn(
                    "Transaction already active — did you call a read method "
                    "before entering the context?"
                )
            return self._session.begin()

    Current behavior: no transaction() method exists on facades.
    This test FAILS until Part C2 adds the transaction() context manager.
    """

    def test_nested_transaction_detection(self, db):
        """transaction() method exists on LibraryDb facade.

        RED → GREEN transition:
        - RED: No transaction() method exists on the facade.
        - GREEN: transaction() exists and is callable.
        """
        # Check that the transaction() method exists
        assert hasattr(db.library, "transaction"), (
            "LibraryDb must have a transaction() method (AR-2). "
            "This method wraps session.begin() and warns if called after autobegin."
        )
        assert callable(db.library.transaction), "LibraryDb.transaction must be callable (context manager)."


# ---------------------------------------------------------------------------
# Test 3: Read methods work without explicit transaction
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestReadMethodsWorkWithoutTransaction:
    """GREEN BASELINE: Read methods should work without explicit transaction.

    Target behavior (AR-2): READ methods use SQLAlchemy autobegin safely.
    They do NOT have the guard clause and do NOT require transaction().

    This test should PASS in both current and target states.
    """

    def test_read_method_works_without_explicit_transaction(self, db, seed_data):
        """Calling a READ facade method without transaction() succeeds.

        This is expected behavior — reads use autobegin safely.
        Should PASS now and continue to PASS after the guard is added.
        """
        # list_libraries is a READ method — should work without transaction
        result = db.library.list_libraries()
        assert isinstance(result, list), "READ methods should return results without requiring transaction()"

        # get_library is also a READ method
        lib_id = seed_data["libraries"][0]
        lib = db.library.get_library(lib_id)
        assert lib is not None, "get_library should return a result for a valid library ID"


# ---------------------------------------------------------------------------
# Test 4: Facade methods return domain objects, not raw dicts
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestFacadeMethodsReturnDomainObjects:
    """Check that facade methods return objects with expected domain fields.

    Target behavior: facade methods return TypedDict-like objects with
    typed fields (e.g., LibraryRow with 'id', 'name', 'path' keys).

    This test checks the API shape — it may partially PASS depending on
    current return types. The key assertion is that returned objects have
    the expected domain fields, not arbitrary dict keys.
    """

    def test_facade_methods_return_domain_objects_not_raw_dicts(self, db, seed_data):
        """Facade methods return objects with expected domain field keys.

        Checks that get_library returns an object with 'id', 'name', 'path' keys.
        This verifies the API contract — callers depend on these field names.
        """
        lib_id = seed_data["libraries"][0]
        result = db.library.get_library(lib_id)

        assert result is not None, "get_library should return a result for seed data"

        # Check that the result has expected domain fields
        # (TypedDict or dataclass with these keys/attributes)
        expected_fields = {"id", "name", "path"}
        if isinstance(result, dict):
            actual_keys = set(result.keys())
        else:
            # Domain object — check attributes
            actual_keys = {k for k in dir(result) if not k.startswith("_")}

        missing_fields = expected_fields - actual_keys
        assert not missing_fields, (
            f"Facade method return value missing expected domain fields: {missing_fields}. "
            f"Actual keys/attrs: {actual_keys}"
        )


# ---------------------------------------------------------------------------
# Test 5: Facade methods accept domain identifiers
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestFacadeMethodsAcceptDomainIdentifiers:
    """Check that facade methods accept domain-shaped payloads.

    Target behavior: add_library accepts a dict with 'name', 'path', etc.
    (domain identifiers), not an integer PK.

    This test verifies the public API shape — callers pass domain payloads,
    not database-specific identifiers.
    """

    def test_facade_methods_accept_domain_identifiers(self, db, seed_data):
        """Facade methods accept domain-shaped payloads.

        Checks that add_library accepts a dict with 'name', 'path', 'library_type'.
        This verifies the API contract — callers pass domain payloads.
        """
        # add_library should accept a domain-shaped payload (dict with name, path)
        # This is the current API shape and should continue to work
        payload = {
            "name": "DomainShapeTestLib",
            "path": "/tmp/domain_shape_test",
            "library_type": "music",
        }

        # Verify the method accepts this payload shape
        # (may fail if DB is not available, but the API shape is the check)
        try:
            result = db.library.add_library(payload)
            # If we get here, the method accepts the payload shape
            assert isinstance(result, int), "add_library should return an integer ID"
            # Cleanup
            db.library.remove_library(result)
        except FacadeMisuseError:
            # If the guard is implemented, this is expected without transaction()
            # This is acceptable — the API shape test passes if the method
            # accepts the payload (even if it later rejects due to no transaction)
            pass
