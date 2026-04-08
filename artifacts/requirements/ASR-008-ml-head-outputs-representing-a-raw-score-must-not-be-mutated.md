# ASR-008: ML head outputs representing a raw score must not be mutated

**Status:** Active  
**Date:** 2026-04-09  
**Quality Attribute:** Data Integrity  
**Priority:** High  
**Source:** User requirement — April 2026  

## Stimulus

A downstream process (calibration, tagging, re-scoring) attempts to modify a stored raw ML head output

## Response Measure

Raw scores produced by ML heads are written once and never modified by downstream processing. All derived values are computed from the raw scores, not by overwriting them.

## Background

Before segment-level scoring was introduced, raw float scores from ML heads were the only source of truth. Mutating them downstream would corrupt everything that depended on them. This requirement is being superseded as the architecture shifts to segment stats as the immutable record. See the Deferred ASR for the replacement requirement.
