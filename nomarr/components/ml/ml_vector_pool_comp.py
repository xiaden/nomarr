"""Vector pooling utilities for backbone embedding persistence.

Pools segment-level embeddings [num_segments, embed_dim] into a single
track-level vector [embed_dim] suitable for ArangoDB storage and vector search.
"""

from __future__ import annotations

import numpy as np

from nomarr.components.ml.ml_embed_comp import pool_scores


def pool_embedding_for_storage(
    embeddings_2d: np.ndarray,
    *,
    mode: str = "trimmed_mean",
    trim_perc: float = 0.1,
) -> list[float]:
    """Pool segment-level embeddings into a single track-level vector.

    Uses the same pooling infrastructure as head score aggregation for
    consistency. Returns a plain Python list[float] for direct JSON
    serialization into ArangoDB documents.

    Args:
        embeddings_2d: Shape ``[num_segments, embed_dim]`` backbone output.
        mode: Pooling strategy ("mean", "median", "trimmed_mean").
        trim_perc: Fraction to trim from each tail when using trimmed_mean.

    Returns:
        List of floats with length ``embed_dim``.

    Raises:
        ValueError: If input is not 2-D or has zero columns.

    """
    if embeddings_2d.ndim != 2:
        msg = f"Expected 2-D array, got shape {embeddings_2d.shape}"
        raise ValueError(msg)
    if embeddings_2d.shape[1] == 0:
        msg = "Embedding dimension is 0"
        raise ValueError(msg)

    pooled: np.ndarray = pool_scores(
        embeddings_2d, mode=mode, trim_perc=trim_perc, nan_policy="omit",
    )
    return [float(x) for x in pooled]


def get_embedding_dimension(embeddings_2d: np.ndarray) -> int:
    """Return the embedding dimension (number of columns) of a 2-D array.

    Args:
        embeddings_2d: Shape ``[num_segments, embed_dim]``.

    Returns:
        The embed_dim value.

    Raises:
        ValueError: If input is not 2-D.

    """
    if embeddings_2d.ndim != 2:
        msg = f"Expected 2-D array, got shape {embeddings_2d.shape}"
        raise ValueError(msg)
    return int(embeddings_2d.shape[1])
