"""Worker-claim domain value objects.

``TASK-worker-claims-intent-facade-A-correction`` Phase 1: the immutable domain
contracts for the ``db.app`` claims intent facade.  They carry natural identities
and claim semantics only — never ``WorkerClaimRow``, raw dictionaries/JSONB,
generated row ids, encoded claim keys, table names, or storage song ids.

Natural song identity is ``SongIdentity`` (ADR-032/041).  ``worker_id`` is the
logical worker handle; ``claim_type`` is the optional claim kind (``None`` for
untyped claims, ``"reconcile"`` for reconciliation claims).  All timestamps are
integer milliseconds since epoch, per the persistence convention.
"""

from __future__ import annotations

from dataclasses import dataclass

from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity


def _require_str(value: object, name: str, *, allow_none: bool = False) -> None:
    """Validate a nonblank string field (optionally allowing ``None``)."""
    if value is None:
        if allow_none:
            return
        raise ValueError(f"{name} must not be None")
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    if not value.strip():
        raise ValueError(f"{name} must not be blank")


def _require_nonnegative_int(value: object, name: str, *, allow_none: bool = False) -> None:
    """Validate a non-negative integer millisecond value (optionally ``None``)."""
    if value is None:
        if allow_none:
            return
        raise ValueError(f"{name} must not be None")
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an int millisecond timestamp")
    if value < 0:
        raise ValueError(f"{name} must not be negative")


@dataclass(frozen=True, slots=True)
class WorkerClaimIdentity:
    """Logical identity of one worker's claim on one song.

    Uniquely addresses a claim by its natural song identity, the claiming
    worker, and the optional claim type.  Deliberately omits the worker-claim
    row id, encoded key, JSON payload, table name, and storage song id.
    """

    song: SongIdentity
    worker_id: str
    claim_type: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.song, SongIdentity):
            raise TypeError("WorkerClaimIdentity.song must be a SongIdentity")
        _require_str(self.worker_id, "WorkerClaimIdentity.worker_id")
        _require_str(self.claim_type, "WorkerClaimIdentity.claim_type", allow_none=True)


@dataclass(frozen=True, slots=True)
class WorkerClaim:
    """A worker's claim on a song at a point in time.

    ``claimed_at_ms`` is the non-negative integer-millisecond claim time.  The
    value object carries no storage shape: the claim key, JSONB payload, and
    generated row id live only inside persistence.
    """

    identity: WorkerClaimIdentity
    claimed_at_ms: int

    def __post_init__(self) -> None:
        if not isinstance(self.identity, WorkerClaimIdentity):
            raise TypeError("WorkerClaim.identity must be a WorkerClaimIdentity")
        _require_nonnegative_int(self.claimed_at_ms, "WorkerClaim.claimed_at_ms")

    @property
    def song(self) -> SongIdentity:
        """Convenience accessor for the claimed song's natural identity."""
        return self.identity.song

    @property
    def worker_id(self) -> str:
        """Convenience accessor for the claiming worker's handle."""
        return self.identity.worker_id

    @property
    def claim_type(self) -> str | None:
        """Convenience accessor for the optional claim type."""
        return self.identity.claim_type


@dataclass(frozen=True, slots=True)
class ClaimRemovalRequest:
    """Immutable intent command describing one complete claim-removal request.

    Explicit ``worker_ids`` and ``songs`` filters are supported, and the cleanup
    policy flags (``stale_workers_before_ms`` plus ``remove_missing_songs`` /
    ``remove_completed_songs`` / ``remove_errored_songs``) let a caller express a
    complete cleanup intent without listing claims, querying health/state, or
    extracting storage ids.  At least one filter or policy flag is required so an
    accidental all-claims delete cannot reach the routine API (all-claims deletion
    lives only under ``db.app.maintenance``).  Deduplication of overlapping
    filters is persistence-owned.
    """

    worker_ids: tuple[str, ...] = ()
    songs: tuple[SongIdentity, ...] = ()
    stale_workers_before_ms: int | None = None
    remove_missing_songs: bool = False
    remove_completed_songs: bool = False
    remove_errored_songs: bool = False

    def __post_init__(self) -> None:
        for worker_id in self.worker_ids:
            _require_str(worker_id, "ClaimRemovalRequest.worker_ids")
        for song in self.songs:
            if not isinstance(song, SongIdentity):
                raise TypeError("ClaimRemovalRequest.songs must contain SongIdentity values")
        _require_nonnegative_int(
            self.stale_workers_before_ms, "ClaimRemovalRequest.stale_workers_before_ms", allow_none=True
        )
        if not (
            self.worker_ids
            or self.songs
            or self.stale_workers_before_ms is not None
            or self.remove_missing_songs
            or self.remove_completed_songs
            or self.remove_errored_songs
        ):
            raise ValueError(
                "ClaimRemovalRequest must include at least one worker/song filter or cleanup policy flag "
                "(preventing an accidental unfiltered all-claims deletion)"
            )


__all__ = ["ClaimRemovalRequest", "WorkerClaim", "WorkerClaimIdentity"]
