"""Focused tests for ``AppAqlOperations`` primitive delegation contracts."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.persistence.database.app_aql import AppAqlOperations

pytestmark = [pytest.mark.unit, pytest.mark.mocked]


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def ops(mock_db: MagicMock) -> AppAqlOperations:
    return AppAqlOperations(mock_db)


@pytest.mark.parametrize(
    (
        "method_name",
        "args",
        "expected_collection",
        "expected_field_name",
        "expected_field_value",
        "expected_allowed_fields",
        "expected_result",
    ),
    [
        (
            "release_lock",
            ("resource-123",),
            AppAqlOperations.LOCK_COLLECTION,
            "document_reference",
            "resource-123",
            AppAqlOperations.LOCK_FIELDS,
            None,
        ),
        (
            "release_claim",
            ("file-123",),
            AppAqlOperations.WORKER_CLAIM_COLLECTION,
            "file_id",
            "library_files/file-123",
            AppAqlOperations.WORKER_CLAIM_FIELDS,
            None,
        ),
        (
            "delete_meta",
            ("schema-version",),
            AppAqlOperations.META_COLLECTION,
            "key",
            "schema-version",
            AppAqlOperations.META_FIELDS,
            None,
        ),
        (
            "delete_pipeline_state",
            ("libraries/lib123",),
            AppAqlOperations.PIPELINE_STATE_COLLECTION,
            "library_key",
            "lib123",
            AppAqlOperations.PIPELINE_STATE_FIELDS,
            7,
        ),
        (
            "delete_scan_records_for_library",
            ("lib123",),
            AppAqlOperations.SCAN_COLLECTION,
            "library_key",
            "lib123",
            AppAqlOperations.SCAN_FIELDS,
            7,
        ),
        (
            "delete_session",
            ("session-123",),
            AppAqlOperations.SESSION_COLLECTION,
            "session_id",
            "session-123",
            AppAqlOperations.SESSION_FIELDS,
            None,
        ),
    ],
)
def test_refactored_delete_callers_delegate_to_delete_many_by_field(
    mock_db: MagicMock,
    ops: AppAqlOperations,
    method_name: str,
    args: tuple[str],
    expected_collection: str,
    expected_field_name: str,
    expected_field_value: str,
    expected_allowed_fields: frozenset[str],
    expected_result: int | None,
) -> None:
    with (
        patch("nomarr.persistence.database.app_aql.primitives.delete_many_by_field", return_value=7) as delete_many,
        patch("nomarr.persistence.database.app_aql.primitives.get_many_by_field") as get_many,
        patch("nomarr.persistence.database.app_aql.primitives.delete_many_by_keys") as delete_keys,
    ):
        result = getattr(ops, method_name)(*args)

    delete_many.assert_called_once_with(
        mock_db,
        expected_collection,
        expected_field_name,
        expected_field_value,
        allowed_fields=expected_allowed_fields,
    )
    get_many.assert_not_called()
    delete_keys.assert_not_called()
    mock_db.aql.execute.assert_not_called()
    assert result == expected_result
