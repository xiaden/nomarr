"""Unit tests for map_persistence_exceptions() exception translation.

Tests the sync context manager in ``nomarr.persistence.sql.exceptions``
that translates SQLAlchemy exceptions into domain exceptions using
PostgreSQL error codes (pgcodes).

Uses ``unittest.mock.Mock`` to create fake SQLAlchemy exceptions with
specific pgcode values, since SQLite doesn't have PostgreSQL error codes.
"""

from __future__ import annotations

import logging
from unittest.mock import Mock

import pytest
from sqlalchemy.exc import IntegrityError, NoResultFound, OperationalError

from nomarr.helpers.exceptions import (
    DatabaseStateError,
    DuplicateEntityError,
    EntityNotFoundError,
    ReferentialIntegrityError,
)
from nomarr.persistence.sql.exceptions import map_persistence_exceptions


def test_no_result_found_maps_to_entity_not_found():
    """NoResultFound is translated to EntityNotFoundError."""
    with pytest.raises(EntityNotFoundError, match="Entity not found"), map_persistence_exceptions():
        raise NoResultFound("no rows")


def test_integrity_error_unique_violation_maps_to_duplicate_entity():
    """IntegrityError with pgcode 23505 (unique_violation) maps to DuplicateEntityError."""
    exc = IntegrityError("duplicate", params=None, orig=Mock())
    exc.orig.pgcode = "23505"
    with pytest.raises(DuplicateEntityError, match="Duplicate entity"), map_persistence_exceptions():
        raise exc


def test_integrity_error_fk_violation_maps_to_referential_integrity():
    """IntegrityError with pgcode 23503 (foreign_key_violation) maps to ReferentialIntegrityError."""
    exc = IntegrityError("fk violation", params=None, orig=Mock())
    exc.orig.pgcode = "23503"
    with (
        pytest.raises(ReferentialIntegrityError, match="Referential integrity violation"),
        map_persistence_exceptions(),
    ):
        raise exc


def test_operational_error_maps_to_database_state_error():
    """OperationalError is translated to DatabaseStateError."""
    exc = OperationalError("connection lost", params=None, orig=Mock())
    with pytest.raises(DatabaseStateError, match="Database operational error"), map_persistence_exceptions():
        raise exc


def test_integrity_error_unknown_pgcode_maps_to_database_state_error(caplog):
    """IntegrityError with unrecognized pgcode maps to DatabaseStateError and logs a warning."""
    exc = IntegrityError("unknown", params=None, orig=Mock())
    exc.orig.pgcode = "99999"
    with (
        caplog.at_level(logging.WARNING, logger="nomarr.persistence.sql.exceptions"),
        pytest.raises(DatabaseStateError, match="Database error"),
        map_persistence_exceptions(),
    ):
        raise exc
    assert any("unexpected pgcode" in record.message for record in caplog.records)


def test_integrity_error_no_pgcode_maps_to_database_state_error():
    """IntegrityError where orig has no pgcode attribute maps to DatabaseStateError."""
    orig = Mock(spec=[])  # spec=[] ensures no attributes exist on the mock
    exc = IntegrityError("no pgcode", params=None, orig=orig)
    with pytest.raises(DatabaseStateError, match="Database error"), map_persistence_exceptions():
        raise exc


def test_integrity_error_null_orig_maps_to_database_state_error():
    """IntegrityError with orig=None maps to DatabaseStateError."""
    exc = IntegrityError("null orig", params=None, orig=None)
    with pytest.raises(DatabaseStateError, match="Database error"), map_persistence_exceptions():
        raise exc
