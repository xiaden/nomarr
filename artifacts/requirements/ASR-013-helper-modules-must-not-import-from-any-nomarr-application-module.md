# ASR-013: Helper modules must not import from any nomarr application module

**Status:** Active  
**Date:** 2026-04-09  
**Quality Attribute:** Maintainability  
**Priority:** High  
**Source:** User requirement — April 2026  

## Stimulus

A developer adds a nomarr.* import to a helper module

## Response Measure

No helper module contains an import of any nomarr.* symbol. Import-linter catches violations at CI time.

## Background

Helpers are pure utilities: data structures, formatters, validators, math functions. They must work in any context — unit tests, CLI tools, scripts — without pulling in the application stack. An import of nomarr.services, nomarr.components, or any higher module in a helper creates a hidden coupling that makes the helper non-portable and risks circular imports.

## Constraints

Helpers may import from the Python standard library and third-party packages, but must not import from any nomarr.* module. This is enforced by import-linter.
