"""Tests for nomarr.components.library.reconciliation_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from arango.exceptions import DocumentInsertError

from nomarr.components.library.reconciliation_comp import (
    claim_files_for_reconciliation,
    count_files_needing_reconciliation,
    release_claim,
    set_file_written,
)
from nomarr.helpers.constants.file_states import (
    STATE_TAGS_CURRENT,
    STATE_TAGS_NOT_WRITTEN,
    STATE_TAGS_STALE,
    STATE_TAGS_WRITTEN,
)
from nomarr.helpers.time_helper import Milliseconds


def _document_insert_error() -> DocumentInsertError:
    """Create a lightweight DocumentInsertError instance for unit tests."""
    return DocumentInsertError.__new__(DocumentInsertError)


class TestClaimFilesForReconciliation:
    """Tests for claim_files_for_reconciliation."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_list_when_no_stale_files(self) -> None:
        mock_db = MagicMock()

        with patch(
            "nomarr.components.library.reconciliation_comp.get_stale_file_ids",
            return_value=[],
        ):
            result = claim_files_for_reconciliation(mock_db, "libraries/test", "workers/test")

        assert result == []
        mock_db.library_files.get.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_claims_available_file_successfully(self) -> None:
        mock_db = MagicMock()
        candidate = {"_id": "library_files/abc", "_key": "abc"}
        mock_db.library_files.get.return_value = candidate

        with (
            patch(
                "nomarr.components.library.reconciliation_comp.get_stale_file_ids",
                return_value=["library_files/abc"],
            ),
            patch(
                "nomarr.components.library.reconciliation_comp.now_ms",
                return_value=Milliseconds(10_000),
            ),
        ):
            result = claim_files_for_reconciliation(mock_db, "libraries/test", "workers/test")

        assert result == [candidate]
        inserted_payload = mock_db.worker_claims.insert.call_args.args[0][0]
        assert inserted_payload["_key"] == "claim_reconcile_abc"
        assert inserted_payload["file_id"] == "library_files/abc"
        assert inserted_payload["worker_id"] == "workers/test"
        assert inserted_payload["claimed_at"] == 10_000
        assert inserted_payload["claim_type"] == "reconcile"

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_respects_batch_size_limit(self) -> None:
        mock_db = MagicMock()
        stale_ids = [f"library_files/{index}" for index in range(5)]
        candidates = [{"_id": stale_id, "_key": str(index)} for index, stale_id in enumerate(stale_ids)]
        mock_db.library_files.get.side_effect = candidates

        with (
            patch(
                "nomarr.components.library.reconciliation_comp.get_stale_file_ids",
                return_value=stale_ids,
            ),
            patch(
                "nomarr.components.library.reconciliation_comp.now_ms",
                return_value=Milliseconds(20_000),
            ),
        ):
            result = claim_files_for_reconciliation(
                mock_db,
                "libraries/test",
                "workers/test",
                batch_size=2,
            )

        assert result == candidates[:2]
        assert mock_db.worker_claims.insert.call_count == 2

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_skips_already_claimed_active_file(self) -> None:
        mock_db = MagicMock()
        candidate = {"_id": "library_files/abc", "_key": "abc"}
        mock_db.library_files.get.return_value = candidate
        mock_db.worker_claims.insert.side_effect = _document_insert_error()
        mock_db.worker_claims.get.return_value = {
            "_id": "worker_claims/existing",
            "claimed_at": 59_000,
        }

        with (
            patch(
                "nomarr.components.library.reconciliation_comp.get_stale_file_ids",
                return_value=["library_files/abc"],
            ),
            patch(
                "nomarr.components.library.reconciliation_comp.now_ms",
                return_value=Milliseconds(60_000),
            ),
        ):
            result = claim_files_for_reconciliation(
                mock_db,
                "libraries/test",
                "workers/test",
                lease_ms=60_000,
            )

        assert result == []
        mock_db.worker_claims.delete.assert_not_called()
        assert mock_db.worker_claims.insert.call_count == 1

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_reclaims_expired_lease(self) -> None:
        mock_db = MagicMock()
        candidate = {"_id": "library_files/abc", "_key": "abc"}
        mock_db.library_files.get.return_value = candidate
        mock_db.worker_claims.insert.side_effect = [_document_insert_error(), None]
        mock_db.worker_claims.get.return_value = {
            "_id": "worker_claims/existing",
            "claimed_at": 0,
        }

        with (
            patch(
                "nomarr.components.library.reconciliation_comp.get_stale_file_ids",
                return_value=["library_files/abc"],
            ),
            patch(
                "nomarr.components.library.reconciliation_comp.now_ms",
                return_value=Milliseconds(120_000),
            ),
        ):
            result = claim_files_for_reconciliation(
                mock_db,
                "libraries/test",
                "workers/test",
                lease_ms=60_000,
            )

        assert result == [candidate]
        mock_db.worker_claims.delete.assert_called_once_with(_id="worker_claims/existing")
        assert mock_db.worker_claims.insert.call_count == 2


class TestSetFileWritten:
    """Tests for set_file_written."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_normalizes_bare_key_to_full_id(self) -> None:
        mock_db = MagicMock()

        set_file_written(mock_db, "abc123")

        first_transition = mock_db.file_states.transition.call_args_list[0].args
        assert first_transition[0] == ["library_files/abc123"]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_normalizes_full_id_unchanged(self) -> None:
        mock_db = MagicMock()

        set_file_written(mock_db, "library_files/abc123")

        for transition_call in mock_db.file_states.transition.call_args_list:
            assert transition_call.args[0] == ["library_files/abc123"]
        mock_db.worker_claims.delete.assert_called_once_with(file_id="library_files/abc123")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_transitions_tag_state_edges(self) -> None:
        mock_db = MagicMock()

        set_file_written(mock_db, "abc")

        assert mock_db.file_states.transition.call_count == 2
        first_transition = mock_db.file_states.transition.call_args_list[0].args
        second_transition = mock_db.file_states.transition.call_args_list[1].args
        assert first_transition == (["library_files/abc"], STATE_TAGS_NOT_WRITTEN, STATE_TAGS_WRITTEN)
        assert second_transition == (["library_files/abc"], STATE_TAGS_STALE, STATE_TAGS_CURRENT)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_deletes_worker_claim(self) -> None:
        mock_db = MagicMock()

        set_file_written(mock_db, "abc")

        mock_db.worker_claims.delete.assert_called_once_with(file_id="library_files/abc")


class TestReleaseClaim:
    """Tests for release_claim."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_normalizes_bare_key_and_deletes_claim(self) -> None:
        mock_db = MagicMock()

        release_claim(mock_db, "abc")

        mock_db.worker_claims.delete.assert_called_once_with(file_id="library_files/abc")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_does_not_change_state_edges(self) -> None:
        mock_db = MagicMock()

        release_claim(mock_db, "abc")

        mock_db.file_states.transition.assert_not_called()


class TestCountFilesNeedingReconciliation:
    """Tests for count_files_needing_reconciliation."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_count_of_stale_file_ids(self) -> None:
        mock_db = MagicMock()

        with patch(
            "nomarr.components.library.reconciliation_comp.get_stale_file_ids",
            return_value=["library_files/a", "library_files/b", "library_files/c"],
        ):
            result = count_files_needing_reconciliation(mock_db, "libraries/test")

        assert result == 3

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_when_no_stale_files(self) -> None:
        mock_db = MagicMock()

        with patch(
            "nomarr.components.library.reconciliation_comp.get_stale_file_ids",
            return_value=[],
        ):
            result = count_files_needing_reconciliation(mock_db, "libraries/test")

        assert result == 0
