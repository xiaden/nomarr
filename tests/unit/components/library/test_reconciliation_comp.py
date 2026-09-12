"""Tests for ``nomarr.components.library.reconciliation_comp``.

Reconciliation claims and counts are exercised entirely through the typed
locator boundary: ``db.library.list_songs_with_state(...) -> list[SongStateCandidate]``
and ``db.app.add_claim`` / ``db.app.remove_claim`` / ``db.app.song_state_membership``.
No test pins a generated id, a raw row/dict ``Song``, or a resolver.
"""

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
from nomarr.helpers.dataclasses.song_state_candidate_dataclass import SongStateCandidate
from nomarr.helpers.dataclasses.worker_claim_dataclass import WorkerClaim, WorkerClaimIdentity
from nomarr.helpers.time_helper import Milliseconds

LIBRARY_UUID = "691ebf37-b1e4-5244-a9c0-4758c39eaab6"


def _library() -> Library:
    """Construct a persisted domain ``Library`` scoping reconciliation claims/counts."""
    return Library(name="Test Library", root_path="/music", library_uuid=LIBRARY_UUID)


def _lib_identity() -> LibraryIdentity:
    library = _library()
    return LibraryIdentity(library.library_uuid, library.name, library.root_path)


def _song(normalized_path: str = "song.mp3") -> Song:
    return Song(
        path=f"/music/{normalized_path}",
        normalized_path=normalized_path,
        file_size=100,
        modified_time=1000,
        duration_seconds=None,
        chromaprint=None,
        needs_tagging=False,
        is_valid=True,
        tagged=False,
        calibration_hash=None,
        write_claimed_by=None,
        last_tagged_at=None,
        scanned_at=None,
        created_at=1000,
    )


def _identity(normalized_path: str) -> SongIdentity:
    return SongIdentity(library=_lib_identity(), normalized_path=normalized_path)


def _candidate(normalized_path: str, states: tuple[str, ...] = ("tags_not_fresh",)) -> SongStateCandidate:
    song = _song(normalized_path)
    return SongStateCandidate(
        identity=SongIdentity(library=_lib_identity(), normalized_path=song.normalized_path),
        song=song,
        states=tuple(sorted(set(states))),
    )


def _reconcile_claim(normalized_path: str, worker_id: str, claimed_at_ms: int) -> WorkerClaim:
    return WorkerClaim(
        identity=WorkerClaimIdentity(song=_identity(normalized_path), worker_id=worker_id, claim_type="reconcile"),
        claimed_at_ms=claimed_at_ms,
    )


def _make_mock_db() -> MagicMock:
    mock_db = MagicMock()
    mock_db.library.list_songs_with_state.return_value = []
    mock_db.app.add_claim.return_value = True
    mock_db.app.song_state_membership.return_value = set()
    return mock_db


