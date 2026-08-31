"""Tests for nomarr.components.library.reconciliation_comp module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.reconciliation_comp import (
    claim_files_for_reconciliation,
    count_files_needing_reconciliation,
    release_claim,
    set_file_written,
)
from nomarr.helpers.constants.file_states import (
    STATE_NOT_WRITTEN,
    STATE_TAGS_CURRENT,
    STATE_TAGS_NOT_FRESH,
    STATE_WRITTEN,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.helpers.dataclasses.worker_claim_dataclass import WorkerClaim, WorkerClaimIdentity
from nomarr.helpers.time_helper import Milliseconds


def _song(**overrides: object) -> Song:
    base: dict = {
        "song_id": 1,
        "library_id": 1,
        "folder_id": None,
        "path": "/music/song.mp3",
        "normalized_path": "song.mp3",
        "file_size": 100,
        "modified_time": 1000,
        "duration_seconds": None,
        "chromaprint": None,
        "needs_tagging": False,
        "is_valid": True,
        "tagged": False,
        "calibration_hash": None,
        "write_claimed_by": None,
        "last_tagged_at": None,
        "scanned_at": None,
        "created_at": 1000,
    }
    base.update(overrides)
    return Song(**base)


def _library() -> Library:
    """Construct a domain ``Library`` scoping reconciliation claims/counts."""
    return Library(name="Test Library", root_path="/music")


def _identity(song_id: int) -> SongIdentity:
    """Construct a natural song identity for a numeric song handle."""
    return SongIdentity(
        library=LibraryIdentity(name="Test Library"),
        normalized_path=f"song-{song_id}.mp3",
    )


def _reconcile_claim(song_id: int, worker_id: str, claimed_at_ms: int) -> WorkerClaim:
    return WorkerClaim(
        identity=WorkerClaimIdentity(song=_identity(song_id), worker_id=worker_id, claim_type="reconcile"),
        claimed_at_ms=claimed_at_ms,
    )


class TestClaimFilesForReconciliation:
    """Tests for claim_files_for_reconciliation."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_list_when_no_stale_files(self) -> None:
        mock_db = MagicMock()

        with patch(
            "nomarr.components.library.reconciliation_comp.get_stale_song_ids",
            return_value=[],
        ):
            result = claim_files_for_reconciliation(mock_db, _library(), "workers/test")

        assert result == []
        mock_db.library.get_song.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_claims_available_file_successfully(self) -> None:
        mock_db = MagicMock()
        candidate = _song(song_id=123)
        mock_db.library.get_song.return_value = candidate
        mock_db.library.resolve_song_identity.return_value = _identity(123)
        mock_db.app.add_claim.return_value = True

        with (
            patch(
                "nomarr.components.library.reconciliation_comp.get_stale_song_ids",
                return_value=[123],
            ),
            patch.object(mock_db.app, "song_ids_with_state", return_value=[]),
            patch(
                "nomarr.components.library.reconciliation_comp.now_ms",
                return_value=Milliseconds(10_000),
            ),
        ):
            result = claim_files_for_reconciliation(mock_db, _library(), "workers/test")

            assert result == [candidate]
        mock_db.library.get_song.assert_called_once_with(123)
        mock_db.app.add_claim.assert_called_once_with(
            _reconcile_claim(123, "workers/test", 10_000),
            lease_ms=60_000,
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_claims_pending_tag_write_when_tags_are_fresh(self) -> None:
        mock_db = MagicMock()
        candidate = _song(song_id=123)
        mock_db.library.list_songs.return_value = [candidate]
        mock_db.library.get_song.return_value = candidate
        mock_db.library.resolve_song_identity.return_value = _identity(123)
        mock_db.app.add_claim.return_value = True

        with (
            patch("nomarr.components.library.reconciliation_comp.get_stale_song_ids", return_value=[]),
            patch.object(mock_db.app, "song_ids_with_state", return_value=[123]),
            patch("nomarr.components.library.reconciliation_comp.now_ms", return_value=Milliseconds(10_000)),
        ):
            result = claim_files_for_reconciliation(mock_db, _library(), "workers/test")

            assert result == [candidate]
        mock_db.app.add_claim.assert_called_once_with(
            _reconcile_claim(123, "workers/test", 10_000),
            lease_ms=60_000,
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_respects_batch_size_limit(self) -> None:
        mock_db = MagicMock()
        stale_ids = [100, 101, 102, 103, 104]
        candidates = [_song(song_id=file_id) for file_id in stale_ids]
        mock_db.library.get_song.side_effect = candidates
        mock_db.library.resolve_song_identity.side_effect = [_identity(sid) for sid in stale_ids]
        mock_db.app.add_claim.return_value = True

        with (
            patch(
                "nomarr.components.library.reconciliation_comp.get_stale_song_ids",
                return_value=stale_ids,
            ),
            patch.object(mock_db.app, "song_ids_with_state", return_value=[]),
            patch(
                "nomarr.components.library.reconciliation_comp.now_ms",
                return_value=Milliseconds(20_000),
            ),
        ):
            result = claim_files_for_reconciliation(
                mock_db,
                _library(),
                "workers/test",
                batch_size=2,
            )

        assert result == candidates[:2]
        assert mock_db.library.get_song.call_count == 2
        assert mock_db.app.add_claim.call_count == 2
        expected = {_reconcile_claim(sid, "workers/test", 20_000) for sid in (100, 101)}
        for call in mock_db.app.add_claim.call_args_list:
            assert call.kwargs == {"lease_ms": 60_000}
            assert call.args[0] in expected

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_skips_already_claimed_active_file(self) -> None:
        mock_db = MagicMock()
        candidate = _song(song_id=123)
        mock_db.library.get_song.return_value = candidate
        mock_db.library.resolve_song_identity.return_value = _identity(123)
        mock_db.app.add_claim.return_value = False

        with (
            patch(
                "nomarr.components.library.reconciliation_comp.get_stale_song_ids",
                return_value=[123],
            ),
            patch(
                "nomarr.components.library.reconciliation_comp.now_ms",
                return_value=Milliseconds(60_000),
            ),
        ):
            result = claim_files_for_reconciliation(
                mock_db,
                _library(),
                "workers/test",
                lease_ms=60_000,
            )

        assert result == []
        mock_db.library.get_song.assert_called_once_with(123)
        mock_db.app.add_claim.assert_called_once_with(
            _reconcile_claim(123, "workers/test", 60_000),
            lease_ms=60_000,
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_reclaims_expired_lease(self) -> None:
        mock_db = MagicMock()
        candidate = _song(song_id=123)
        mock_db.library.get_song.return_value = candidate
        mock_db.library.resolve_song_identity.return_value = _identity(123)
        mock_db.app.add_claim.return_value = True

        with (
            patch(
                "nomarr.components.library.reconciliation_comp.get_stale_song_ids",
                return_value=[123],
            ),
            patch(
                "nomarr.components.library.reconciliation_comp.now_ms",
                return_value=Milliseconds(120_000),
            ),
        ):
            result = claim_files_for_reconciliation(
                mock_db,
                _library(),
                "workers/test",
                lease_ms=60_000,
            )

            assert result == [candidate]
        mock_db.app.add_claim.assert_called_once_with(
            _reconcile_claim(123, "workers/test", 120_000),
            lease_ms=60_000,
        )


class TestSetFileWritten:
    """Tests for set_file_written."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_normalizes_bare_key_to_full_id(self) -> None:
        mock_db = MagicMock()
        mock_db.library.resolve_song_identity.return_value = _identity(123)
        mock_db.app.song_state_membership.return_value = {STATE_TAGS_NOT_FRESH}
        with patch("nomarr.components.library.reconciliation_comp.transition_song_state") as mock_transition:
            set_file_written(mock_db, 123, "worker:reconcile:0")

        first_transition = mock_transition.call_args_list[0].args
        assert first_transition == (
            mock_db,
            [123],
            STATE_NOT_WRITTEN,
            STATE_WRITTEN,
        )
        mock_db.app.remove_claim.assert_called_once_with(
            WorkerClaimIdentity(song=_identity(123), worker_id="worker:reconcile:0", claim_type="reconcile")
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_normalizes_full_id_unchanged(self) -> None:
        mock_db = MagicMock()
        mock_db.library.resolve_song_identity.return_value = _identity(123)

        with patch("nomarr.components.library.reconciliation_comp.transition_song_state") as mock_transition:
            set_file_written(mock_db, 123, "worker:reconcile:0")

        for transition_call in mock_transition.call_args_list:
            assert transition_call.args[1] == [123]
        mock_db.app.remove_claim.assert_called_once_with(
            WorkerClaimIdentity(song=_identity(123), worker_id="worker:reconcile:0", claim_type="reconcile")
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_transitions_tag_state_edges(self) -> None:
        mock_db = MagicMock()
        mock_db.library.resolve_song_identity.return_value = _identity(123)
        mock_db.app.song_state_membership.return_value = {STATE_TAGS_NOT_FRESH}

        with patch("nomarr.components.library.reconciliation_comp.transition_song_state") as mock_transition:
            set_file_written(mock_db, 123, "worker:reconcile:0")

        assert mock_transition.call_count == 2
        first_transition = mock_transition.call_args_list[0].args
        second_transition = mock_transition.call_args_list[1].args
        assert first_transition == (
            mock_db,
            [123],
            STATE_NOT_WRITTEN,
            STATE_WRITTEN,
        )
        assert second_transition == (
            mock_db,
            [123],
            STATE_TAGS_NOT_FRESH,
            STATE_TAGS_CURRENT,
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_releases_claim_via_app_api(self) -> None:
        mock_db = MagicMock()
        mock_db.library.resolve_song_identity.return_value = _identity(123)

        with patch("nomarr.components.library.reconciliation_comp.transition_song_state"):
            set_file_written(mock_db, 123, "worker:reconcile:0")

        mock_db.app.remove_claim.assert_called_once_with(
            WorkerClaimIdentity(song=_identity(123), worker_id="worker:reconcile:0", claim_type="reconcile")
        )


class TestReleaseClaim:
    """Tests for release_claim."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_normalizes_bare_key_and_releases_claim_via_app_api(self) -> None:
        mock_db = MagicMock()
        mock_db.library.resolve_song_identity.return_value = _identity(123)

        release_claim(mock_db, 123, "worker:reconcile:0")

        mock_db.app.remove_claim.assert_called_once_with(
            WorkerClaimIdentity(song=_identity(123), worker_id="worker:reconcile:0", claim_type="reconcile")
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_does_not_change_state_edges(self) -> None:
        mock_db = MagicMock()
        mock_db.library.resolve_song_identity.return_value = _identity(123)

        release_claim(mock_db, 123, "worker:reconcile:0")

        mock_db.file_states.transition.assert_not_called()


class TestCountFilesNeedingReconciliation:
    """Tests for count_files_needing_reconciliation."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_count_of_stale_file_ids(self) -> None:
        mock_db = MagicMock()

        with (
            patch(
                "nomarr.components.library.reconciliation_comp.get_stale_song_ids",
                return_value=[
                    100,
                    101,
                    102,
                ],
            ),
            patch.object(mock_db.app, "song_ids_with_state", return_value=[]),
        ):
            result = count_files_needing_reconciliation(mock_db, _library())

        assert result == 3

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_when_no_stale_files(self) -> None:
        mock_db = MagicMock()

        with (
            patch(
                "nomarr.components.library.reconciliation_comp.get_stale_song_ids",
                return_value=[],
            ),
            patch.object(mock_db.app, "song_ids_with_state", return_value=[]),
        ):
            result = count_files_needing_reconciliation(mock_db, _library())

        assert result == 0

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_counts_pending_tag_writes_when_tags_are_fresh(self) -> None:
        mock_db = MagicMock()
        mock_db.library.list_songs.return_value = [_song(song_id=100), _song(song_id=200)]

        with (
            patch("nomarr.components.library.reconciliation_comp.get_stale_song_ids", return_value=[]),
            patch.object(mock_db.app, "song_ids_with_state", return_value=[100]),
        ):
            result = count_files_needing_reconciliation(mock_db, _library())

        assert result == 1
