"""Sabotage tests: transaction policy and facade API shape (AR-1, AR-2).

Shipped state (per CONTRACTS.md AR-2 / AR-SDR-4):
- WRITE facade methods succeed WITHOUT a ``transaction()`` context; the
  ``transaction()`` context manager and the ``_require_transaction`` guard
  have been removed from all facades (``LibraryDb``, ``AppDb``, ``MlDb`` and
  their sub-facades). Callers may invoke write methods directly.
- READ facade methods use SQLAlchemy autobegin (no explicit transaction).
- ``FacadeMisuseError`` is no longer part of the shipped API and must not be
  importable from ``nomarr.helpers.exceptions``.
- Facade methods return domain objects (TypedDict-like) with typed fields and
  accept domain-shaped payloads (not integer PKs).
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Test 1: FacadeMisuseError is no longer importable
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestFacadeMisuseErrorRemoved:
    """Shipped state: FacadeMisuseError no longer exists.

    Per CONTRACTS.md AR-SDR-4 the transaction contract (and the
    ``FacadeMisuseError`` raised by its guard) is removed. Importing it from
    ``nomarr.helpers.exceptions`` must raise ImportError.
    """

    def test_facade_misuse_error_not_importable(self):
        """Importing FacadeMisuseError from nomarr.helpers.exceptions raises ImportError."""
        with pytest.raises(ImportError):
            from nomarr.helpers.exceptions import FacadeMisuseError  # noqa: F401


# ---------------------------------------------------------------------------
# Test 2: Write methods succeed without transaction context
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestWriteMethodsWorkWithoutTransaction:
    """Shipped state: WRITE methods succeed without transaction().

    Per CONTRACTS.md AR-2 / AR-SDR-4, write facade methods no longer require a
    ``transaction()`` context. Calling them directly must succeed.
    """

    @pytest.mark.requires_database
    def test_write_method_succeeds_without_transaction(self, db, seed_data):
        """Calling a WRITE facade method without transaction() succeeds."""
        result = db.library.add_library(
            {
                "name": "SabotageTestLib",
                "path": "/tmp/sabotage_test",
                "library_type": "music",
            }
        )
        assert isinstance(result, int), "add_library should return an integer ID"
        db.library.remove_library(result)


# ---------------------------------------------------------------------------
# Test 3: Facades expose no transaction() or _require_transaction
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestNoTransactionContract:
    """Shipped state: transaction() and _require_transaction are removed.

    Per CONTRACTS.md AR-SDR-4, ``transaction()`` and ``_require_transaction``
    have been removed from every facade. Facades must not expose them.
    """

    @pytest.mark.requires_database
    def test_facades_do_not_expose_transaction(self, db):
        """LibraryDb, AppDb, and MlDb must not expose a transaction() method."""
        for facade in (db.library, db.app, db.ml):
            assert not hasattr(facade, "transaction"), (
                f"{type(facade).__name__} must not have a transaction() method (AR-SDR-4)."
            )
            assert not hasattr(facade, "_require_transaction"), (
                f"{type(facade).__name__} must not have a _require_transaction guard (AR-SDR-4)."
            )

    @pytest.mark.requires_database
    def test_sub_facades_do_not_expose_transaction(self, db):
        """Sub-facades (songs, tags, scans, regions) must not expose transaction()."""
        for sub in (db.library.songs, db.library.tags, db.library.scans, db.library.regions):
            assert not hasattr(sub, "transaction"), (
                f"{type(sub).__name__} must not have a transaction() method (AR-SDR-4)."
            )


# ---------------------------------------------------------------------------
# Test 4: Read methods work without explicit transaction
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestReadMethodsWorkWithoutTransaction:
    """Shipped state: read methods work without an explicit transaction.

    Per AR-2, READ methods use SQLAlchemy autobegin safely. They do NOT have
    the guard clause and do NOT require ``transaction()``.
    """

    @pytest.mark.requires_database
    def test_read_method_works_without_explicit_transaction(self, db, seed_data):
        """Calling a READ facade method without transaction() succeeds."""
        # list_libraries is a READ method — should work without transaction
        result = db.library.list_libraries()
        assert isinstance(result, list), "READ methods should return results without requiring transaction()"

        # get_library is also a READ method
        lib_id = seed_data["libraries"][0]
        lib = db.library.get_library(lib_id)
        assert lib is not None, "get_library should return a result for a valid library ID"


# ---------------------------------------------------------------------------
# Test 5: Facade methods return domain objects, not raw dicts
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestFacadeMethodsReturnDomainObjects:
    """Check that facade methods return objects with expected domain fields.

    Facade methods return TypedDict-like objects with typed fields
    (e.g., LibraryRow with 'id', 'name', 'path' keys). The key assertion
    is that returned objects have the expected domain fields, not arbitrary
    dict keys.
    """

    @pytest.mark.requires_database
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
# Test 7: AppDb exposes no legacy claim method / transaction surface (Phase 3)
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestAppDbHasNoLegacyClaimSurface:
    """AppDb (and AppMaintenanceDb) expose no legacy claim method or txn surface.

    The canonical claims intent surface is add_claim / remove_claim /
    remove_claims / list_claims / count_claims plus the all-claims reset under
    maintenance.delete_all_worker_claims. No legacy insert/release/steal/truncate
    name, no compatibility alias, and no transaction() guard may resurface
    (CONTRACTS.md / TASK-worker-claims-intent-facade-A-correction Phase 3).
    """

    def test_app_db_exposes_no_legacy_claim_method(self) -> None:
        from nomarr.persistence.api.application import AppDb

        for name in (
            "insert_worker_claim",
            "claim_file",
            "release_claim",
            "release_claim_by_song",
            "delete_claims_for_workers",
            "delete_claims_for_songs",
            "delete_claims",
            "steal_claim",
            "aggregate_worker_claims",
            "count_worker_claims",
            "truncate_worker_claims",
            "claim_song",
            "try_insert_or_steal_claim",
            "remove_claim_by_song",
        ):
            assert not hasattr(AppDb, name), f"AppDb must not expose a '{name}' claim method (CONTRACTS.md)."
        assert not hasattr(AppDb, "transaction"), "AppDb must not expose a transaction() method."
        assert not hasattr(AppDb, "_require_transaction"), "AppDb must not expose _require_transaction."

    def test_app_db_has_no_top_level_all_claims_delete(self) -> None:
        from nomarr.persistence.api.application import AppDb

        assert not hasattr(AppDb, "delete_all_worker_claims"), (
            "delete_all_worker_claims must live only under db.app.maintenance."
        )

    def test_maintenance_db_exposes_only_delete_all_worker_claims(self) -> None:
        from nomarr.persistence.api.application import AppMaintenanceDb

        claim_names = {name for name in dir(AppMaintenanceDb) if "claim" in name.lower()}
        assert claim_names == {"delete_all_worker_claims"}, (
            f"AppMaintenanceDb must expose only delete_all_worker_claims, got: {sorted(claim_names)}"
        )


# ---------------------------------------------------------------------------
# Test 6: Facade methods accept domain identifiers
# ---------------------------------------------------------------------------


@pytest.mark.sabotage_check
class TestFacadeMethodsAcceptDomainIdentifiers:
    """Check that facade methods accept domain-shaped payloads.

    Target behavior: add_library accepts a dict with 'name', 'path', etc.
    (domain identifiers), not an integer PK.

    This test verifies the public API shape — callers pass domain payloads,
    not database-specific identifiers.
    """

    @pytest.mark.requires_database
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

        # Verify the method accepts this payload shape and returns an integer ID
        result = db.library.add_library(payload)
        assert isinstance(result, int), "add_library should return an integer ID"
        # Cleanup
        db.library.remove_library(result)
