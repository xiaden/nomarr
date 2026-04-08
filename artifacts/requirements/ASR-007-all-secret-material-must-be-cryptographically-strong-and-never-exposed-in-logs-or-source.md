# ASR-007: All secret material must be cryptographically strong and never exposed in logs or source

**Status:** Active  
**Date:** 2026-04-09  
**Quality Attribute:** Security  
**Priority:** Critical  
**Source:** User requirement — April 2026  

## Stimulus

A secret (API key, token, credential) is generated, stored, or transmitted by the application

## Response Measure

All secrets are generated with a cryptographically secure source of randomness. Secrets at rest are stored in a form that cannot be trivially reversed. No secret value appears in any log output, error message, or HTTP response.

## Background

The application manages credentials for external music services, internal API tokens, and database access. Weak or exposed secrets are the most common class of self-hosted application security failure. Linked to ADR-001 (ONNX runtime, which eliminated a model loading path that previously had credential handling).

## Constraints

Secrets must be sourced from environment variables or a secrets provider — never hardcoded in source or config files. Secrets must not appear in logs, stack traces, or error responses.
