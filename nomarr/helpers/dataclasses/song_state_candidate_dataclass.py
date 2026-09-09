"""Typed song-state-read candidate (typed state-read owner, Plan C P2).

``SongStateCandidate`` is the semantic value returned by the persistence
``list_songs_with_state`` seam. It carries only semantic application values:
the mutable request-scoped ``SongLocator`` (``SongIdentity``), the domain
``Song``, and the set of state names the song is currently in. It never carries
``SongRow``, raw joined dictionaries, assignment/edge rows, the generated
``songs.id``, or an integer ``library_id`` (ADR-047/048; CONTRACTS §3/§5).

This is the minimal shape produced by the Plan C facade seam. The candidate
*contract* (exact fields/consumers/invariants) is owned by Plan J, which ratifies
or ratify-then-adjusts this shape after C; Plan K migrates integer state-read
callers onto it only after C/J are green.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
    from nomarr.helpers.dataclasses.song_dataclass import Song


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
