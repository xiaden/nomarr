# ADR-034: Multi-Cluster Taste Profile — Genre-Split Centroids

**Status:** Accepted  
**Date:** 2026-06-16  
**Tags:** taste-profile, playlist-generation, multi-cluster  
**Source Log:** rnd-architect#L4  

## Context

Personal playlist generation currently uses a single recency-weighted centroid embedding to represent a user's listening preferences. For users with diverse taste spanning multiple genres, this single centroid collapses distinct listening modes into a "mushy middle," degrading playlist quality across all five playlist types (Familiar, Discovery, Hidden Gems, Universal, Genre). The original design document (DD-personal-playlist.md) anticipated a multi-cluster approach where each genre tag group produces its own centroid, and the TasteCluster DTO was created but never populated. The actual implementation drifted to a single-centroid contract. Two alternatives were evaluated and rejected: (1) Builder-level multi-cluster — duplicates work, no architectural improvement; (2) Greedy single-pass clustering — overengineered for a well-tagged library, introduces tuning parameter without quality metrics.

## Decision

The taste profile component will compute per-genre recency-weighted centroids and return multiple clusters instead of a single centroid. The TasteProfile and NavidromePersonalPlaylistContext DTOs will carry list[TasteCluster] rather than a single centroid vector. The existing TasteCluster DTO gains a total_weight field for proportional interleaving. An untagged-track fallback cluster is added — only created when the untagged fraction exceeds a minimum threshold (5%). All playlist builders are updated uniformly to iterate over clusters with per-cluster ANN search and weight-proportional interleaving, sharing a common helper to avoid logic duplication across builders.

## Consequences

- Architecture aligns with the original design doc (TasteCluster is finally populated)
- Clustering logic lives in one place (taste profile) instead of duplicated across builders
- Each playlist builder performs N ANN searches (one per cluster) instead of 1 — performance impact bounded by capping clusters to configurable max
- DTO contract breaks for TasteProfile and NavidromePersonalPlaylistContext — all consumers updated in same deployment
- All five builder functions rewritten simultaneously
- Untagged track coverage preserved without making data consistency Nomarr's problem

## References

- DD-personal-playlist: Original design doc that anticipated multi-cluster
- ADR-001: ONNX Runtime for ML inference (centroid computation is numpy, not ML)
- ADR-013: TaggingService for genre tag queries
