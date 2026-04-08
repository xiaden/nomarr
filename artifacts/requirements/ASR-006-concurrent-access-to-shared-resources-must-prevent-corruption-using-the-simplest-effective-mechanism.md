# ASR-006: Concurrent access to shared resources must prevent corruption using the simplest effective mechanism

**Status:** Active  
**Date:** 2026-04-08  
**Quality Attribute:** Availability  
**Priority:** High  
**Source:** User requirement — April 2026  

## Stimulus

Two or more workers attempt to access or modify the same shared resource concurrently

## Response Measure

No data corruption, duplicate processing, or lost updates occur due to concurrent access. The coordination mechanism chosen is the simplest one that provably prevents the hazard.

## Background

The system runs multiple workers that may operate on overlapping data (e.g., two workers scanning the same file, concurrent writes to the same document). The goal is correctness, not throughput maximalism. Complex distributed locking schemes introduce their own failure modes — the simplest mechanism that guarantees correctness is preferred.
