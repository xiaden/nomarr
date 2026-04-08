# ASR-001: Database queries must complete in bounded time regardless of collection size

**Status:** Active  
**Date:** 2026-04-08  
**Quality Attribute:** Performance  
**Priority:** High  
**Source:** User requirement — April 2026  

## Stimulus

A query is issued against a collection that has grown to production scale (tens to hundreds of thousands of documents)

## Response Measure

The query completes in bounded time. The system must not perform unbounded N+1 lookups or full-collection scans where indexed alternatives exist.

## Background

ArangoDB is the backing store. Collections grow over time. Query patterns that are acceptable at small scale (full scans, repeated per-document lookups) become unacceptable at production scale. Indexed traversals and batched AQL must be used instead.
