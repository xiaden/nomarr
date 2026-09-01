"""Deterministic matching-corpus manifests for embedding-research analysis.

Part C contract: every flat/binned comparison must run on ONE validated,
deterministic per-backbone corpus.  ``MatchingCorpusManifest`` carries the
sorted song IDs and a stable corpus hash; ``build_matching_corpus`` derives
the deterministic corpus from the candidate universe intersected with the
availability of every required sidecar/bin/rep; ``validate_matching_corpus``
fails loudly (never silently intersects) on any song-ID set or order mismatch.

The corpus identity (sorted song IDs + eligibility/config inputs) also feeds
the cache-identity rules in :mod:`cache_identity` so that a cache hit is only
accepted when the corpus and scoring semantics match exactly.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence

# Requirement labels are namespace-separated, e.g. ``flat:medoid`` or
# ``ptc:quantile0.1:0.50``.  They describe the sidecar/bin/rep availability a
# song must satisfy to be eligible for the matching corpus.
REQUIREMENT_NAMESPACES: tuple[str, ...] = ("flat", "ptc", "ctp")


def _canonical_json(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def corpus_identity_hash(
    backbone: str,
    eligible_song_ids: Collection[str],
    eligibility_inputs: Mapping[str, object] | None = None,
) -> str:
    """Stable sha256 over the canonical serialization of the corpus identity.

    The eligibility inputs (rep types, aggregate methods, K, requirement
    labels, ...) participate in the hash so a config change yields a new
    corpus identity and invalidates any cache keyed on it.
    """
    canonical = _canonical_json(
        {
            "backbone": backbone,
            "eligible_song_ids": sorted(eligible_song_ids),
            "eligibility": sorted((eligibility_inputs or {}).items(), key=lambda kv: str(kv[0])),
        }
    )
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class MatchingCorpusManifest:
    """Immutable, deterministic per-backbone matching-corpus identity.

    Attributes:
        song_ids: Sorted tuple of song IDs that every compared configuration
            must provide, in canonical (manifest) order.
        corpus_hash: Stable sha256 over the canonical serialization of the
            backbone, the sorted song IDs, and the eligibility/config inputs.
        backbone: Embedding model identifier.
    """

    song_ids: tuple[str, ...]
    corpus_hash: str
    backbone: str

    def __post_init__(self) -> None:
        # Enforce canonical ordering so the dataclass is truly immutable and
        # two manifests for the same corpus compare equal regardless of input
        # order.
        object.__setattr__(self, "song_ids", tuple(sorted(self.song_ids)))

    def __len__(self) -> int:
        return len(self.song_ids)


def build_matching_corpus(
    backbone: str,
    candidate_song_ids: Collection[str],
    available_by_requirement: Mapping[str, Collection[str]],
    *,
    eligibility_inputs: Mapping[str, object] | None = None,
) -> MatchingCorpusManifest:
    """Deterministically select the matching corpus for a backbone.

    The matching corpus is the sorted intersection of the candidate universe
    with the availability of EVERY requirement (flat medoid, configured flat
    candidates, and each requested PTC/CTP configuration).  A song absent from
    any single required sidecar/bin/rep is excluded from the corpus so no
    comparison ever silently runs on a different ``n_songs``.
    """
    common = set(candidate_song_ids)
    for available in available_by_requirement.values():
        common &= set(available)
    song_ids = tuple(sorted(common))

    eligibility = dict(eligibility_inputs or {})
    eligibility["requirements"] = sorted(available_by_requirement)
    corpus_hash = corpus_identity_hash(backbone, song_ids, eligibility)
    return MatchingCorpusManifest(
        song_ids=song_ids,
        corpus_hash=corpus_hash,
        backbone=backbone,
    )


def validate_matching_corpus(
    manifest: MatchingCorpusManifest,
    song_ids: Sequence[str],
    context: str,
) -> None:
    """Fail loudly unless *song_ids* matches the manifest exactly (set + order).

    Raises ``ValueError`` on any song-ID set or order mismatch.  It never
    silently intersects: callers must skip/fail the configuration instead of
    comparing different corpora.
    """
    loaded = list(song_ids)
    expected = list(manifest.song_ids)
    if set(loaded) != set(expected):
        missing = sorted(set(expected) - set(loaded))
        extra = sorted(set(loaded) - set(expected))
        raise ValueError(
            f"[{context}] song-ID set mismatch vs matching-corpus manifest "
            f"(backbone={manifest.backbone}): missing={missing} extra={extra}"
        )
    if loaded != expected:
        raise ValueError(
            f"[{context}] song-ID order mismatch vs matching-corpus manifest "
            f"(backbone={manifest.backbone}): expected {expected}, got {loaded}"
        )
