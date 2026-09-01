"""Cache identity for embedding-research matrix caches.

Part C contract: cache identity must include corpus hash and scoring-semantics
version in addition to backbone/pathway/threshold/representation/metric/aggregate
dimensions, and a cache hit is only accepted when the song-ID set and scoring
semantics match exactly.

Two helpers drive this:

* :func:`matrix_cache_identity` — a canonical sha256 over every identity
  dimension.  The returned identity string is used as (or compared against) a
  stored cache key; two caches collide only if every dimension matches.
* :func:`validate_matrix_cache_identity` — fails loudly unless the stored
  identity equals the expected one.

Versioned invalidation (:func:`versioned_cache_root`) keeps old cache roots on
disk but makes them unreadable once ``SCORING_SEMANTICS_VERSION`` or the corpus
hash changes: the root is keyed by ``v{version}/{corpus_hash}``, so a bump or a
different corpus simply points at a fresh root while the old bytes are
orphaned rather than rewritten.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

# Bump to invalidate every matrix cache when the *meaning* of stored scores
# changes (e.g. a weighting/scoring-semantics change).  Old roots remain on
# disk under their own ``v<N>`` directory but are no longer read.
SCORING_SEMANTICS_VERSION = 1


def matrix_cache_identity(
    *,
    backbone: str,
    pathway: str,
    threshold: float,
    rep_a: str,
    rep_b: str,
    aggregate: str,
    metric: str,
    song_ids: Sequence[str],
    corpus_hash: str,
    score_variant: str | None = None,
) -> str:
    """Canonical identity string for a matrix cache.

    Every dimension participates in the hash; two caches are identical only if
    all dimensions (including the *ordered* song-ID list and corpus hash)
    match exactly.  When *score_variant* is supplied it is validated against the
    allowed scoring surface and folded into the identity, so a cache built for
    the primary ``max_per_candidate_segment`` scoring method can never be
    confused with one built for a different scoring method (or an unlabelled
    generic aggregate, which is rejected by :func:`validate_score_variant`).
    """
    from scripts.embedding_research.strategy_binned._constants import (
        validate_score_variant as _validate_score_variant,
    )

    if score_variant is not None:
        _validate_score_variant(score_variant)
    payload = json.dumps(
        {
            "scoring_semantics_version": SCORING_SEMANTICS_VERSION,
            "corpus_hash": corpus_hash,
            "backbone": backbone,
            "pathway": pathway,
            "threshold": float(threshold),
            "rep_a": rep_a,
            "rep_b": rep_b,
            "aggregate": aggregate,
            "score_variant": score_variant,
            "metric": metric,
            "song_ids": list(song_ids),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_matrix_cache_identity(
    expected_identity: str,
    stored_identity: str | None,
    context: str,
) -> None:
    """Fail loudly unless the stored identity matches the expected one.

    A ``None`` stored identity (no prior cache entry) is accepted; a non-matching
    stored identity is a hard error — never a silent reuse of stale data.
    """
    if stored_identity is not None and stored_identity != expected_identity:
        raise ValueError(
            f"[{context}] matrix-cache identity mismatch: stored cache was built from a "
            f"different corpus/semantics/representation set and cannot be reused"
        )


def versioned_cache_root(
    base: Path,
    *,
    scoring_version: int = SCORING_SEMANTICS_VERSION,
    corpus_hash: str | None = None,
) -> Path:
    """Root directory for a matrix cache, keyed by version + corpus hash.

    Old roots remain on disk (``v1/...``, ``v2/...``) but a new version or
    corpus hash resolves to a distinct path, so stale entries are orphaned,
    never rewritten.
    """
    root = base / f"v{scoring_version}"
    if corpus_hash:
        root = root / corpus_hash
    return root