class TestClaimFilesForReconciliation:
    """Tests for ``claim_files_for_reconciliation``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_list_when_no_stale_or_pending_candidates(self) -> None:
        mock_db = _make_mock_db()

        result = claim_files_for_reconciliation(mock_db, _library(), "workers/test")

        assert result == []
        mock_db.app.add_claim.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_claims_available_candidate_successfully(self) -> None:
        mock_db = _make_mock_db()
        candidate = _candidate("song-123.mp3")
        mock_db.library.list_songs_with_state.side_effect = [[candidate], []]

        with patch(
            "nomarr.components.library.reconciliation_comp.now_ms",
            return_value=Milliseconds(10_000),
        ):
            result = claim_files_for_reconciliation(mock_db, _library(), "workers/test")

        assert result == [candidate]
        mock_db.app.add_claim.assert_called_once_with(
            _reconcile_claim("song-123.mp3", "workers/test", 10_000),
            lease_ms=60_000,
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_claims_pending_tag_write_candidate(self) -> None:
        mock_db = _make_mock_db()
        candidate = _candidate("song-123.mp3", states=(STATE_NOT_WRITTEN,))
        mock_db.library.list_songs_with_state.side_effect = [[], [candidate]]

        with patch(
            "nomarr.components.library.reconciliation_comp.now_ms",
            return_value=Milliseconds(10_000),
        ):
            result = claim_files_for_reconciliation(mock_db, _library(), "workers/test")

        assert result == [candidate]
        mock_db.app.add_claim.assert_called_once_with(
            _reconcile_claim("song-123.mp3", "workers/test", 10_000),
            lease_ms=60_000,
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_respects_batch_size_limit(self) -> None:
        mock_db = _make_mock_db()
        candidates = [_candidate(f"song-{index}.mp3") for index in range(5)]
        mock_db.library.list_songs_with_state.side_effect = [candidates, []]

        with patch(
            "nomarr.components.library.reconciliation_comp.now_ms",
            return_value=Milliseconds(20_000),
        ):
            result = claim_files_for_reconciliation(mock_db, _library(), "workers/test", batch_size=2)

        assert result == candidates[:2]
        assert mock_db.app.add_claim.call_count == 2
        expected = {_reconcile_claim(f"song-{index}.mp3", "workers/test", 20_000) for index in (0, 1)}
        for add_claim_call in mock_db.app.add_claim.call_args_list:
            assert add_claim_call.kwargs == {"lease_ms": 60_000}
            assert add_claim_call.args[0] in expected

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_skips_already_claimed_active_candidate(self) -> None:
        mock_db = _make_mock_db()
        mock_db.library.list_songs_with_state.side_effect = [[_candidate("song-123.mp3")], []]
        mock_db.app.add_claim.return_value = False

        with patch(
            "nomarr.components.library.reconciliation_comp.now_ms",
            return_value=Milliseconds(60_000),
        ):
            result = claim_files_for_reconciliation(mock_db, _library(), "workers/test", lease_ms=60_000)

        assert result == []
        mock_db.app.add_claim.assert_called_once_with(
            _reconcile_claim("song-123.mp3", "workers/test", 60_000),
            lease_ms=60_000,
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_empty_without_uuid_and_skips_reads(self) -> None:
        mock_db = _make_mock_db()
        library = Library(name="Unsaved", root_path="/music")

        result = claim_files_for_reconciliation(mock_db, library, "workers/test")

        assert result == []
        mock_db.library.list_songs_with_state.assert_not_called()


class TestSetFileWritten:
    """Tests for ``set_file_written``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_transitions_both_axes_and_releases_claim(self) -> None:
        mock_db = _make_mock_db()
        identity = _identity("song-123.mp3")
        mock_db.app.song_state_membership.return_value = {STATE_TAGS_NOT_FRESH}

        with patch("nomarr.components.library.reconciliation_comp.transition_song_state") as mock_transition:
            set_file_written(mock_db, identity, "worker:reconcile:0")

        assert mock_transition.call_args_list[0].args == (
            mock_db,
            [identity],
            STATE_NOT_WRITTEN,
            STATE_WRITTEN,
        )
        assert mock_transition.call_args_list[1].args == (
            mock_db,
            [identity],
            STATE_TAGS_NOT_FRESH,
            STATE_TAGS_CURRENT,
        )
        mock_db.app.remove_claim.assert_called_once_with(
            WorkerClaimIdentity(song=identity, worker_id="worker:reconcile:0", claim_type="reconcile")
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_only_transitions_written_axis_when_tags_are_current(self) -> None:
        mock_db = _make_mock_db()
        identity = _identity("song-123.mp3")

        with patch("nomarr.components.library.reconciliation_comp.transition_song_state") as mock_transition:
            set_file_written(mock_db, identity, "worker:reconcile:0")

        assert mock_transition.call_count == 1
        assert mock_transition.call_args_list[0].args == (
            mock_db,
            [identity],
            STATE_NOT_WRITTEN,
            STATE_WRITTEN,
        )


class TestReleaseClaim:
    """Tests for ``release_claim``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_releases_claim_via_app_api(self) -> None:
        mock_db = _make_mock_db()
        identity = _identity("song-123.mp3")

        release_claim(mock_db, identity, "worker:reconcile:0")

        mock_db.app.remove_claim.assert_called_once_with(
            WorkerClaimIdentity(song=identity, worker_id="worker:reconcile:0", claim_type="reconcile")
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_does_not_change_state_edges(self) -> None:
        mock_db = _make_mock_db()

        release_claim(mock_db, _identity("song-123.mp3"), "worker:reconcile:0")

        mock_db.app.song_state_membership.assert_not_called()


class TestCountFilesNeedingReconciliation:
    """Tests for ``count_files_needing_reconciliation``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_counts_deduplicated_locators_across_both_states(self) -> None:
        mock_db = _make_mock_db()
        mock_db.library.list_songs_with_state.side_effect = [
            [_candidate("a.mp3"), _candidate("b.mp3")],
            [_candidate("b.mp3", states=(STATE_NOT_WRITTEN,)), _candidate("c.mp3", states=(STATE_NOT_WRITTEN,))],
        ]

        result = count_files_needing_reconciliation(mock_db, _library())

        assert result == 3

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_when_no_candidates(self) -> None:
        mock_db = _make_mock_db()

        result = count_files_needing_reconciliation(mock_db, _library())

        assert result == 0

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_zero_without_uuid_and_skips_reads(self) -> None:
        mock_db = _make_mock_db()
        library = Library(name="Unsaved", root_path="/music")

        result = count_files_needing_reconciliation(mock_db, library)

        assert result == 0
        mock_db.library.list_songs_with_state.assert_not_called()
