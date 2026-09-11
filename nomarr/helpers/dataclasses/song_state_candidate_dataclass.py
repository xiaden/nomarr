"""Semantic candidate returned by the typed song-state read (Plan H).

``SongStateCandidate`` is the contract-owned value returned by the persistence
``list_songs_with_state`` seam. It carries only the mutable, request-scoped
``SongLocator`` (the existing ``SongIdentity``), semantic ``Song`` values, and
state names. Persistence rows, raw joins, assignment rows, generated keys, and
integer fallbacks are intentionally not representable here (ADR-048;
CONTRACTS §3/§5).

Plan C owns the persistence implementation; Plan H owns this shape and its
consumer/invariant contract; Plan I migrates state-read callers after this seam
is green.
"""

from __future__ import annotations

from dataclasses import dataclass

from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
from nomarr.helpers.dataclasses.song_dataclass import Song


@dataclass(frozen=True, slots=True)
class IncompleteTagCandidate:
    """Semantic written-song result missing expected ML tag heads."""

    identity: SongIdentity
    song: Song
    matched_count: int
    missing_count: int
    missing_heads: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.identity, SongIdentity) or not isinstance(self.song, Song):
            raise TypeError("IncompleteTagCandidate requires semantic song values")
        if self.song.normalized_path != self.identity.normalized_path:
            raise ValueError("IncompleteTagCandidate locator and song paths must agree")
        if self.matched_count < 0 or self.missing_count < 1:
            raise ValueError("IncompleteTagCandidate counts are invalid")
        if not self.missing_heads or any(not head.strip() for head in self.missing_heads):
            raise ValueError("IncompleteTagCandidate.missing_heads must be non-empty")


@dataclass(frozen=True, slots=True)
class SongStateCandidate:
    """One song (with its locator) in a requested processing state.

    Attributes:
        identity: The mutable, request-scoped ``SongLocator`` (ADR-048)
            ``SongIdentity(library=..., normalized_path=...)``.
        song: The semantic domain ``Song`` values for the located song
            (``song.normalized_path`` equals ``identity.normalized_path``).
        states: Sorted, unique tuple of state *names* (domain vocabulary) the
            song is currently assigned to. Never state-table identifiers.
    """

    identity: SongIdentity
    song: Song
    states: tuple[str, ...]

    def __post_init__(self) -> None:
        """Reject malformed candidates at the semantic boundary."""
        if not isinstance(self.identity, SongIdentity):
            raise TypeError("SongStateCandidate.identity must be a SongIdentity")
        if not isinstance(self.song, Song):
            raise TypeError("SongStateCandidate.song must be a Song")
        if self.song.normalized_path != self.identity.normalized_path:
            raise ValueError("SongStateCandidate locator and song paths must agree")
        if not isinstance(self.states, tuple):
            raise TypeError("SongStateCandidate.states must be a tuple of state names")
        if any(not isinstance(state, str) or not state.strip() for state in self.states):
            raise ValueError("SongStateCandidate.states must contain non-blank state names")
        if self.states != tuple(sorted(set(self.states))):
            raise ValueError("SongStateCandidate.states must be sorted and unique")
