# ADR-033: Multi-Cluster Taste Profile — Genre-Split Centroids

**Status:** Superseded by ADR-034  
**Date:** 2026-06-16  
**Tags:** taste-profile, playlist-generation, multi-cluster  
**Source Log:** rnd-architect#L4  

## Context

Personal playlist generation currently uses a single recency-weighted centroid embedding to represent a user's listening preferences. For users with diverse taste spanning multiple genres, this single centroid collapses distinct listening modes into a "mushy middle," degrading playlist quality across all five playlist types (Familiar, Discovery, Hidden Gems, Universal, Genre).

The original design document (DD-personal-playlist.md) anticipated a multi-cluster approach where each genre tag group produces its own centroid, and the TasteCluster DTO was created but never populated. The actual implementation drifted to a single-centroid contract.

Two alternatives were evaluated and rejected:
1. Builder-level multi-cluster (each builder independently does per-genre centroids) — duplicates work, no architectural improvement, only useful for phased rollout which this project does not do.
2. Greedy single-pass clustering (BIRCH-like, genre-agnostic) — overengineered for a well-tagged library, introduces a new tuning parameter without quality metrics to calibrate it.

## Decision

The taste profile component will compute per-genre recency-weighted centroids and return multiple clusters instead of a single centroid. The TasteProfile and NavidromePersonalPlaylistContext DTOs will carry list[TasteCluster] rather than a single centroid vector. The existing TasteCluster DTO gains a total_weight field for proportional interleaving.

An untagged-track fallback cluster is added — but only created when the untagged fraction exceeds a minimum threshold (5%), ensuring untagged tracks are not silently dropped while keeping the primary path optimized for tagged libraries.

All playlist builders are updated uniformly to iterate over clusters with per-cluster ANN search and weight-proportional interleaving, sharing a common helper to avoid logic duplication across builders.

## Consequences

- Architecture aligns with the original design doc (TasteCluster is finally populated)
- Clustering logic lives in one place (taste profile) instead of being duplicated across builders
- Each playlist builder performs N ANN searches (one per cluster) instead of 1 — performance impact bounded by capping clusters to configurable max
- DTO contract breaks for TasteProfile and NavidromePersonalPlaylistContext — all consumers must be updated in the same deployment
- All five builder functions are rewritten simultaneously (this project does phased deployment)
- Untagged track coverage is preserved without making data consistency Nomarr's problem

---

**Note:** This record is retained for history. ADR-034 (same title, Accepted) is the canonical version of this decision. The two records describe the same decision; ADR-034 carries the authoritative status and references.
