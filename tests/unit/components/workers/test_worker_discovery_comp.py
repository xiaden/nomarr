"""Tests for nomarr.components.workers.worker_discovery_comp module."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.workers.worker_discovery_comp import (
    claim_file,
    cleanup_stale_claims,
    discover_and_claim_file,
    discover_next_file,
    get_active_claim_count,
    release_claim,
    release_claims_for_worker,
)
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.worker_claim_dataclass import ClaimRemovalRequest, WorkerClaim, WorkerClaimIdentity


def _identity(song_id: int) -> SongIdentity:
    return SongIdentity(library=LibraryIdentity(name="Test Library"), normalized_path=f"song-{song_id}.mp3")


def _untyped_claim(song_id: int, worker_id: str, claimed_at_ms: int) -> WorkerClaim:
    return WorkerClaim(
        identity=WorkerClaimIdentity(song=_identity(song_id), worker_id=worker_id, claim_type=None),
        claimed_at_ms=claimed_at_ms,
    )


class TestDiscoverNextFile:
    """Tests for discover_next_file."""

    @pytest.mark.unit
    def test_returns_file_id_when_file_found(self) -> None:
        mock_db = MagicMock()
        with patch(
            "nomarr.components.workers.worker_discovery_comp.discover_next_untagged_file",
            return_value={"id": 123},
        ) as mock_discover_next:
            result = discover_next_file(mock_db)

        assert result == "123"
        mock_discover_next.assert_called_once_with(
            mock_db,
            exclude_claimed=True,
        )

    @pytest.mark.unit
    def test_returns_none_when_no_file(self) -> None:
        mock_db = MagicMock()
        with patch(
            "nomarr.components.workers.worker_discovery_comp.discover_next_untagged_file",
            return_value=None,
        ):
            result = discover_next_file(mock_db)
        assert result is None


class TestClaimFile:
    """Tests for claim_file."""

    @pytest.mark.unit
    def test_returns_true_on_success(self) -> None:
        mock_db = MagicMock()
        mock_db.library.resolve_song_identity.return_value = _identity(123)
        mock_db.app.add_claim.return_value = True
        with patch(
            "nomarr.components.workers.worker_discovery_comp.now_ms",
            return_value=SimpleNamespace(value=999),
        ):
            result = claim_file(mock_db, "123", "worker:tag:0")
        assert result is True
        mock_db.app.add_claim.assert_called_once_with(_untyped_claim(123, "worker:tag:0", 999))

    @pytest.mark.unit
    def test_returns_false_when_song_unresolvable(self) -> None:
        mock_db = MagicMock()
        mock_db.library.resolve_song_identity.return_value = None
        result = claim_file(mock_db, "123", "worker:tag:0")
        assert result is False
        mock_db.app.add_claim.assert_not_called()

    @pytest.mark.unit
    def test_returns_false_when_claim_conflicts(self) -> None:
        mock_db = MagicMock()
        mock_db.library.resolve_song_identity.return_value = _identity(123)
        mock_db.app.add_claim.return_value = False
        with patch(
            "nomarr.components.workers.worker_discovery_comp.now_ms",
            return_value=SimpleNamespace(value=999),
        ):
            result = claim_file(mock_db, "123", "worker:tag:0")
        assert result is False


class TestReleaseClaim:
    """Tests for release_claim (untyped domain identity)."""

    @pytest.mark.unit
    def test_releases_untyped_claim_via_domain_identity(self) -> None:
        mock_db = MagicMock()
        mock_db.library.resolve_song_identity.return_value = _identity(123)
        release_claim(mock_db, 123, "worker:tag:0")
        mock_db.app.remove_claim.assert_called_once_with(
            WorkerClaimIdentity(song=_identity(123), worker_id="worker:tag:0", claim_type=None)
        )

    @pytest.mark.unit
    def test_noop_when_song_unresolvable(self) -> None:
        mock_db = MagicMock()
        mock_db.library.resolve_song_identity.return_value = None
        release_claim(mock_db, 123, "worker:tag:0")
        mock_db.app.remove_claim.assert_not_called()


class TestCleanupStaleClaims:
    """Tests for cleanup_stale_claims."""

    @pytest.mark.unit
    def test_uses_complete_removal_intent(self) -> None:
        mock_db = MagicMock()
        mock_db.app.remove_claims.return_value = 3
        with patch(
            "nomarr.components.workers.worker_discovery_comp.now_ms",
            return_value=SimpleNamespace(value=10000),
        ):
            result = cleanup_stale_claims(mock_db, heartbeat_timeout_ms=1000)

        assert result == 3
        mock_db.app.remove_claims.assert_called_once_with(
            ClaimRemovalRequest(
                stale_workers_before_ms=9000,
                remove_missing_songs=True,
                remove_completed_songs=True,
                remove_errored_songs=True,
            )
        )
        mock_db.app.list_claims.assert_not_called()
        mock_db.app.list_worker_health.assert_not_called()
        mock_db.library.list_songs_by_ids.assert_not_called()

    @pytest.mark.unit
    def test_returns_zero_without_removals(self) -> None:
        mock_db = MagicMock()
        mock_db.app.remove_claims.return_value = 0
        with patch(
            "nomarr.components.workers.worker_discovery_comp.now_ms",
            return_value=SimpleNamespace(value=10000),
        ):
            result = cleanup_stale_claims(mock_db, heartbeat_timeout_ms=1000)

        assert result == 0
        mock_db.app.remove_claims.assert_called_once()


class TestReleaseClaimsForWorker:
    """Tests for release_claims_for_worker."""

    @pytest.mark.unit
    def test_returns_integer_release_count(self) -> None:
        mock_db = MagicMock()
        mock_db.app.remove_claims.return_value = 4

        result = release_claims_for_worker(mock_db, "worker:tag:0")

        assert result == 4
        mock_db.app.remove_claims.assert_called_once_with(ClaimRemovalRequest(worker_ids=("worker:tag:0",)))
        mock_db.app.list_claims.assert_not_called()

    @pytest.mark.unit
    def test_returns_zero_without_claims(self) -> None:
        mock_db = MagicMock()
        mock_db.app.remove_claims.return_value = 0

        result = release_claims_for_worker(mock_db, "worker:tag:0")

        assert result == 0
        mock_db.app.remove_claims.assert_called_once_with(ClaimRemovalRequest(worker_ids=("worker:tag:0",)))


class TestDiscoverAndClaimFile:
    """Tests for the combined discover+claim helper."""

    @pytest.mark.unit
    def test_returns_file_id_when_discovered_and_claimed(self) -> None:
        mock_db = MagicMock()
        with (
            patch(
                "nomarr.components.workers.worker_discovery_comp.discover_next_file",
                return_value="123",
            ) as mock_discover,
            patch(
                "nomarr.components.workers.worker_discovery_comp.claim_file",
                return_value=True,
            ) as mock_claim,
        ):
            result = discover_and_claim_file(mock_db, "worker:tag:0")

        assert result == "123"
        mock_discover.assert_called_once_with(mock_db)
        mock_claim.assert_called_once_with(mock_db, "123", "worker:tag:0")

    @pytest.mark.unit
    def test_returns_none_when_claim_conflicts(self) -> None:
        mock_db = MagicMock()
        with (
            patch(
                "nomarr.components.workers.worker_discovery_comp.discover_next_file",
                return_value="123",
            ) as mock_discover,
            patch(
                "nomarr.components.workers.worker_discovery_comp.claim_file",
                return_value=False,
            ) as mock_claim,
        ):
            result = discover_and_claim_file(mock_db, "worker:tag:0")

        assert result is None
        mock_discover.assert_called_once_with(mock_db)
        mock_claim.assert_called_once_with(mock_db, "123", "worker:tag:0")

    @pytest.mark.unit
    def test_returns_none_without_claiming_when_no_file_discovered(self) -> None:
        mock_db = MagicMock()
        with (
            patch(
                "nomarr.components.workers.worker_discovery_comp.discover_next_file",
                return_value=None,
            ) as mock_discover,
            patch(
                "nomarr.components.workers.worker_discovery_comp.claim_file",
            ) as mock_claim,
        ):
            result = discover_and_claim_file(mock_db, "worker:tag:0")

        assert result is None
        mock_discover.assert_called_once_with(mock_db)
        mock_claim.assert_not_called()


class TestGetActiveClaimCount:
    """Tests for get_active_claim_count (thin delegation to count_claims)."""

    @pytest.mark.unit
    def test_returns_count_claims_value(self) -> None:
        mock_db = MagicMock()
        mock_db.app.count_claims.return_value = 7

        result = get_active_claim_count(mock_db)

        assert result == 7
        mock_db.app.count_claims.assert_called_once_with()
        mock_db.app.list_claims.assert_not_called()

    @pytest.mark.unit
    def test_returns_zero_without_claims(self) -> None:
        mock_db = MagicMock()
        mock_db.app.count_claims.return_value = 0

        result = get_active_claim_count(mock_db)

        assert result == 0
        mock_db.app.count_claims.assert_called_once_with()
