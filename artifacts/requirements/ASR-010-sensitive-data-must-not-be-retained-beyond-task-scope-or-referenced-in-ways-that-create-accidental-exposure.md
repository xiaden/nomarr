# ASR-010: Sensitive data must not be retained beyond task scope or referenced in ways that create accidental exposure

**Status:** Active  
**Date:** 2026-04-09  
**Quality Attribute:** Security  
**Priority:** High  
**Source:** User requirement — April 2026  

## Stimulus

The application processes or transmits sensitive data (credentials, tokens, user-identifying information)

## Response Measure

Sensitive data is not retained in memory or storage beyond the scope of the operation that requires it. No sensitive value is reachable through references that outlive that operation.

## Background

The application handles credentials, tokens, and user-associated data. Retaining sensitive values beyond the scope of the task that requires them — or capturing them in references that outlive that scope (closures, logs, caches) — creates exposure risk that is difficult to audit and easy to miss in review.

## Constraints

Sensitive values must not be captured in long-lived objects, closures, or caches. They must be consumed within the operation that requires them and must not flow into log output, error messages, or telemetry.
