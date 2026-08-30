"""Domain value objects for persisted ML embedding streams (patches).

These types are the contract at the ML persistence intent boundary.  They carry
only the backbone identity and the raw embedding patches bytes; row identifiers,
song foreign keys, and timestamps remain persistence concerns.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EmbeddingStream:
    """Persisted embedding patches for one ``(song, backbone)`` pair.

    ``backbone`` is the backbone identifier scoping the stream; ``patches_emb``
    is the raw ``[n_patches, embed_dim]`` byte payload.  The storage row id,
    song foreign key, and timestamps are intentionally omitted so callers never
    depend on repository row shapes.
    """

    backbone: str
    patches_emb: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.backbone, str) or not self.backbone.strip():
            raise ValueError("EmbeddingStream.backbone must not be blank")
        if not isinstance(self.patches_emb, bytes):
            raise TypeError("EmbeddingStream.patches_emb must be bytes")


__all__ = ["EmbeddingStream"]
