"""Caller-facing vector domain values for persistence reads.

These types are the contract at the ML persistence intent boundary for the
corrected read/search surface: :class:`SongVector` (one stored embedding for a
song/backbone), :class:`VectorMatch` (one ANN search result),
:class:`EmbeddingCounts` (hot/cold embedding tallies), and
:class:`BackboneVectorWrite` (the typed command that replaces one backbone's
stored embedding for a song).  They reuse the existing
:class:`~nomarr.helpers.dataclasses.song_command_dataclass.SongIdentity` natural
identity and carry only application semantics.  Row identifiers, storage
primary keys, table/column names, and timestamps remain persistence concerns
and are intentionally omitted.

These are frozen/slotted value objects with no ``from_row``/``to_dict``
persistence projections and no duplicate identity fields.
"""

from __future__ import annotations

from dataclasses import dataclass

from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity


@dataclass(frozen=True, slots=True)
class SongVector:
    """One stored embedding vector for a ``(song, backbone)`` read.

    ``vector`` is the actual stored embedding as an ordered tuple of floats.
    ``model_suite_hash`` carries the semantic suite hash read from the
    persisted ``model_id`` (or ``None`` when that value is null); the persisted
    ``model_suite_hash`` column stays ``""`` inside persistence.  ``genres``
    preserves the ``None`` versus non-empty distinction.  Row metadata
    (storage id, song foreign key, tier, timestamps) is omitted.
    """

    song: SongIdentity
    backbone: str
    vector: tuple[float, ...]
    model_suite_hash: str | None
    num_segments: int | None
    segmentation_hash: str | None
    genres: tuple[str, ...] | None

    def __post_init__(self) -> None:
        if not isinstance(self.song, SongIdentity):
            raise TypeError("SongVector.song must be a SongIdentity")
        if not isinstance(self.backbone, str) or not self.backbone.strip():
            raise ValueError("SongVector.backbone must not be blank")


@dataclass(frozen=True, slots=True)
class VectorMatch:
    """One ANN search result with an application similarity score.

    ``score`` is the cosine similarity ``clamp(1 - distance, -1, 1)``; its
    semantic range is ``[-1, 1]`` and is enforced by persistence, not re-checked
    here.  ``vector`` is optional and populated only when the caller requests it
    via ``include_vector``; a missing vector is ``None``.
    """

    song: SongIdentity
    backbone: str
    score: float
    vector: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.song, SongIdentity):
            raise TypeError("VectorMatch.song must be a SongIdentity")
        if not isinstance(self.backbone, str) or not self.backbone.strip():
            raise ValueError("VectorMatch.backbone must not be blank")


@dataclass(frozen=True, slots=True)
class EmbeddingCounts:
    """Hot and cold embedding tallies for a backbone."""

    hot_count: int
    cold_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class BackboneVectorWrite:
    """Command to replace one backbone's stored embedding for a song.

    Carries only application semantics: the embedding ``vector`` as an ordered
    tuple of floats, the optional ``num_segments``, the semantic
    ``model_suite_hash`` (persistence maps it to the persisted ``model_id``
    column while the persisted ``model_suite_hash`` column stays ``""``), the
    optional ``genres`` (``None`` persists as NULL, distinct from ``()``), and
    ``segmentation_hash`` which must remain ``None`` (persistence always writes
    ``segmentation_hash=NULL``).  Storage concerns are intentionally omitted:
    ``embed_dim`` is derived by persistence as ``len(vector)``, and storage ids,
    tier, and timestamps never cross this boundary.

    Note: the dataclass is ``kw_only`` so positional construction is
    impossible -- a docs-literal positional build can never misbind
    ``model_suite_hash`` into ``num_segments`` and instead fails loudly with a
    ``TypeError``. Callers always build the command with keyword arguments.
    """

    vector: tuple[float, ...]
    model_suite_hash: str
    num_segments: int | None = None
    genres: tuple[str, ...] | None = None
    segmentation_hash: None = None

    def __post_init__(self) -> None:
        if not isinstance(self.vector, tuple):
            raise TypeError("BackboneVectorWrite.vector must be a tuple")
        vector = tuple(float(value) for value in self.vector)
        object.__setattr__(self, "vector", vector)
        if self.num_segments is not None and not isinstance(self.num_segments, int):
            raise TypeError("BackboneVectorWrite.num_segments must be an int or None")
        if not isinstance(self.model_suite_hash, str):
            raise TypeError("BackboneVectorWrite.model_suite_hash must be a str")
        if not self.model_suite_hash.strip():
            raise ValueError("BackboneVectorWrite.model_suite_hash must not be blank")
        if self.genres is not None and not isinstance(self.genres, tuple):
            raise TypeError("BackboneVectorWrite.genres must be a tuple or None")
        if self.segmentation_hash is not None:
            raise ValueError("BackboneVectorWrite.segmentation_hash must remain None")


__all__ = ["BackboneVectorWrite", "EmbeddingCounts", "SongVector", "VectorMatch"]
