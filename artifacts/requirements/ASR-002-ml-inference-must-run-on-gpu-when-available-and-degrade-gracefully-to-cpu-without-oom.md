# ASR-002: ML inference must run on GPU when available and degrade gracefully to CPU without OOM

**Status:** Active  
**Date:** 2026-04-08  
**Quality Attribute:** Performance, Availability  
**Priority:** Critical  
**Source:** User requirement — April 2026  

## Stimulus

An ML inference workload is submitted while the system is under memory pressure or GPU contention

## Response Measure

Inference executes on GPU when available. If the system is straining, inference degrades gracefully to CPU. The process must not cause an out-of-memory condition on either path.

## Background

ML inference is the heaviest compute operation in the system. Unmanaged memory growth or hard GPU-only requirements would make the application unusable on CPU-only or memory-constrained hosts. See also ASR-012 (runtime architecture).
