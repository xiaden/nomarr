# ADR-022: Progress indicator visual language: spinner for queries, progress bar for tasks

**Status:** Accepted  
**Date:** 2026-04-09  
**Tags:** frontend, ux, loading-states  

## Context

ASR-003 requires that any non-instant operation displays a progress indication. Operations fall into two categories: queries (data fetches — search, filter, record loads) and Tasks (long-running background jobs — library scans, ML tagging, calibration). These categories have different progress characteristics: queries are short-lived and return a single response, so progress cannot be expressed as a fraction; Tasks are long-lived and report incremental completion that can be expressed as a ratio. A consistent visual language is needed so users can immediately understand the nature of the operation in progress.

## Decision

Queries use a spinner as their progress indicator: shown while the request is in-flight, hidden on completion or error. Tasks use a progress bar as their progress indicator: it reflects the fraction of work completed as reported by the backend, shown for the duration of the task, and dismissed on completion or failure. Mixing these indicators — spinner for a Task, progress bar for a query — is a violation of this convention.

## Consequences

All frontend components that perform queries must expose a loading state and render a spinner. All frontend components that display Task progress must accept a numeric progress value and render a progress bar. The distinction between the two operation categories is a hard UI contract — it must be applied consistently across all views. New operation types must be explicitly classified as query or Task before implementation.

## References

ASR-003
