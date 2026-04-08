# ASR-009: All ML-derived nom: tag values must be computed from segment stats and calibration before being written to file

**Status:** Deferred  
**Date:** 2026-04-09  
**Quality Attribute:** Data Integrity  
**Priority:** High  
**Source:** User requirement — April 2026  

## Stimulus

A nom: tag value is written to an audio file

## Response Measure

nom: tag values written to files are produced by a deterministic pipeline over segment stats and current calibration data. The segment stats and raw embeddings are the only values mutated during ML processing of a file; all tag outputs are derived, not stored intermediates.

## Background

As the architecture matures, segment-level stats (raw embeddings, per-segment scores) become the new immutable record. Tags written to files must be derived from these stats combined with calibration data — never computed ad-hoc or from mutable intermediate state. This replaces ASR-008 once the segment-stats pipeline is fully operational.
