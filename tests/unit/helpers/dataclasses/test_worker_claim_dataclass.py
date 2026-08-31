"""Unit tests for the worker-claim domain value objects.

``TASK-worker-claims-intent-facade-A-correction`` Phase 1 (P1-S2): prove the
frozen/slotted ``WorkerClaimIdentity``, ``WorkerClaim``, and
``ClaimRemovalRequest`` carry only natural claim semantics and never expose
``WorkerClaimRow``, raw dictionaries/JSONB, generated row ids, encoded claim
keys, table names, or storage song ids.  See
``nomarr/helpers/dataclasses/worker_claim_dataclass.py``.
"""

from __future__ import annotations

import pytest

from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.worker_claim_dataclass import (
    ClaimRemovalRequest,
    WorkerClaim,
    WorkerClaimIdentity,
)

PERSISTENCE_FIELDS = ("id", "_key", "_id", "key", "value", "file_id", "claimed_at")
STORAGE_NAMES = ("WorkerClaimRow",)


def _song() -> SongIdentity:
    return SongIdentity(
        library=LibraryIdentity(name="lib", root_path="/music"),
        normalized_path="artist/album/track.flac",
    )


def _identity(**kwargs: object) -> WorkerClaimIdentity:
    base: dict[str, object] = {"song": _song(), "worker_id": "worker:tag:0"}
    base.update(kwargs)
    return WorkerClaimIdentity(**base)  # type: ignore[arg-type]


def _claim(**kwargs: object) -> WorkerClaim:
    base: dict[str, object] = {"identity": _identity(), "claimed_at_ms": 1234}
    base.update(kwargs)
    return WorkerClaim(**base)  # type: ignore[arg-type]


@pytest.mark.unit
class TestWorkerClaimIdentity:
    def test_is_frozen_and_slotted(self) -> None:
        identity = _identity()
        with pytest.raises(AttributeError):
            identity.worker_id = "other"  # type: ignore[misc]
        assert not hasattr(identity, "__dict__")

    def test_equality_by_value(self) -> None:
        other_song = SongIdentity(
            library=LibraryIdentity(name="lib2", root_path="/other"),
            normalized_path="other.flac",
        )
        assert _identity() == _identity()
        assert _identity() != _identity(worker_id="other")
        assert _identity() != _identity(claim_type="reconcile")
        assert _identity() != _identity(song=other_song)

    def test_blank_worker_id_rejected(self) -> None:
        for value in ("", "   "):
            with pytest.raises(ValueError):
                _identity(worker_id=value)

    def test_non_str_worker_id_rejected(self) -> None:
        for value in (None, 123):
            with pytest.raises(ValueError):
                _identity(worker_id=value)  # type: ignore[arg-type]

    def test_blank_claim_type_rejected(self) -> None:
        for value in ("", "   "):
            with pytest.raises(ValueError):
                _identity(claim_type=value)

    def test_claim_type_defaults_to_none(self) -> None:
        assert _identity().claim_type is None
        assert _identity(claim_type="reconcile").claim_type == "reconcile"

    def test_song_must_be_song_identity(self) -> None:
        with pytest.raises(TypeError):
            _identity(song="not-a-song")  # type: ignore[arg-type]


