"""Embedding and vector dataclasses used across Nomarr.

This module defines data containers for ML embedding streams, vector search
results, and related derived data flowing between the ML pipeline, persistence,
and API layers.

Usage:
    from v2.nomarr.helpers.dataclasses.embedding_dataclass import (
        EmbeddingStream,
        VectorEntry,
        VectorSearchResult,
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True, kw_only=True)
class EmbeddingStream:
    """Canonical temporal embedding stream for one ``(file, backbone)`` pair.

    Each document in the ``ml_embedding_streams`` collection stores a quantized
    backbone patch stream. The ``_key`` is deterministically derived from
    ``file_id`` and ``backbone``.
    """

    backbone: str
    """Backbone model identifier (e.g. ``"effnet"``)."""

    embed_dim: int
    """Dimensionality of the embedding."""

    num_patches: int
    """Number of temporal patches extracted."""

    stream_data: tuple[int, ...]
    """Int8-quantized patch stream, flattened row-major.

    Length must equal ``num_patches * embed_dim``.
    """

    def __post_init__(self) -> None:
        """Validate structural invariants."""
        if not self.id:
            raise ValueError("EmbeddingStream.id must not be empty")
        if not self.file_id:
            raise ValueError("EmbeddingStream.file_id must not be empty")
        if not self.backbone:
            raise ValueError("EmbeddingStream.backbone must not be empty")
        if self.embed_dim <= 0:
            raise ValueError(f"EmbeddingStream.embed_dim must be positive, got {self.embed_dim}")
        if self.num_patches <= 0:
            raise ValueError(f"EmbeddingStream.num_patches must be positive, got {self.num_patches}")
        expected_len = self.num_patches * self.embed_dim
        if len(self.stream_data) != expected_len:
            raise ValueError(
                f"EmbeddingStream.stream_data length {len(self.stream_data)} "
                f"does not match num_patches * embed_dim ({expected_len})"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class VectorEntry:
    """Single vector entry from a per-backbone vector collection.

    Used for both hot (recent) and cold (archival) vectors. Each entry
    references a file and carries metadata about the model suite and
    segmentation that produced it.
    """

    embed_dim: int
    """Dimensionality of the vector."""

    vector: tuple[int, ...]
    """Aggregated segment vector (int-encoded)."""

    num_segments: int
    """Number of audio segments that were pooled."""

    segmentation_hash: str
    """Hash of the segmentation parameters."""

    created_at: int
    """Epoch milliseconds when the vector was created."""

    genres: tuple[str, ...] | None = None
    """Genre labels associated with this vector (optional)."""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("VectorEntry.id must not be empty")
        if not self.file_id:
            raise ValueError("VectorEntry.file_id must not be empty")
        if self.embed_dim <= 0:
            raise ValueError(f"VectorEntry.embed_dim must be positive, got {self.embed_dim}")
        if len(self.vector) != self.embed_dim:
            raise ValueError(
                f"VectorEntry.vector length {len(self.vector)} does not match embed_dim ({self.embed_dim})"
            )
        if self.num_segments <= 0:
            raise ValueError(f"VectorEntry.num_segments must be positive, got {self.num_segments}")


@dataclass(frozen=True, slots=True, kw_only=True)
class VectorSearchResult:
    """Result from an approximate nearest-neighbour (ANN) vector search.

    Wraps a ``VectorEntry`` with its similarity score relative to the query.
    """

    entry: VectorEntry
    """The matching vector entry."""

    score: float
    """Cosine similarity score (higher = more similar)."""

    def __post_init__(self) -> None:
        if not -1.0 <= self.score <= 1.0:
            raise ValueError(f"VectorSearchResult.score must be in [-1, 1], got {self.score}")


@dataclass(frozen=True, slots=True, kw_only=True)
class OutputStream:
    """ML model output stream for one file/model-output pair.

    Stores the float activation values produced by an ONNX head model across
    all audio segments. Used as a cache to avoid re-running inference.
    """

    id: str
    """Unique record identifier (e.g. ``"ml_output_streams/abc"``)."""

    file_id: str
    """Identifier of the owning library file."""

    model_id: str
    """Identifier of the ML model that produced this output."""

    output_index: int
    """Index of this output within the model's outputs array."""

    values: tuple[float, ...]
    """Float activation values, one per audio segment."""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("OutputStream.id must not be empty")
        if not self.file_id:
            raise ValueError("OutputStream.file_id must not be empty")
        if not self.model_id:
            raise ValueError("OutputStream.model_id must not be empty")
        if self.output_index < 0:
            raise ValueError(f"OutputStream.output_index must be non-negative, got {self.output_index}")
        if not self.values:
            raise ValueError("OutputStream.values must not be empty")

    @classmethod
    def from_db_doc(cls, doc: dict[str, Any], *, file_id: str) -> OutputStream:
        """Construct an ``OutputStream`` from a raw DB document.

        Args:
            doc: Raw document from ``ml_output_streams``.
            file_id: The owning file's identifier (resolved from the data store).

        Returns:
            A validated ``OutputStream`` instance.
        """
        return cls(
            id=doc["_id"],
            file_id=file_id,
            model_id=doc.get("model_id", ""),
            output_index=doc.get("output_index", 0),
            values=tuple(doc.get("values", ())),
        )