@pytest.mark.unit
class TestWorkerClaim:
    def test_is_frozen_and_slotted(self) -> None:
        claim = _claim()
        with pytest.raises(AttributeError):
            claim.claimed_at_ms = 0  # type: ignore[misc]
        assert not hasattr(claim, "__dict__")

    def test_equality_by_value(self) -> None:
        assert _claim() == _claim()
        assert _claim() != _claim(claimed_at_ms=0)
        assert _claim() != _claim(identity=_identity(claim_type="reconcile"))

    def test_negative_claimed_at_rejected(self) -> None:
        with pytest.raises(ValueError):
            _claim(claimed_at_ms=-1)

    def test_non_int_claimed_at_rejected(self) -> None:
        for value in (1.5, True, "42"):
            with pytest.raises((ValueError, TypeError)):
                _claim(claimed_at_ms=value)  # type: ignore[arg-type]

    def test_zero_claimed_at_valid(self) -> None:
        assert _claim(claimed_at_ms=0).claimed_at_ms == 0

    def test_identity_must_be_worker_claim_identity(self) -> None:
        with pytest.raises(TypeError):
            _claim(identity="not-an-identity")  # type: ignore[arg-type]

    def test_convenience_accessors(self) -> None:
        claim = _claim(identity=_identity(worker_id="w1", claim_type="reconcile"))
        assert claim.song == _song()
        assert claim.worker_id == "w1"
        assert claim.claim_type == "reconcile"

    def test_claimed_at_is_semantic_not_storage_column(self) -> None:
        # claimed_at_ms is a validated non-negative int-ms semantic timestamp,
        # not the worker_claims storage row id or claimed_at column.
        assert not hasattr(_claim(), "id")
        assert not hasattr(_claim(), "key")


@pytest.mark.unit
class TestClaimRemovalRequest:
    def test_is_frozen_and_slotted(self) -> None:
        request = ClaimRemovalRequest(worker_ids=("w1",))
        with pytest.raises(AttributeError):
            request.worker_ids = ()  # type: ignore[misc]
        assert not hasattr(request, "__dict__")

    def test_requires_at_least_one_filter_or_flag(self) -> None:
        with pytest.raises(ValueError):
            ClaimRemovalRequest()

    def test_accepts_each_single_filter(self) -> None:
        assert ClaimRemovalRequest(worker_ids=("w1",)).worker_ids == ("w1",)
        assert ClaimRemovalRequest(songs=(_song(),)).songs == (_song(),)
        assert ClaimRemovalRequest(stale_workers_before_ms=0).stale_workers_before_ms == 0
        assert ClaimRemovalRequest(remove_missing_songs=True).remove_missing_songs
        assert ClaimRemovalRequest(remove_completed_songs=True).remove_completed_songs
        assert ClaimRemovalRequest(remove_errored_songs=True).remove_errored_songs

    def test_blank_worker_ids_rejected(self) -> None:
        with pytest.raises(ValueError):
            ClaimRemovalRequest(worker_ids=("", "w2"))

    def test_songs_must_be_song_identities(self) -> None:
        with pytest.raises(TypeError):
            ClaimRemovalRequest(songs=("bad",))  # type: ignore[list-item]

    def test_negative_stale_workers_before_rejected(self) -> None:
        with pytest.raises(ValueError):
            ClaimRemovalRequest(stale_workers_before_ms=-1)

    def test_bool_stale_workers_before_rejected(self) -> None:
        with pytest.raises(ValueError):
            ClaimRemovalRequest(stale_workers_before_ms=True)  # type: ignore[arg-type]


@pytest.mark.unit
class TestWorkerClaimPersistenceAbsence:
    def test_no_persistence_owned_fields(self) -> None:
        for value in (_identity(), _claim(), ClaimRemovalRequest(worker_ids=("w1",))):
            for attr in PERSISTENCE_FIELDS:
                assert not hasattr(value, attr), f"{type(value).__name__} must not expose {attr!r}"

    def test_no_storage_encoded_key_or_song_id(self) -> None:
        # The deterministic key (``claim_<song_id>``) and storage song id are
        # repository-private encodings; the domain values expose only natural
        # identity.  The SongIdentity carries the natural library + path.
        claim = _claim()
        assert claim.song.normalized_path == "artist/album/track.flac"
        assert not hasattr(claim.song, "id")

    def test_no_legacy_row_type_reference(self) -> None:
        for name in STORAGE_NAMES:
            assert not hasattr(WorkerClaimIdentity, name)
            assert not hasattr(WorkerClaim, name)
            assert not hasattr(ClaimRemovalRequest, name)
